import logging
import random
import re

import numpy as np

from babeldoc.babeldoc_exception.BabelDOCException import ExtractTextError
from babeldoc.format.pdf.document_il import Box
from babeldoc.format.pdf.document_il import Document
from babeldoc.format.pdf.document_il import Page
from babeldoc.format.pdf.document_il import PdfCharacter
from babeldoc.format.pdf.document_il import PdfLine
from babeldoc.format.pdf.document_il import PdfParagraph
from babeldoc.format.pdf.document_il import PdfParagraphComposition
from babeldoc.format.pdf.document_il import PdfRectangle
from babeldoc.format.pdf.document_il import VisualBbox
from babeldoc.format.pdf.document_il.utils.fontmap import FontMapper
from babeldoc.format.pdf.document_il.utils.formular_helper import (
    collect_page_formula_font_ids,
)
from babeldoc.format.pdf.document_il.utils.layout_helper import (
    HEIGHT_NOT_USFUL_CHAR_IN_CHAR,
)
from babeldoc.format.pdf.document_il.utils.layout_helper import SPACE_REGEX
from babeldoc.format.pdf.document_il.utils.layout_helper import Layout
from babeldoc.format.pdf.document_il.utils.layout_helper import add_space_dummy_chars
from babeldoc.format.pdf.document_il.utils.layout_helper import build_layout_index
from babeldoc.format.pdf.document_il.utils.layout_helper import calculate_iou_for_boxes
from babeldoc.format.pdf.document_il.utils.layout_helper import get_char_unicode_string
from babeldoc.format.pdf.document_il.utils.layout_helper import get_character_layout
from babeldoc.format.pdf.document_il.utils.layout_helper import is_bullet_point
from babeldoc.format.pdf.document_il.utils.layout_helper import (
    is_character_in_formula_layout,
)
from babeldoc.format.pdf.document_il.utils.layout_helper import is_text_layout
from babeldoc.format.pdf.document_il.utils.paragraph_helper import is_cid_paragraph
from babeldoc.format.pdf.document_il.utils.style_helper import INDIGO
from babeldoc.format.pdf.document_il.utils.style_helper import WHITE
from babeldoc.format.pdf.translation_config import TranslationConfig

logger = logging.getLogger(__name__)

# Base58 alphabet (Bitcoin style, without numbers 0, O, I, l)
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def generate_base58_id(length: int = 5) -> str:
    """Generate a random base58 ID of specified length."""
    return "".join(random.choice(BASE58_ALPHABET) for _ in range(length))


class ParagraphFinder:
    stage_name = "Parse Paragraphs"

    # 定义项目符号的正则表达式模式

    def __init__(self, translation_config: TranslationConfig):
        self.translation_config = translation_config
        self.font_mapper = FontMapper(translation_config)

    def _preprocess_formula_layouts(self, page: Page):
        """
        Identifies 'formula' layouts that do not significantly overlap with any text layouts
        and re-labels them as 'isolate_formula'.
        """
        # Use a simplified Layout object for is_text_layout check
        text_layouts = [
            layout
            for layout in page.page_layout
            if is_text_layout(Layout(layout.id, layout.class_name))
        ]
        formula_layouts = [
            layout for layout in page.page_layout if layout.class_name == "formula"
        ]

        if not text_layouts or not formula_layouts:
            return

        for formula_layout in formula_layouts:
            is_isolated = True
            for text_layout in text_layouts:
                iou = calculate_iou_for_boxes(formula_layout.box, text_layout.box)
                if iou >= 0.5:
                    is_isolated = False
                    break

            if is_isolated:
                formula_layout.class_name = "isolate_formula"

    def add_text_fill_background(self, page: Page):
        layout_map = {layout.id: layout for layout in page.page_layout}
        for paragraph in page.pdf_paragraph:
            layout_id = paragraph.layout_id
            if layout_id is None:
                continue
            layout = layout_map[layout_id]
            if paragraph.box is None:
                continue
            x1, y1, x2, y2 = (
                paragraph.box.x,
                paragraph.box.y,
                paragraph.box.x2,
                paragraph.box.y2,
            )
            layout_box = layout.box
            if layout_box.x < x1:
                x1 = layout_box.x
            if layout_box.y < y1:
                y1 = layout_box.y
            if layout_box.x2 > x2:
                x2 = layout_box.x2
            if layout_box.y2 > y2:
                y2 = layout_box.y2
            assert x2 > x1 and y2 > y1
            page.pdf_rectangle.append(
                PdfRectangle(
                    box=Box(x1, y1, x2, y2),
                    fill_background=True,
                    graphic_state=WHITE,
                    debug_info=False,
                    xobj_id=paragraph.xobj_id,
                )
            )

    def update_paragraph_data(self, paragraph: PdfParagraph, update_unicode=False):
        if not paragraph.pdf_paragraph_composition:
            return

        chars = []
        for composition in paragraph.pdf_paragraph_composition:
            if composition.pdf_line:
                chars.extend(composition.pdf_line.pdf_character)
            elif composition.pdf_formula:
                chars.extend(composition.pdf_formula.pdf_character)
            elif composition.pdf_character:
                chars.append(composition.pdf_character)
            elif composition.pdf_same_style_unicode_characters:
                continue
            else:
                logger.error(
                    "Unexpected composition type"
                    " in PdfParagraphComposition. "
                    "This type only appears in the IL "
                    "after the translation is completed.",
                )
                continue

        if update_unicode and chars:
            paragraph.unicode = get_char_unicode_string(chars)
        if not chars:
            return
        # 更新边界框
        min_x = min(char.visual_bbox.box.x for char in chars)
        min_y = min(char.visual_bbox.box.y for char in chars)
        max_x = max(char.visual_bbox.box.x2 for char in chars)
        max_y = max(char.visual_bbox.box.y2 for char in chars)
        paragraph.box = Box(min_x, min_y, max_x, max_y)
        first_real_char = next((char for char in chars if char.xobj_id is not None), chars[0])
        paragraph.vertical = first_real_char.vertical
        paragraph.xobj_id = first_real_char.xobj_id

        paragraph.first_line_indent = False
        if (
            paragraph.pdf_paragraph_composition
            and paragraph.pdf_paragraph_composition[0].pdf_line
            and paragraph.pdf_paragraph_composition[0]
            .pdf_line.pdf_character[0]
            .visual_bbox.box.x
            - paragraph.box.x
            > 1
        ):
            paragraph.first_line_indent = True

    def update_line_data(self, line: PdfLine):
        min_x = min(char.visual_bbox.box.x for char in line.pdf_character)
        min_y = min(char.visual_bbox.box.y for char in line.pdf_character)
        max_x = max(char.visual_bbox.box.x2 for char in line.pdf_character)
        max_y = max(char.visual_bbox.box.y2 for char in line.pdf_character)
        line.box = Box(min_x, min_y, max_x, max_y)

    def add_debug_info(self, page: Page):
        if not self.translation_config.debug:
            return
        for paragraph in page.pdf_paragraph:
            for composition in paragraph.pdf_paragraph_composition:
                if composition.pdf_line:
                    line = composition.pdf_line
                    page.pdf_rectangle.append(
                        PdfRectangle(
                            box=line.box,
                            fill_background=False,
                            graphic_state=INDIGO,
                            debug_info=True,
                            line_width=0.2,
                        )
                    )

    def process(self, document):
        with self.translation_config.progress_monitor.stage_start(
            self.stage_name,
            len(document.page),
        ) as pbar:
            if not document.page:
                return
            for page in document.page:
                self.translation_config.raise_if_cancelled()
                self.process_page(page)
                pbar.advance()

            total_paragraph_count = 0
            for page in document.page:
                total_paragraph_count += len(page.pdf_paragraph)
            if total_paragraph_count == 0:
                raise ExtractTextError("The document contains no paragraphs.")

            if self.check_cid_paragraph(document):
                raise ExtractTextError("The document contains too many CID paragraphs.")

    def check_cid_paragraph(self, doc: Document):
        cid_para_count = 0
        para_total = 0
        for page in doc.page:
            para_total += len(page.pdf_paragraph)
            for para in page.pdf_paragraph:
                if is_cid_paragraph(para):
                    cid_para_count += 1
        return cid_para_count / para_total > 0.8

    def bbox_overlap(self, bbox1: Box, bbox2: Box) -> bool:
        return (
            bbox1.x < bbox2.x2
            and bbox1.x2 > bbox2.x
            and bbox1.y < bbox2.y2
            and bbox1.y2 > bbox2.y
        )

    def process_page(self, page: Page):
        layout_index, layout_map = build_layout_index(page)
        # 预处理公式布局的标签
        self._preprocess_formula_layouts(page)

        # 第一步：根据 layout 创建 paragraphs
        # 在这一步中，page.pdf_character 中的字符会被移除
        paragraphs = self._group_characters_into_paragraphs(
            page, layout_index, layout_map
        )
        page.pdf_paragraph = paragraphs

        page_level_formula_font_ids, xobj_specific_formula_font_ids = (
            collect_page_formula_font_ids(
                page, self.translation_config.formular_font_pattern
            )
        )

        # for para in paragraphs:
        #     if not para.debug_id:
        #         continue
        #     new_line = PdfLine(
        #         pdf_character=[x.pdf_character for x in para.pdf_paragraph_composition]
        #     )
        #     self.update_line_data(new_line)
        #     para.pdf_paragraph_composition = [
        #         PdfParagraphComposition(pdf_line=new_line)
        #     ]

        # 第二步：将段落内的字符拆分为行
        for paragraph in paragraphs:
            if (
                paragraph.xobj_id
                and paragraph.xobj_id in xobj_specific_formula_font_ids
            ):
                current_formula_font_ids = xobj_specific_formula_font_ids[
                    paragraph.xobj_id
                ]
            else:
                current_formula_font_ids = page_level_formula_font_ids
            self._split_paragraph_into_lines(paragraph, current_formula_font_ids)

        # 第三步：处理段落中的空格
        for paragraph in paragraphs:
            add_space_dummy_chars(paragraph)
            self.process_paragraph_spacing(paragraph)
            self.update_paragraph_data(paragraph)

        # 第四步：计算所有行宽度的中位数
        median_width = self.calculate_median_line_width(paragraphs)

        # 第五步：处理独立段落
        self.process_independent_paragraphs(paragraphs, median_width)
        self.merge_inline_text_fragments(paragraphs)
        self.merge_instruction_list_continuations(paragraphs)
        self.split_instruction_list_paragraphs(paragraphs)
        self.split_toc_entry_paragraphs(paragraphs)
        self.merge_toc_page_number_fragments(paragraphs)

        # 新增后处理：合并带行号交替的正文段落（a 正文、b 行号、c 正文 -> 合并 a 与 c，保留 b）
        if getattr(self.translation_config, "merge_alternating_line_numbers", True):
            self.merge_alternating_line_number_paragraphs(paragraphs)

        self.split_toc_entry_paragraphs(paragraphs)
        self.merge_toc_page_number_fragments(paragraphs)
        self.repair_toc_split_fragments(paragraphs)
        self.merge_inline_text_fragments(paragraphs)
        self.merge_instruction_list_continuations(paragraphs)
        self.split_instruction_list_paragraphs(paragraphs)
        self.split_toc_entry_paragraphs(paragraphs)
        self.merge_toc_page_number_fragments(paragraphs)

        for paragraph in paragraphs:
            self.update_paragraph_data(paragraph, update_unicode=True)

        if self.translation_config.ocr_workaround:
            self.add_text_fill_background(page)
            # since this is ocr file,
            # image characters are not needed
            page.pdf_character = []

        self.fix_overlapping_paragraphs(page)
        self.repair_toc_split_fragments(page.pdf_paragraph)
        self.repair_labeled_toc_prefix_fragments(page.pdf_paragraph)
        self.repair_toc_unicode_fragments(page.pdf_paragraph)

        # 第六步：对每一行的字符进行排序
        # self._sort_characters_in_lines(page)

        self.add_debug_info(page)

        # 新阶段：设置段落的 renderorder 为所有组成部分中 renderorder 最小的
        self._set_paragraph_render_order(page)

    def _set_paragraph_render_order(self, page: Page):
        """
        设置段落的 renderorder 为段落所有组成部分中 renderorder 最小的值
        """
        for paragraph in page.pdf_paragraph:
            min_render_order = 9999999999999999

            # 遍历段落的所有组成部分
            for composition in paragraph.pdf_paragraph_composition:
                # 检查 PdfLine 中的字符
                if composition.pdf_line:
                    for char in composition.pdf_line.pdf_character:
                        if (
                            hasattr(char, "render_order")
                            and char.render_order is not None
                        ):
                            min_render_order = min(min_render_order, char.render_order)

                # 检查单个字符
                elif composition.pdf_character:
                    char = composition.pdf_character
                    if hasattr(char, "render_order") and char.render_order is not None:
                        min_render_order = min(min_render_order, char.render_order)

                # 检查公式中的字符
                elif composition.pdf_formula:
                    for char in composition.pdf_formula.pdf_character:
                        if (
                            hasattr(char, "render_order")
                            and char.render_order is not None
                        ):
                            min_render_order = min(min_render_order, char.render_order)

            # 如果找到了有效的 renderorder，设置段落的 renderorder
            if min_render_order != 9999999999999999:
                paragraph.render_order = min_render_order

    def is_isolated_formula(self, char: PdfCharacter):
        return char.char_unicode in (
            "(cid:122)",
            "(cid:123)",
            "(cid:124)",
            "(cid:125)",
        )

    def _paragraph_text_ascii(self, p: PdfParagraph) -> str:
        parts: list[str] = []
        for comp in p.pdf_paragraph_composition or []:
            if comp.pdf_line:
                for ch in comp.pdf_line.pdf_character or []:
                    if ch.char_unicode is not None:
                        parts.append(ch.char_unicode)
            elif comp.pdf_character and comp.pdf_character.char_unicode is not None:
                parts.append(comp.pdf_character.char_unicode)
        return "".join(parts)

    def _is_ascii_digit_or_space_paragraph(self, p: PdfParagraph) -> bool:
        text = self._paragraph_text_ascii(p)
        if not text:
            return True
        has_digit = False
        for c in text:
            if c.isdigit() and ord(c) < 128:
                has_digit = True
                continue
            if c.isspace():
                continue
            return False
        return True if has_digit or text.strip() == "" else False

    @staticmethod
    def _same_layout_and_xobj(a: PdfParagraph, c: PdfParagraph) -> bool:
        return (
            a.layout_id is not None
            and c.layout_id is not None
            and a.layout_id == c.layout_id
            and a.xobj_id is not None
            and c.xobj_id is not None
            and a.xobj_id == c.xobj_id
        )

    def merge_alternating_line_number_paragraphs(self, paragraphs: list[PdfParagraph]):
        # a 代表正文
        # l 代表行号
        if not paragraphs or len(paragraphs) < 3:
            return
        i = 0
        while i < len(paragraphs) - 2:
            a = paragraphs[i]
            # 吞掉一个或多个连续的行号段 l
            j = i + 1
            saw_l = False
            while j < len(paragraphs) and self._is_ascii_digit_or_space_paragraph(
                paragraphs[j]
            ):
                saw_l = True
                j += 1
            # 现在 j 指向候选的 c
            if saw_l and j < len(paragraphs):
                c = paragraphs[j]
                if self._same_layout_and_xobj(a, c):
                    a.pdf_paragraph_composition.extend(c.pdf_paragraph_composition)
                    self.update_paragraph_data(a)
                    del paragraphs[j]
                    # 不移动 i，继续尝试把更多正文接到 a，实现 a l+ a l+ a ... 链式合并
                    continue
            i += 1

    def _group_characters_into_paragraphs(
        self, page: Page, layout_index, layout_map
    ) -> list[PdfParagraph]:
        paragraphs: list[PdfParagraph] = []
        if page.pdf_paragraph:
            paragraphs.extend(page.pdf_paragraph)
            page.pdf_paragraph = []

        char_areas = [
            (char.visual_bbox.box.x2 - char.visual_bbox.box.x)
            * (char.visual_bbox.box.y2 - char.visual_bbox.box.y)
            for char in page.pdf_character
        ]
        median_char_area = 0.0
        if char_areas:
            char_areas.sort()
            mid = len(char_areas) // 2
            median_char_area = (
                char_areas[mid]
                if len(char_areas) % 2 == 1
                else (char_areas[mid - 1] + char_areas[mid]) / 2
            )

        current_paragraph: PdfParagraph | None = None
        current_layout: Layout | None = None
        skip_chars = []

        for char in page.pdf_character:
            char_layout = get_character_layout(char, layout_index, layout_map)
            # Check if character is in any formula layout and set formula_layout_id
            char.formula_layout_id = is_character_in_formula_layout(
                char, page, layout_index, layout_map
            )

            if not is_text_layout(char_layout) or self.is_isolated_formula(char):
                skip_chars.append(char)
                continue

            char_box = char.visual_bbox.box
            # char_pdf_box = char.box
            # if calculate_iou_for_boxes(char_box, char_pdf_box) < 0.2:
            #     char_box = char_pdf_box
            char_area = (char_box.x2 - char_box.x) * (char_box.y2 - char_box.y)
            is_small_char = char_area < median_char_area * 0.05

            is_new_paragraph = False
            if current_paragraph is None:
                is_new_paragraph = True
            elif (
                not (
                    is_small_char
                    and current_paragraph.pdf_paragraph_composition
                    and char_layout.id == current_layout.id
                )
                and char.char_unicode not in HEIGHT_NOT_USFUL_CHAR_IN_CHAR
            ):
                if (
                    (
                        char_layout.id != current_layout.id
                        and not SPACE_REGEX.match(char.char_unicode)
                    )
                    or (  # not same xobject
                        current_paragraph.pdf_paragraph_composition
                        and current_paragraph.pdf_paragraph_composition[
                            -1
                        ].pdf_character.xobj_id
                        != char.xobj_id
                    )
                    or (
                        is_bullet_point(char)
                        and not current_paragraph.pdf_paragraph_composition
                    )
                ):
                    is_new_paragraph = True

            if is_new_paragraph:
                current_layout = char_layout
                current_paragraph = PdfParagraph(
                    pdf_paragraph_composition=[],
                    layout_id=current_layout.id,
                    debug_id=generate_base58_id(),
                    layout_label=current_layout.name,
                )
                paragraphs.append(current_paragraph)

            current_paragraph.pdf_paragraph_composition.append(
                PdfParagraphComposition(pdf_character=char)
            )

        page.pdf_character = skip_chars
        for para in paragraphs:
            self.update_paragraph_data(para)
        return paragraphs

    def _merge_overlapping_clusters(
        self, lines: dict[int, list[PdfCharacter]], char_height_average: float
    ) -> dict[int, list[PdfCharacter]]:
        """
        Merge clusters that have significant y-axis overlap.
        If y_intersection / min_height > 0.5 or the distance between y-midlines is less than char_height_average, merge the two clusters.
        """
        if len(lines) <= 1:
            return lines

        # Calculate y-axis ranges for each cluster
        cluster_ranges = {}
        cluster_midlines = {}
        for label, chars in lines.items():
            y_values = [char.visual_bbox.box.y for char in chars] + [
                char.visual_bbox.box.y2 for char in chars
            ]
            y_min, y_max = min(y_values), max(y_values)
            cluster_ranges[label] = (y_min, y_max)
            cluster_midlines[label] = (y_min + y_max) / 2

        # Keep merging until no more merges are possible
        changed = True
        while changed:
            changed = False
            labels_to_check = list(lines.keys())

            for i in range(len(labels_to_check)):
                if not changed:  # Only continue if no merge happened in this iteration
                    for j in range(i + 1, len(labels_to_check)):
                        label1, label2 = labels_to_check[i], labels_to_check[j]

                        # Skip if either label has been merged away
                        if label1 not in lines or label2 not in lines:
                            continue

                        y1_min, y1_max = cluster_ranges[label1]
                        y2_min, y2_max = cluster_ranges[label2]

                        # Calculate intersection
                        intersection_start = max(y1_min, y2_min)
                        intersection_end = min(y1_max, y2_max)

                        # Calculate midline distance
                        midline_distance = abs(
                            cluster_midlines[label1] - cluster_midlines[label2]
                        )

                        should_merge = False
                        if (
                            intersection_end > intersection_start
                        ):  # There is intersection
                            intersection_height = intersection_end - intersection_start
                            height1 = y1_max - y1_min
                            height2 = y2_max - y2_min
                            min_height = min(height1, height2)

                            # Check if intersection ratio exceeds threshold
                            if (
                                min_height > 0
                                and intersection_height / min_height > 0.3
                            ):
                                should_merge = True

                        # Check if midline distance is less than char_height_average
                        if midline_distance < char_height_average:
                            should_merge = True

                        if should_merge:
                            # Merge label2 into label1
                            lines[label1].extend(lines[label2])
                            del lines[label2]

                            # Update cluster range and midline for the merged cluster
                            new_y_min = min(y1_min, y2_min)
                            new_y_max = max(y1_max, y2_max)
                            cluster_ranges[label1] = (new_y_min, new_y_max)
                            cluster_midlines[label1] = (new_y_min + new_y_max) / 2
                            del cluster_ranges[label2]
                            del cluster_midlines[label2]

                            changed = True
                            break

        return lines

    def _get_effective_y_bounds(self, char: PdfCharacter) -> tuple[float, float]:
        """
        Determines the effective vertical boundaries (y1, y2) for a character.

        It prioritizes the visual bounding box if its Intersection over Union (IoU)
        with the PDF bounding box is high (>= 0.5), otherwise, it falls back to the
        PDF bounding box. This helps use more accurate layout information when available.
        """
        visual_box = char.visual_bbox.box
        return visual_box.y, visual_box.y2
        pdf_box = char.box
        if calculate_iou_for_boxes(visual_box, pdf_box) >= 0.5:
            return visual_box.y, visual_box.y2
        return pdf_box.y, pdf_box.y2

    @staticmethod
    def _compute_collision_counts_histogram(
        y1_arr: np.ndarray,
        y2_arr: np.ndarray,
        para_y_min: float,
        para_y_max: float,
        step: float,
    ) -> np.ndarray:
        """Compute overlap counts at each scan line using a difference-array histogram.

        Args:
            y1_arr: 1-D array with lower y bounds of characters (inclusive).
            y2_arr: 1-D array with upper y bounds of characters (exclusive).
            para_y_min: Minimum y of the paragraph.
            para_y_max: Maximum y of the paragraph.
            step: Scan step size.

        Returns:
            1-D NumPy int32 array where index i corresponds to y = para_y_max - i × step.
        """
        # Number of scan positions
        m = int(np.ceil((para_y_max - para_y_min) / step))
        if m <= 0:
            return np.array([], dtype=np.int32)

        # Map character bounds to discrete indices (top inclusive, bottom exclusive)
        starts = np.floor((para_y_max - y2_arr) / step).astype(np.int32)
        ends = np.floor((para_y_max - y1_arr) / step).astype(np.int32) + 1
        # Clip ends to the valid range [0, m]
        np.clip(ends, 0, m, out=ends)

        hist = np.zeros(m + 1, dtype=np.int32)
        np.add.at(hist, starts, 1)
        np.add.at(hist, ends, -1)

        return np.cumsum(hist[:-1])

    def _split_paragraph_into_lines(
        self, paragraph: PdfParagraph, formula_font_ids: set[str]
    ):
        """
        Splits a paragraph into lines using a "line-threading" method.

        This method works by scanning vertically across the paragraph's bounding
        box and counting how many characters intersect with a horizontal line
        at each y-coordinate. The regions with a low number of intersections
        (less than 2) are identified as gaps between lines. The characters
        are then partitioned into lines based on these identified gaps.
        """
        if not paragraph.pdf_paragraph_composition:
            return

        # 1. Extract all characters and other compositions from the paragraph.
        all_chars: list[PdfCharacter] = []
        other_compositions: list[PdfParagraphComposition] = []
        for comp in paragraph.pdf_paragraph_composition:
            if comp.pdf_character:
                all_chars.append(comp.pdf_character)
            else:
                other_compositions.append(comp)

        if not all_chars:
            return

        # 2. Determine effective y-bounds for each character and the paragraph's total vertical range.
        char_y_bounds = [
            {"char": char, "y1": y1, "y2": y2}
            for char in all_chars
            for y1, y2 in [self._get_effective_y_bounds(char)]
        ]

        if not char_y_bounds:
            paragraph.pdf_paragraph_composition = other_compositions
            self.update_paragraph_data(paragraph)
            return

        para_y_min = min(b["y1"] for b in char_y_bounds)
        para_y_max = max(b["y2"] for b in char_y_bounds)

        # If the paragraph is vertically flat, treat it as a single line.
        if (para_y_max - para_y_min) < 5:  # Using a small threshold
            # all_chars.sort(key=lambda c: c.visual_bbox.box.x)
            single_line_composition = self.create_line(all_chars)
            paragraph.pdf_paragraph_composition = [
                single_line_composition
            ] + other_compositions
            self.update_paragraph_data(paragraph)
            return

        # 3. Perform "threading" scan to create a collision histogram.
        # Scan from top (max y) to bottom (min y) with a step of 0.5.
        scan_y_min = para_y_min
        scan_y_max = para_y_max
        step = 0.25

        y_coordinates = np.arange(scan_y_max, scan_y_min, -step)

        # Compute collision counts using NumPy histogram (O(m + n))
        y1_arr = np.array([b["y1"] for b in char_y_bounds], dtype=np.float32)
        y2_arr = np.array([b["y2"] for b in char_y_bounds], dtype=np.float32)
        collision_counts = self._compute_collision_counts_histogram(
            y1_arr,
            y2_arr,
            scan_y_min,
            scan_y_max,
            step,
        )

        # 4. Find gaps (regions with low collision count) from the histogram.
        gaps = []
        in_gap = False
        for i, count in enumerate(collision_counts):
            if count < 1 and not in_gap:
                in_gap = True
                gap_start_index = i
            elif count >= 1 and in_gap:
                in_gap = False
                gaps.append((gap_start_index, i - 1))
        if in_gap:
            gaps.append((gap_start_index, len(collision_counts) - 1))

        # If no significant gaps are found, treat it as a single line.
        if not gaps:
            # all_chars.sort(key=lambda c: c.visual_bbox.box.x)
            single_line_composition = self.create_line(all_chars)
            paragraph.pdf_paragraph_composition = [
                single_line_composition
            ] + other_compositions
            self.update_paragraph_data(paragraph)
            return

        # 5. Assign characters to lines based on the identified gaps.
        # Calculate separator y-coordinates from the midpoints of the gaps.
        separator_y_coords = sorted(
            [y_coordinates[start_idx] for start_idx, end_idx in gaps],
            reverse=True,
        )

        lines: list[list[PdfCharacter]] = [
            [] for _ in range(len(separator_y_coords) + 1)
        ]

        for b in char_y_bounds:
            char_y_center = (b["y1"] + b["y2"]) / 2
            line_idx = 0
            # Find which line bucket the character belongs to.
            for sep_y in separator_y_coords:
                if char_y_center > sep_y:
                    break
                line_idx += 1
            lines[line_idx].append(b["char"])

        # 6. Rebuild the paragraph's composition list from the new lines.
        new_line_compositions = []
        for line_chars in lines:
            if line_chars:
                # Sort characters within each line by x-coordinate (left-to-right).
                # line_chars.sort(key=lambda c: c.visual_bbox.box.x)
                new_line_compositions.append(self.create_line(line_chars))

        # The lines are already sorted vertically due to the scanning process.
        paragraph.pdf_paragraph_composition = new_line_compositions + other_compositions
        self.update_paragraph_data(paragraph)

    def process_paragraph_spacing(self, paragraph: PdfParagraph):
        if not paragraph.pdf_paragraph_composition:
            return

        # 处理行级别的空格
        processed_lines = []
        for composition in paragraph.pdf_paragraph_composition:
            if not composition.pdf_line:
                processed_lines.append(composition)
                continue

            line = composition.pdf_line
            if not "".join(
                x.char_unicode for x in line.pdf_character
            ).strip():  # 跳过完全空白的行
                continue

            # 处理行内字符的尾随空格
            processed_chars = []
            for char in line.pdf_character:
                if not char.char_unicode.isspace():
                    processed_chars = processed_chars + [char]
                elif processed_chars:  # 只有在有非空格字符后才考虑保留空格
                    processed_chars.append(char)

            # 移除尾随空格
            while processed_chars and processed_chars[-1].char_unicode.isspace():
                processed_chars.pop()

            if processed_chars:  # 如果行内还有字符
                line = self.create_line(processed_chars)
                processed_lines.append(line)

        paragraph.pdf_paragraph_composition = processed_lines
        self.update_paragraph_data(paragraph)

    def create_line(self, chars: list[PdfCharacter]) -> PdfParagraphComposition:
        assert chars

        line = PdfLine(pdf_character=chars)
        self.update_line_data(line)
        return PdfParagraphComposition(pdf_line=line)

    def calculate_median_line_width(self, paragraphs: list[PdfParagraph]) -> float:
        # 收集所有行的宽度
        line_widths = []
        for paragraph in paragraphs:
            for composition in paragraph.pdf_paragraph_composition:
                if composition.pdf_line:
                    line = composition.pdf_line
                    line_widths.append(line.box.x2 - line.box.x)

        if not line_widths:
            return 0.0

        # 计算中位数
        line_widths.sort()
        mid = len(line_widths) // 2
        if len(line_widths) % 2 == 0:
            return (line_widths[mid - 1] + line_widths[mid]) / 2
        return line_widths[mid]

    def process_independent_paragraphs(
        self,
        paragraphs: list[PdfParagraph],
        median_width: float,
    ):
        i = 0
        while i < len(paragraphs):
            paragraph = paragraphs[i]
            if len(paragraph.pdf_paragraph_composition) <= 1:  # 跳过只有一行的段落
                i += 1
                continue

            j = 1
            while j < len(paragraph.pdf_paragraph_composition):
                prev_composition = paragraph.pdf_paragraph_composition[j - 1]
                if not prev_composition.pdf_line:
                    j += 1
                    continue

                prev_line = prev_composition.pdf_line
                prev_width = prev_line.box.x2 - prev_line.box.x
                prev_text = "".join([c.char_unicode for c in prev_line.pdf_character])

                # 检查是否包含目录点线（至少 20 个点，允许点之间有空格）
                if self._has_toc_dot_leader(prev_text):
                    # 创建新的段落
                    new_paragraph = PdfParagraph(
                        box=Box(0, 0, 0, 0),  # 临时边界框
                        pdf_paragraph_composition=(
                            paragraph.pdf_paragraph_composition[j:]
                        ),
                        unicode="",
                        debug_id=generate_base58_id(),
                        layout_label=paragraph.layout_label,
                        layout_id=paragraph.layout_id,
                    )
                    # 更新原段落
                    paragraph.pdf_paragraph_composition = (
                        paragraph.pdf_paragraph_composition[:j]
                    )

                    # 更新两个段落的数据
                    self.update_paragraph_data(paragraph)
                    self.update_paragraph_data(new_paragraph)

                    # 在原段落后插入新段落
                    paragraphs.insert(i + 1, new_paragraph)
                    break

                # 如果前一行宽度小于中位数的一半，将当前行及后续行分割成新段落
                if (
                    self.translation_config.split_short_lines
                    and prev_width
                    < median_width * self.translation_config.short_line_split_factor
                ) or (
                    paragraph.pdf_paragraph_composition
                    and (current_line := paragraph.pdf_paragraph_composition[j])
                    and (line := current_line.pdf_line)
                    and (chars := line.pdf_character)
                    and (char := chars[0])
                    and is_bullet_point(char)
                ):
                    # 创建新的段落
                    new_paragraph = PdfParagraph(
                        box=Box(0, 0, 0, 0),  # 临时边界框
                        pdf_paragraph_composition=(
                            paragraph.pdf_paragraph_composition[j:]
                        ),
                        unicode="",
                        debug_id=generate_base58_id(),
                        layout_label=paragraph.layout_label,
                        layout_id=paragraph.layout_id,
                    )
                    # 更新原段落
                    paragraph.pdf_paragraph_composition = (
                        paragraph.pdf_paragraph_composition[:j]
                    )

                    # 更新两个段落的数据
                    self.update_paragraph_data(paragraph)
                    self.update_paragraph_data(new_paragraph)

                    # 在原段落后插入新段落
                    paragraphs.insert(i + 1, new_paragraph)
                    break
                j += 1
            i += 1

    @staticmethod
    def _get_line_text(line: PdfLine) -> str:
        return get_char_unicode_string(line.pdf_character)

    @staticmethod
    def _is_instruction_list_label(text: str) -> bool:
        return (
            re.match(
                r"^[A-Z][A-Z0-9]*(?:/[A-Z][A-Z0-9]*)*\s+\S",
                text.strip(),
            )
            is not None
        )

    @staticmethod
    def _line_y_overlap_ratio(a: PdfLine, b: PdfLine) -> float:
        if not a.box or not b.box:
            return 0.0
        overlap = min(a.box.y2, b.box.y2) - max(a.box.y, b.box.y)
        if overlap <= 0:
            return 0.0
        min_height = min(a.box.y2 - a.box.y, b.box.y2 - b.box.y)
        if min_height <= 0:
            return 0.0
        return overlap / min_height

    def _append_line_chars(self, target: PdfLine, source: PdfLine):
        space_char = self._make_inline_space_char(target, source)
        if space_char:
            target.pdf_character.append(space_char)
        target.pdf_character.extend(source.pdf_character)
        target.pdf_character.sort(key=lambda c: c.visual_bbox.box.x)
        self.update_line_data(target)

    @staticmethod
    def _make_inline_space_char(
        target: PdfLine,
        source: PdfLine,
    ) -> PdfCharacter | None:
        if not target.pdf_character or not source.pdf_character:
            return None

        target_text = get_char_unicode_string(target.pdf_character).rstrip()
        source_text = get_char_unicode_string(source.pdf_character).lstrip()
        if not target_text or not source_text:
            return None
        if not source_text[0].isalnum():
            return None

        last_char = max(target.pdf_character, key=lambda c: c.visual_bbox.box.x2)
        first_char = min(source.pdf_character, key=lambda c: c.visual_bbox.box.x)
        gap = first_char.visual_bbox.box.x - last_char.visual_bbox.box.x2
        if gap <= 0:
            return None
        should_insert = target_text[-1] in ",;:" or gap > 2
        if not should_insert:
            return None

        width = min(gap, max(gap * 0.8, 1))
        box = Box(
            x=last_char.visual_bbox.box.x2,
            y=first_char.visual_bbox.box.y,
            x2=last_char.visual_bbox.box.x2 + width,
            y2=first_char.visual_bbox.box.y2,
        )
        return PdfCharacter(
            pdf_style=first_char.pdf_style,
            box=box,
            char_unicode=" ",
            scale=first_char.scale,
            advance=box.x2 - box.x,
            visual_bbox=VisualBbox(box=box),
        )

    def merge_inline_text_fragments(self, paragraphs: list[PdfParagraph]):
        """Join same-baseline text fragments split by overlapping layout boxes."""
        index = 1
        while index < len(paragraphs):
            previous = paragraphs[index - 1]
            current = paragraphs[index]
            previous_line = self._get_last_line(previous)
            current_line = self._get_first_line(current)
            if not previous_line or not current_line:
                index += 1
                continue

            if not self._can_merge_inline_fragment(
                previous,
                previous_line,
                current,
                current_line,
            ):
                index += 1
                continue

            self._append_line_chars(previous_line, current_line)
            current.pdf_paragraph_composition.pop(0)
            if current.pdf_paragraph_composition:
                self.update_paragraph_data(previous, update_unicode=True)
                self.update_paragraph_data(current, update_unicode=True)
                index += 1
            else:
                del paragraphs[index]
                self.update_paragraph_data(previous, update_unicode=True)

    def _can_merge_inline_fragment(
        self,
        previous: PdfParagraph,
        previous_line: PdfLine,
        current: PdfParagraph,
        current_line: PdfLine,
    ) -> bool:
        if previous.xobj_id != current.xobj_id:
            return False
        text_labels = ("plain text", "text", "paragraph", "content")
        if previous.layout_label not in text_labels:
            return False
        if current.layout_label != previous.layout_label and (
            current.layout_label != "fallback_line"
        ):
            return False
        if not previous_line.box or not current_line.box:
            return False
        if self._line_y_overlap_ratio(previous_line, current_line) < 0.45:
            return False
        gap = current_line.box.x - previous_line.box.x2
        if gap < -1 or gap > 12:
            return False

        current_text = self._get_line_text(current_line).strip()
        previous_text = self._get_line_text(previous_line).rstrip()
        if not current_text or self._is_instruction_list_label(current_text):
            return False
        if previous_text.endswith((".", ":", ";")) and current_text[0].isalnum():
            return False
        return True

    def merge_instruction_list_continuations(self, paragraphs: list[PdfParagraph]):
        index = 1
        while index < len(paragraphs):
            previous = paragraphs[index - 1]
            current = paragraphs[index]
            previous_line = self._get_last_line(previous)
            current_line = self._get_first_line(current)
            first_previous_line = self._get_first_line(previous)
            if not previous_line or not current_line or not first_previous_line:
                index += 1
                continue
            if not self._is_instruction_list_label(self._get_line_text(first_previous_line)):
                index += 1
                continue
            if self._is_instruction_list_label(self._get_line_text(current_line)):
                index += 1
                continue
            if previous.xobj_id != current.xobj_id:
                index += 1
                continue
            if not previous_line.box or not current_line.box:
                index += 1
                continue
            line_height = max(previous_line.box.y2 - previous_line.box.y, 1)
            vertical_gap = previous_line.box.y - current_line.box.y2
            description_x = self._instruction_description_x(first_previous_line)
            if (
                -1 <= vertical_gap <= line_height * 1.2
                and description_x is not None
                and abs(current_line.box.x - description_x) <= 8
            ):
                previous.pdf_paragraph_composition.extend(
                    current.pdf_paragraph_composition
                )
                self.update_paragraph_data(previous, update_unicode=True)
                del paragraphs[index]
                continue
            index += 1

    @staticmethod
    def _instruction_description_x(line: PdfLine) -> float | None:
        chars = line.pdf_character
        seen_non_space = False
        for index, char in enumerate(chars):
            text = char.char_unicode or ""
            if text.isspace() and seen_non_space:
                for next_char in chars[index + 1 :]:
                    if not (next_char.char_unicode or "").isspace():
                        return next_char.visual_bbox.box.x
                return None
            if not text.isspace():
                seen_non_space = True
        return None

    def split_instruction_list_paragraphs(self, paragraphs: list[PdfParagraph]):
        new_paragraphs: list[PdfParagraph] = []
        for paragraph in paragraphs:
            lines = [
                composition.pdf_line
                for composition in paragraph.pdf_paragraph_composition
                if composition.pdf_line
            ]
            if len(lines) < 3:
                new_paragraphs.append(paragraph)
                continue
            line_groups = self._split_instruction_list_lines(lines)
            if not line_groups:
                new_paragraphs.append(paragraph)
                continue

            for line_group in line_groups:
                new_paragraph = PdfParagraph(
                    box=Box(0, 0, 0, 0),
                    pdf_style=paragraph.pdf_style,
                    pdf_paragraph_composition=[
                        PdfParagraphComposition(pdf_line=line)
                        for line in line_group
                    ],
                    unicode="",
                    scale=paragraph.scale,
                    optimal_scale=paragraph.optimal_scale,
                    debug_id=generate_base58_id(),
                    layout_label=paragraph.layout_label,
                    layout_id=paragraph.layout_id,
                    render_order=paragraph.render_order,
                )
                self.update_paragraph_data(new_paragraph, update_unicode=True)
                new_paragraphs.append(new_paragraph)

        paragraphs[:] = new_paragraphs

    def _split_instruction_list_lines(
        self,
        lines: list[PdfLine],
    ) -> list[list[PdfLine]] | None:
        split_groups: list[list[PdfLine]] = []
        plain_group: list[PdfLine] = []
        current_instruction_group: list[PdfLine] | None = None
        instruction_count = 0
        first_label_x: float | None = None

        def flush_plain_group():
            nonlocal plain_group
            if plain_group:
                split_groups.append(plain_group)
                plain_group = []

        for line in lines:
            text = self._get_line_text(line).strip()
            is_instruction = self._is_instruction_list_label(text)
            if is_instruction:
                flush_plain_group()
                instruction_count += 1
                current_instruction_group = [line]
                split_groups.append(current_instruction_group)
                if first_label_x is None and line.box:
                    first_label_x = line.box.x
                continue

            if (
                current_instruction_group is not None
                and line.box
                and first_label_x is not None
                and line.box.x > first_label_x + 30
            ):
                current_instruction_group.append(line)
                continue

            current_instruction_group = None
            plain_group.append(line)

        flush_plain_group()

        if instruction_count < 3:
            return None

        if (
            len(split_groups) == 1
            and len(split_groups[0]) == len(lines)
        ):
            return None

        return split_groups

    @staticmethod
    def _has_toc_dot_leader(text: str) -> bool:
        return re.search(r"(?:\.\s*){20,}", text) is not None

    @staticmethod
    def _toc_entry_prefix_pattern() -> str:
        numeric_prefix = r"\d+(?:\.\d+)+"
        labeled_prefix = (
            r"[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,4}"
            r"\s+\d+(?:[-.]\d+)*\.?"
        )
        return rf"(?:{numeric_prefix}|{labeled_prefix})\s+"

    def split_toc_entry_paragraphs(self, paragraphs: list[PdfParagraph]):
        new_paragraphs: list[PdfParagraph] = []
        for paragraph in paragraphs:
            split_compositions: list[PdfParagraphComposition] = []
            changed = False

            for composition in paragraph.pdf_paragraph_composition:
                if not composition.pdf_line:
                    split_compositions.append(composition)
                    continue

                line_groups = self._split_toc_line_chars(composition.pdf_line)
                if len(line_groups) == 1:
                    split_compositions.append(composition)
                    continue

                changed = True
                for chars in line_groups:
                    line = PdfLine(pdf_character=chars)
                    self.update_line_data(line)
                    split_compositions.append(PdfParagraphComposition(pdf_line=line))

            if not changed:
                new_paragraphs.append(paragraph)
                continue

            for composition in split_compositions:
                new_paragraph = PdfParagraph(
                    box=Box(0, 0, 0, 0),
                    pdf_style=paragraph.pdf_style,
                    pdf_paragraph_composition=[composition],
                    unicode="",
                    scale=paragraph.scale,
                    optimal_scale=paragraph.optimal_scale,
                    debug_id=generate_base58_id(),
                    layout_label=paragraph.layout_label,
                    layout_id=paragraph.layout_id,
                    render_order=paragraph.render_order,
                )
                self.update_paragraph_data(new_paragraph, update_unicode=True)
                new_paragraphs.append(new_paragraph)

        paragraphs[:] = new_paragraphs

    def _split_toc_line_chars(self, line: PdfLine) -> list[list[PdfCharacter]]:
        text = get_char_unicode_string(line.pdf_character)
        if not self._has_toc_dot_leader(text):
            return [line.pdf_character]

        split_offsets = [
            match.start("next")
            for match in re.finditer(
                rf"(?<![-\d])(?P<page>\d+-\d+|\d+)\s+"
                rf"(?P<next>{self._toc_entry_prefix_pattern()})",
                text,
            )
        ]
        if not split_offsets:
            return [line.pdf_character]

        split_char_indexes: list[int] = []
        offset_index = 0
        text_offset = 0
        for char_index, char in enumerate(line.pdf_character):
            char_text = char.char_unicode or ""
            next_offset = text_offset + len(char_text)
            while (
                offset_index < len(split_offsets)
                and split_offsets[offset_index] < next_offset
            ):
                split_char_indexes.append(char_index)
                offset_index += 1
            text_offset = next_offset

        groups: list[list[PdfCharacter]] = []
        start = 0
        for split_index in split_char_indexes:
            if split_index <= start:
                continue
            groups.append(line.pdf_character[start:split_index])
            start = split_index
        if start < len(line.pdf_character):
            groups.append(line.pdf_character[start:])

        trimmed_groups = [self._trim_dummy_space_chars(group) for group in groups]
        return [group for group in trimmed_groups if group]

    def merge_toc_page_number_fragments(self, paragraphs: list[PdfParagraph]):
        for index in range(1, len(paragraphs)):
            previous = paragraphs[index - 1]
            current = paragraphs[index]
            previous_line = self._get_only_line(previous)
            current_line = self._get_only_line(current)
            if not previous_line or not current_line:
                continue

            previous_text = get_char_unicode_string(previous_line.pdf_character)
            current_text = get_char_unicode_string(current_line.pdf_character)
            if not (
                self._has_toc_dot_leader(previous_text)
                and self._has_toc_dot_leader(current_text)
            ):
                continue

            match = re.match(
                rf"(?:\.\s*)?(?P<fragment>\d+-\d+|-?\d+)\s+"
                rf"(?P<next>{self._toc_entry_prefix_pattern()})",
                current_text,
            )
            if not match:
                continue

            move_end = self._char_index_at_text_offset(
                current_line.pdf_character,
                match.end("fragment"),
            )
            keep_start = self._char_index_at_text_offset(
                current_line.pdf_character,
                match.start("next"),
            )
            if move_end <= 0 or keep_start <= move_end:
                continue

            previous_line.pdf_character.extend(current_line.pdf_character[:move_end])
            current_line.pdf_character = self._trim_dummy_space_chars(
                current_line.pdf_character[keep_start:],
            )
            if not current_line.pdf_character:
                continue

            self.update_line_data(previous_line)
            self.update_line_data(current_line)
            self.update_paragraph_data(previous, update_unicode=True)
            self.update_paragraph_data(current, update_unicode=True)

    def repair_toc_split_fragments(self, paragraphs: list[PdfParagraph]):
        changed = True
        while changed:
            changed = False
            for index in range(1, len(paragraphs)):
                previous = paragraphs[index - 1]
                current = paragraphs[index]
                previous_line = self._get_only_line(previous)
                current_line = self._get_only_line(current)
                if not previous_line or not current_line:
                    continue

                previous_text = get_char_unicode_string(previous_line.pdf_character)
                current_text = get_char_unicode_string(current_line.pdf_character)
                if not (
                    self._has_toc_dot_leader(previous_text)
                    and self._has_toc_dot_leader(current_text)
                ):
                    continue

                if self._move_leading_page_tail_to_previous(
                    previous,
                    previous_line,
                    previous_text,
                    current,
                    current_line,
                    current_text,
                ):
                    changed = True
                    continue

                if self._move_trailing_section_prefix_to_current(
                    previous,
                    previous_line,
                    previous_text,
                    current,
                    current_line,
                    current_text,
                ):
                    changed = True
                    continue

                if self._move_trailing_labeled_toc_prefix_to_current(
                    previous,
                    previous_line,
                    previous_text,
                    current,
                    current_line,
                    current_text,
                ):
                    changed = True

    def merge_isolated_toc_page_tails(self, paragraphs: list[PdfParagraph]):
        index = 1
        while index < len(paragraphs):
            previous = paragraphs[index - 1]
            current = paragraphs[index]
            next_paragraph = (
                paragraphs[index + 1] if index + 1 < len(paragraphs) else None
            )
            previous_line = self._get_only_line(previous)
            current_line = self._get_only_line(current)
            next_line = self._get_only_line(next_paragraph) if next_paragraph else None
            if not previous_line or not current_line:
                index += 1
                continue

            previous_text = get_char_unicode_string(previous_line.pdf_character)
            current_text = get_char_unicode_string(current_line.pdf_character).strip()
            next_text = (
                get_char_unicode_string(next_line.pdf_character) if next_line else ""
            )
            if not (
                self._has_toc_dot_leader(previous_text)
                and re.search(r"\d+-$", previous_text)
                and re.fullmatch(r"\d+", current_text)
                and (not next_text or self._has_toc_dot_leader(next_text))
            ):
                index += 1
                continue

            previous_line.pdf_character.extend(current_line.pdf_character)
            self.update_line_data(previous_line)
            self.update_paragraph_data(previous, update_unicode=True)
            del paragraphs[index]

    def repair_labeled_toc_prefix_fragments(self, paragraphs: list[PdfParagraph]):
        for index in range(1, len(paragraphs)):
            previous = paragraphs[index - 1]
            current = paragraphs[index]
            previous_line = self._get_last_line(previous)
            current_line = self._get_first_line(current)
            if not previous_line or not current_line:
                continue

            previous_text = get_char_unicode_string(previous_line.pdf_character)
            current_text = get_char_unicode_string(current_line.pdf_character)
            if not (
                self._has_toc_dot_leader(previous_text)
                and self._has_toc_dot_leader(current_text)
            ):
                continue

            self._move_trailing_labeled_toc_prefix_to_current(
                previous,
                previous_line,
                previous_text,
                current,
                current_line,
                current_text,
            )

    def repair_toc_unicode_fragments(self, paragraphs: list[PdfParagraph]):
        previous_clean_number: str | None = None
        previous_trailing_prefix: str | None = None

        for paragraph in paragraphs:
            text = (paragraph.unicode or "").strip()
            if not self._has_toc_dot_leader(text):
                previous_trailing_prefix = None
                continue

            raw_number_match = re.match(
                r"(?P<number>\.?\d+(?:\.\d+)*)\s+",
                text,
            )
            if not raw_number_match:
                previous_trailing_prefix = None
                continue

            raw_number = raw_number_match.group("number")
            fixed_number = raw_number
            if previous_trailing_prefix:
                fixed_number = self._combine_toc_number_fragments(
                    previous_trailing_prefix,
                    raw_number,
                    previous_clean_number,
                )
            elif raw_number.startswith(".") and previous_clean_number:
                fixed_number = self._complete_toc_number_from_previous(
                    previous_clean_number,
                    raw_number,
                )

            if fixed_number != raw_number:
                paragraph.unicode = fixed_number + text[raw_number_match.end("number") :]
                text = paragraph.unicode.strip()

            sequence_number = self._repair_toc_number_by_sequence(
                fixed_number,
                previous_clean_number,
            )
            if sequence_number and sequence_number != fixed_number:
                number_match = re.match(
                    r"(?P<number>\.?\d+(?:\.\d+)*)\s+",
                    text,
                )
                if number_match:
                    paragraph.unicode = (
                        sequence_number + text[number_match.end("number") :]
                    )
                    text = paragraph.unicode.strip()
                    fixed_number = sequence_number

            trailing_prefix_match = re.search(
                r"(?P<body>.*?\d+-\d+)\s+(?P<prefix>\d+(?:\.\d*)?)$",
                text,
            )
            if trailing_prefix_match:
                paragraph.unicode = trailing_prefix_match.group("body")
                previous_trailing_prefix = trailing_prefix_match.group("prefix")
                text = paragraph.unicode.strip()
            else:
                previous_trailing_prefix = None

            clean_number_match = re.match(r"(?P<number>\d+(?:\.\d+)*)\s+", text)
            if clean_number_match:
                previous_clean_number = clean_number_match.group("number")

    @staticmethod
    def _combine_toc_number_fragments(
        prefix: str,
        raw_number: str,
        previous_number: str | None,
    ) -> str:
        candidates: list[str] = []
        if raw_number.startswith(".") or prefix.endswith("."):
            candidates.append(prefix + raw_number)
        else:
            candidates.append(prefix + "." + raw_number)
            candidates.append(prefix + raw_number)

        if previous_number:
            expected = ParagraphFinder._increment_toc_number(previous_number)
            for candidate in candidates:
                if candidate == expected:
                    return candidate

        return candidates[0]

    @staticmethod
    def _complete_toc_number_from_previous(
        previous_number: str,
        raw_number: str,
    ) -> str:
        fragment_parts = raw_number.lstrip(".").split(".")
        previous_parts = previous_number.split(".")
        prefix_len = max(0, len(previous_parts) - len(fragment_parts))
        return ".".join(previous_parts[:prefix_len] + fragment_parts)

    @staticmethod
    def _increment_toc_number(number: str) -> str:
        parts = number.split(".")
        try:
            parts[-1] = str(int(parts[-1]) + 1)
        except ValueError:
            return number
        return ".".join(parts)

    @staticmethod
    def _repair_toc_number_by_sequence(
        current_number: str,
        previous_number: str | None,
    ) -> str | None:
        if not previous_number or not current_number:
            return None

        expected = ParagraphFinder._increment_toc_number(previous_number)
        current = current_number.lstrip(".")
        if current == expected:
            return None
        if expected.endswith("." + current):
            return expected
        if expected.split(".")[-1].endswith(current):
            return expected
        return None

    def _move_leading_page_tail_to_previous(
        self,
        previous: PdfParagraph,
        previous_line: PdfLine,
        previous_text: str,
        current: PdfParagraph,
        current_line: PdfLine,
        current_text: str,
    ) -> bool:
        if not re.search(r"\d+-$", previous_text):
            return False

        match = re.match(
            rf"(?P<fragment>\d+)\s+"
            rf"(?P<next>{self._toc_entry_prefix_pattern()})",
            current_text,
        )
        if not match:
            return False

        move_end = self._char_index_at_text_offset(
            current_line.pdf_character,
            match.end("fragment"),
        )
        keep_start = self._char_index_at_text_offset(
            current_line.pdf_character,
            match.start("next"),
        )
        if move_end <= 0 or keep_start <= move_end:
            return False

        previous_line.pdf_character.extend(current_line.pdf_character[:move_end])
        current_line.pdf_character = self._trim_dummy_space_chars(
            current_line.pdf_character[keep_start:],
        )
        if not current_line.pdf_character:
            return False

        self.update_line_data(previous_line)
        self.update_line_data(current_line)
        self.update_paragraph_data(previous, update_unicode=True)
        self.update_paragraph_data(current, update_unicode=True)
        return True

    def _move_trailing_section_prefix_to_current(
        self,
        previous: PdfParagraph,
        previous_line: PdfLine,
        previous_text: str,
        current: PdfParagraph,
        current_line: PdfLine,
        current_text: str,
    ) -> bool:
        match = re.search(
            r"(?P<page>\d+-\d+)\s+(?P<prefix>\d+(?:\.\d*)?)$",
            previous_text,
        )
        if not match:
            return False

        if not re.match(r"(?:\.\d+)+\s+|\d+(?:\.\d+)*\s+", current_text):
            return False

        prefix_start_offset = match.start("prefix")
        previous_keep_end_offset = prefix_start_offset
        while (
            previous_keep_end_offset > 0
            and previous_text[previous_keep_end_offset - 1].isspace()
        ):
            previous_keep_end_offset -= 1

        move_start = self._char_index_at_text_offset(
            previous_line.pdf_character,
            prefix_start_offset,
        )
        previous_keep_end = self._char_index_at_text_offset(
            previous_line.pdf_character,
            previous_keep_end_offset,
        )
        if move_start >= len(previous_line.pdf_character):
            return False

        moved_chars = previous_line.pdf_character[move_start:]
        previous_line.pdf_character = self._trim_dummy_space_chars(
            previous_line.pdf_character[:previous_keep_end],
        )
        current_line.pdf_character = self._trim_dummy_space_chars(
            moved_chars + current_line.pdf_character,
        )
        if not previous_line.pdf_character or not current_line.pdf_character:
            return False

        self.update_line_data(previous_line)
        self.update_line_data(current_line)
        self.update_paragraph_data(previous, update_unicode=True)
        self.update_paragraph_data(current, update_unicode=True)
        return True

    def _move_trailing_labeled_toc_prefix_to_current(
        self,
        previous: PdfParagraph,
        previous_line: PdfLine,
        previous_text: str,
        current: PdfParagraph,
        current_line: PdfLine,
        current_text: str,
    ) -> bool:
        match = re.search(
            r"(?P<body>.*?(?:\d+-\d+|-?\d+))\s+"
            r"(?P<prefix>[A-Z][A-Za-z]{0,8})$",
            previous_text,
        )
        if not match:
            return False

        if not re.match(r"[a-z][A-Za-z]*\s+\d+(?:[-.]\d+)*\.?\s+", current_text):
            return False

        combined = match.group("prefix") + current_text
        if not re.match(self._toc_entry_prefix_pattern(), combined):
            return False

        prefix_start_offset = match.start("prefix")
        previous_keep_end_offset = prefix_start_offset
        while (
            previous_keep_end_offset > 0
            and previous_text[previous_keep_end_offset - 1].isspace()
        ):
            previous_keep_end_offset -= 1

        move_start = self._char_index_at_text_offset(
            previous_line.pdf_character,
            prefix_start_offset,
        )
        previous_keep_end = self._char_index_at_text_offset(
            previous_line.pdf_character,
            previous_keep_end_offset,
        )
        if move_start >= len(previous_line.pdf_character):
            return False

        moved_chars = previous_line.pdf_character[move_start:]
        previous_line.pdf_character = self._trim_dummy_space_chars(
            previous_line.pdf_character[:previous_keep_end],
        )
        current_line.pdf_character = self._trim_dummy_space_chars(
            moved_chars + current_line.pdf_character,
        )
        if not previous_line.pdf_character or not current_line.pdf_character:
            return False

        self.update_line_data(previous_line)
        self.update_line_data(current_line)
        self.update_paragraph_data(previous, update_unicode=True)
        self.update_paragraph_data(current, update_unicode=True)
        return True

    @staticmethod
    def _get_only_line(paragraph: PdfParagraph) -> PdfLine | None:
        if len(paragraph.pdf_paragraph_composition) != 1:
            return None
        return paragraph.pdf_paragraph_composition[0].pdf_line

    @staticmethod
    def _get_first_line(paragraph: PdfParagraph) -> PdfLine | None:
        for composition in paragraph.pdf_paragraph_composition:
            if composition.pdf_line:
                return composition.pdf_line
        return None

    @staticmethod
    def _get_last_line(paragraph: PdfParagraph) -> PdfLine | None:
        for composition in reversed(paragraph.pdf_paragraph_composition):
            if composition.pdf_line:
                return composition.pdf_line
        return None

    @staticmethod
    def _char_index_at_text_offset(chars: list[PdfCharacter], offset: int) -> int:
        if offset <= 0:
            return 0
        text_offset = 0
        for char_index, char in enumerate(chars):
            text_offset += len(char.char_unicode or "")
            if text_offset >= offset:
                return char_index + 1
        return len(chars)

    @staticmethod
    def _trim_dummy_space_chars(chars: list[PdfCharacter]) -> list[PdfCharacter]:
        start = 0
        end = len(chars)
        while (
            start < end
            and chars[start].xobj_id is None
            and (chars[start].char_unicode or "").isspace()
        ):
            start += 1
        while (
            end > start
            and chars[end - 1].xobj_id is None
            and (chars[end - 1].char_unicode or "").isspace()
        ):
            end -= 1
        return chars[start:end]

    @staticmethod
    def is_bbox_contain_in_vertical(bbox1: Box, bbox2: Box) -> bool:
        """Check if one bounding box is completely contained within the other."""
        # Check if bbox1 is contained in bbox2
        bbox1_in_bbox2 = bbox1.y >= bbox2.y and bbox1.y2 <= bbox2.y2
        # Check if bbox2 is contained in bbox1
        bbox2_in_bbox1 = bbox2.y >= bbox1.y and bbox2.y2 <= bbox1.y2
        return bbox1_in_bbox2 or bbox2_in_bbox1

    def fix_overlapping_paragraphs(self, page: Page):
        """
        Adjusts the bounding boxes of paragraphs on a page to resolve vertical overlaps.

        Iteratively checks pairs of paragraphs and adjusts their vertical boundaries
        (y and y2) if they overlap, aiming to place the boundary at the midpoint
        of the vertical overlap.
        """
        paragraphs = page.pdf_paragraph
        if not paragraphs or len(paragraphs) < 2:
            return

        max_iterations = len(paragraphs) * len(paragraphs)  # Safety break
        iterations = 0

        while iterations < max_iterations:
            iterations += 1
            overlap_found_in_pass = False

            for i in range(len(paragraphs)):
                for j in range(i + 1, len(paragraphs)):
                    para1 = paragraphs[i]
                    para2 = paragraphs[j]

                    if para1.box is None or para2.box is None:
                        continue

                    if para1.xobj_id != para2.xobj_id:
                        continue

                    # Check for overlap using the existing method
                    if self.bbox_overlap(para1.box, para2.box):
                        if self.is_bbox_contain_in_vertical(para1.box, para2.box):
                            continue
                        # Calculate vertical overlap details
                        overlap_y_start = max(para1.box.y, para2.box.y)
                        overlap_y_end = min(para1.box.y2, para2.box.y2)
                        overlap_height = overlap_y_end - overlap_y_start

                        # Calculate horizontal overlap details
                        overlap_x_start = max(para1.box.x, para2.box.x)
                        overlap_x_end = min(para1.box.x2, para2.box.x2)
                        overlap_width = overlap_x_end - overlap_x_start

                        # Ensure there's a real 2D overlap, focusing on vertical adjustment
                        if overlap_height > 1e-6 and overlap_width > 1e-6:
                            overlap_found_in_pass = True

                            # Determine which paragraph is visually higher
                            if para1.box.y2 > para2.box.y and para1.box.y < para2.box.y:
                                lower_para = para1
                                higher_para = para2
                            # Handle cases where y values are identical (or very close)
                            # Prefer the one with smaller y2 as the higher one, or break tie arbitrarily
                            elif para1.box.y2 < para2.box.y2:
                                lower_para = para1
                                higher_para = para2
                            else:
                                lower_para = para2
                                higher_para = para1

                            # Calculate the midpoint of the vertical overlap
                            mid_y = overlap_y_start + overlap_height / 2

                            # Adjust boxes, ensuring they remain valid (y2 > y)
                            if mid_y > higher_para.box.y and mid_y < lower_para.box.y2:
                                higher_para.box.y = mid_y + 1
                                lower_para.box.y2 = mid_y - 1
                            else:
                                # This might happen if one box is fully contained vertically
                                # within another, or due to floating point issues.
                                # Log a warning and skip adjustment for this pair in this iteration.
                                # A more complex strategy might be needed for full containment.
                                logger.warning(
                                    "Could not resolve overlap between paragraphs"
                                    f" {higher_para.debug_id} and {lower_para.debug_id}"
                                    " using simple midpoint strategy."
                                    f" Midpoint: {mid_y},"
                                    f" Higher Box: {higher_para.box},"
                                    f" Lower Box: {lower_para.box}"
                                )

            # If no overlaps were found and adjusted in this pass, we're done.
            if not overlap_found_in_pass:
                break

        if iterations == max_iterations:
            logger.warning(
                f"Maximum iterations ({max_iterations}) reached in"
                f" fix_overlapping_paragraphs for page {page.page_number}."
                " Some overlaps might remain."
            )

    def _sort_characters_in_lines(self, page: Page):
        """Sort characters in each line from left to right, top to bottom."""
        for paragraph in page.pdf_paragraph:
            for composition in paragraph.pdf_paragraph_composition:
                if composition.pdf_line:
                    line = composition.pdf_line
                    line.pdf_character.sort(key=self._get_char_sort_key)

    def _get_char_sort_key(self, char: PdfCharacter):
        """Get sort key for character positioning (top to bottom, left to right)."""
        visual_box = char.visual_bbox.box
        pdf_box = char.box

        # Use visual box if IoU with bbox is >= 0.1, otherwise use bbox
        if calculate_iou_for_boxes(visual_box, pdf_box) >= 0.1:
            box = visual_box
        else:
            box = pdf_box

        # Sort by y coordinate first (top to bottom), then x coordinate (left to right)
        # Note: In PDF coordinate system, y increases upward, so we negate y for top-to-bottom sorting
        return (box.x, -box.y)

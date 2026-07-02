# BabelDOC CLI 参数中文说明

本文根据 `uv run babeldoc --help` 和 `babeldoc/main.py` 整理，适用于当前源码版本 `0.6.3`。

## 常用示例

```powershell
uv run babeldoc `
  --files "D:\path\input.pdf" `
  --openai `
  --openai-model "gemini-2.5-flash-lite" `
  --openai-base-url "https://generativelanguage.googleapis.com/v1beta/openai/" `
  --openai-api-key "<API_KEY>" `
  --lang-in en `
  --lang-out zh `
  --watermark-output-mode=no_watermark `
  --use-alternating-pages-dual `
  --no-mono `
```

## 全局参数

| 参数 | 中文名 | 含义 | 默认值/说明 |
|---|---|---|---|
| `-h`, `--help` | 帮助 | 显示命令行帮助并退出。 | 无 |
| `-c CONFIG`, `--config CONFIG` | 配置文件 | 指定 TOML 配置文件路径。命令行参数优先级高于配置文件。 | 无 |
| `--version` | 版本 | 显示 BabelDOC 版本并退出。 | 当前源码为 `0.6.3` |
| `--files FILES` | 输入文件 | 指定要翻译的 PDF 文件路径。可重复传入多次以处理多个文件。 | 必填，除非只执行 warmup/离线资源操作 |
| `--debug` | 调试日志 | 启用 debug 日志，并输出更多中间信息。 | `False` |
| `--warmup` | 预热资源 | 只下载并校验必需资源，然后退出，不执行翻译。 | `False` |
| `--rpc-doclayout RPC_DOCLAYOUT` | 版面分析 RPC 1 | 指定文档版面分析 RPC 服务地址。 | 无 |
| `--rpc-doclayout2 RPC_DOCLAYOUT2` | 版面分析 RPC 2 | 指定第二个文档版面分析 RPC 服务地址。 | 无 |
| `--rpc-doclayout3 RPC_DOCLAYOUT3` | 版面分析 RPC 3 | 指定第三个文档版面分析 RPC 服务地址。 | 无 |
| `--rpc-doclayout4 RPC_DOCLAYOUT4` | 版面分析 RPC 4 | 指定第四个文档版面分析 RPC 服务地址。 | 无 |
| `--rpc-doclayout5 RPC_DOCLAYOUT5` | 版面分析 RPC 5 | 指定第五个文档版面分析 RPC 服务地址。 | 无 |
| `--rpc-doclayout6 RPC_DOCLAYOUT6` | 版面分析 RPC 6 | 指定第六个文档版面分析 RPC 服务地址。 | 无 |
| `--rpc-doclayout7 RPC_DOCLAYOUT7` | 版面分析 RPC 7 | 指定第七个文档版面分析 RPC 服务地址。 | 无 |
| `--generate-offline-assets GENERATE_OFFLINE_ASSETS` | 生成离线资源包 | 在指定目录生成离线资源包，包含运行所需模型、字体等资源。 | 无 |
| `--restore-offline-assets RESTORE_OFFLINE_ASSETS` | 恢复离线资源包 | 从指定文件或目录恢复离线资源包。 | 无 |
| `--working-dir WORKING_DIR` | 工作目录 | 指定翻译过程中的工作目录。 | 未指定时使用临时目录 |
| `--metadata-extra-data METADATA_EXTRA_DATA` | 元数据扩展 | 写入输出 PDF 元数据的额外信息。 | 无 |
| `--enable-process-pool` | 启用进程池 | 调试用途参数。 | `False` |

## 翻译参数

| 参数 | 中文名 | 含义 | 默认值/说明 |
|---|---|---|---|
| `--pages PAGES`, `-p PAGES` | 页码范围 | 指定要翻译的页码。支持 `1,2,1-,-3,3-5` 这类格式。 | 未指定时翻译全部页面 |
| `--min-text-length MIN_TEXT_LENGTH` | 最小翻译长度 | 小于该长度的文本片段不翻译。 | `5` |
| `--lang-in LANG_IN`, `-li LANG_IN` | 源语言 | 输入文档语言代码。 | `en` |
| `--lang-out LANG_OUT`, `-lo LANG_OUT` | 目标语言 | 输出译文语言代码。 | `zh` |
| `--output OUTPUT`, `-o OUTPUT` | 输出目录 | 指定翻译结果输出目录。 | 未指定时输出到输入文件所在目录 |
| `--qps QPS`, `-q QPS` | 请求速率 | 翻译服务 QPS 限制。 | `4` |
| `--ignore-cache` | 忽略缓存 | 忽略已有翻译缓存，强制重新翻译。 | `False` |
| `--no-dual` | 不输出双语 PDF | 禁止生成双语对照 PDF。 | 默认会输出双语 PDF |
| `--no-mono` | 不输出单语 PDF | 禁止生成纯译文 PDF。 | 默认会输出单语 PDF |
| `--formular-font-pattern FORMULAR_FONT_PATTERN` | 公式字体匹配 | 用字体名正则/模式识别公式文本。 | 无 |
| `--formular-char-pattern FORMULAR_CHAR_PATTERN` | 公式字符匹配 | 用字符正则/模式识别公式文本。 | 无 |
| `--split-short-lines` | 拆分短行 | 强制把短行拆成不同段落，可能影响排版。 | `False` |
| `--short-line-split-factor SHORT_LINE_SPLIT_FACTOR` | 短行拆分系数 | 短行判断阈值为当前页行长中位数乘以该系数。 | `0.8` |
| `--skip-clean` | 跳过 PDF 清理 | 跳过 PDF 清理步骤，可能提高兼容性但增大文件。 | `False` |
| `--dual-translate-first` | 双语 PDF 译文优先 | 双语模式下把译文页放在原文页前面。 | `False` |
| `--disable-rich-text-translate` | 禁用富文本翻译 | 使用更简单的文本翻译输入，可能改善某些 PDF 兼容性。 | `False` |
| `--enhance-compatibility` | 增强兼容性 | 等价于启用 `--skip-clean`、`--dual-translate-first`、`--disable-rich-text-translate`。 | `False` |
| `--use-alternating-pages-dual` | 双语交替页 | 双语 PDF 中原文页和译文页交替排列，而不是同页并排。 | `False` |
| `--watermark-output-mode {watermarked,no_watermark,both}` | 水印输出模式 | 控制是否生成带水印/无水印 PDF。 | `watermarked` |
| `--max-pages-per-part MAX_PAGES_PER_PART` | 分片页数上限 | 大文档按指定页数分片翻译，最后自动合并。 | 未指定时不分片 |
| `--no-watermark` | 不加水印 | 已废弃参数，请改用 `--watermark-output-mode=no_watermark`。 | 废弃 |
| `--report-interval REPORT_INTERVAL` | 进度刷新间隔 | 进度报告刷新间隔，单位秒。 | `0.1` |
| `--translate-table-text` | 翻译表格文本 | 尝试翻译表格中的文字。 | 实验功能，默认 `False` |
| `--show-char-box` | 显示字符框 | 显示字符边界框。 | 调试用途，默认 `False` |
| `--skip-scanned-detection` | 跳过扫描件检测 | 跳过扫描 PDF 检测，可加快非扫描 PDF 处理。 | `False` |
| `--ocr-workaround` | OCR 绕过处理 | 添加文本遮盖背景，适合部分扫描 PDF。假设背景白、文字黑。 | 实验功能，默认 `False` |
| `--custom-system-prompt CUSTOM_SYSTEM_PROMPT` | 自定义系统提示词 | 给翻译模型追加/替换自定义系统提示词。 | 无 |
| `--add-formula-placehold-hint` | 添加公式占位提示 | 在翻译提示中加入公式占位符说明。 | 不推荐，默认 `False` |
| `--disable-same-text-fallback` | 禁用同文回退 | 当模型输出与输入相同文本时，不启用 fallback 翻译逻辑。 | `False` |
| `--glossary-files GLOSSARY_FILES` | 术语表文件 | 逗号分隔的 CSV 术语表路径。CSV 通常包含 `source`、`target`、可选 `tgt_lng`。 | 无 |
| `--pool-max-workers POOL_MAX_WORKERS` | 通用工作线程数 | 内部任务处理池最大线程数。 | 未指定时默认使用 `qps` |
| `--term-pool-max-workers TERM_POOL_MAX_WORKERS` | 术语提取线程数 | 自动术语提取专用线程池大小。 | 未指定时使用 `pool-max-workers`，再退回 `qps` |
| `--no-auto-extract-glossary` | 禁用自动术语提取 | 关闭自动术语提取。配置文件中对应 `auto_extract_glossary = false`。 | 默认启用自动术语提取 |
| `--auto-enable-ocr-workaround` | 自动启用 OCR 绕过 | 检测到重度扫描 PDF 时，自动尝试 OCR workaround 并跳过后续扫描检测。 | `False` |
| `--primary-font-family {serif,sans-serif,script}` | 主要字体族 | 指定译文字体族：衬线、无衬线、手写/斜体。 | 未指定时按原文自动选择 |
| `--only-include-translated-page` | 只保留翻译页 | 输出 PDF 只包含被翻译的页面。 | 仅在指定 `--pages` 时有效，默认 `False` |
| `--save-auto-extracted-glossary` | 保存自动术语表 | 将自动提取的术语保存为输出目录中的 CSV 文件。 | `False` |
| `--disable-graphic-element-process` | 禁用图形元素处理 | 不处理图形元素。 | `False` |
| `--no-merge-alternating-line-numbers` | 禁用交替行号合并 | 禁用默认开启的交替行号布局合并后处理。 | 默认启用合并 |
| `--skip-translation` | 跳过翻译 | 跳过翻译步骤。 | `False` |
| `--skip-form-render` | 跳过表单渲染 | 输出时不渲染 PDF 表单。 | `False` |
| `--skip-curve-render` | 跳过曲线渲染 | 输出时不渲染 PDF 曲线元素。 | `False` |
| `--only-parse-generate-pdf` | 仅解析并生成 PDF | 只解析 PDF 并重新生成，不做版面分析、段落查找、样式处理和翻译。 | `False` |
| `--remove-non-formula-lines` | 删除非公式线条 | 从段落区域移除非公式装饰线，同时保护图表区域线条。 | `False` |
| `--non-formula-line-iou-threshold NON_FORMULA_LINE_IOU_THRESHOLD` | 非公式线重叠阈值 | 删除非公式线条时，用于判断段落重叠的 IoU 阈值；越高越保守。 | `0.9` |
| `--figure-table-protection-threshold FIGURE_TABLE_PROTECTION_THRESHOLD` | 图表保护阈值 | 删除线条时保护图表区域的 IoU 阈值；越高保护越强。 | `0.9` |
| `--skip-formula-offset-calculation` | 跳过公式偏移计算 | 不执行公式偏移计算。 | `False` |
| `--openai` | 使用 OpenAI 兼容翻译器 | 启用 OpenAI-compatible LLM 翻译接口。Gemini、DeepSeek、OpenRouter 等兼容接口也通过它接入。 | 翻译时必须选择 |

## OpenAI 兼容接口参数

| 参数 | 中文名 | 含义 | 默认值/说明 |
|---|---|---|---|
| `--openai-model OPENAI_MODEL` | 模型名 | 指定 OpenAI-compatible 接口的模型名称。 | `gpt-4o-mini` |
| `--openai-base-url OPENAI_BASE_URL` | 接口地址 | OpenAI-compatible API Base URL。 | 无 |
| `--openai-api-key OPENAI_API_KEY`, `-k OPENAI_API_KEY` | API Key | OpenAI-compatible API Key。 | 使用 `--openai` 时必填 |
| `--openai-term-extraction-model OPENAI_TERM_EXTRACTION_MODEL` | 术语提取模型 | 自动术语提取使用的模型。 | 未指定时使用 `--openai-model` |
| `--openai-term-extraction-base-url OPENAI_TERM_EXTRACTION_BASE_URL` | 术语提取接口地址 | 自动术语提取使用的 API Base URL。 | 未指定时使用 `--openai-base-url` |
| `--openai-term-extraction-api-key OPENAI_TERM_EXTRACTION_API_KEY` | 术语提取 API Key | 自动术语提取使用的 API Key。 | 未指定时使用 `--openai-api-key` |
| `--enable-json-mode-if-requested` | 按需启用 JSON 模式 | 当内部请求需要 JSON 输出时，向 OpenAI-compatible 接口启用 JSON mode。 | `False` |
| `--send-dashscope-header` | 发送 DashScope 头 | 给阿里 DashScope 发送关闭输入/输出检查的请求头。 | `False` |
| `--no-send-temperature` | 不发送 temperature | 请求模型时不传 `temperature` 字段。 | 默认会发送 temperature |
| `--openai-reasoning OPENAI_REASONING` | 推理参数 | 在 OpenAI 请求体中发送 `reasoning` 字段。 | 未指定时不发送 |
| `--openai-term-extraction-reasoning OPENAI_TERM_EXTRACTION_REASONING` | 术语提取推理参数 | 自动术语提取请求中发送 `reasoning` 字段。 | 未指定时不发送 |

## Gemini 接入建议

| 参数 | Gemini 示例值 | 说明 |
|---|---|---|
| `--openai` | 启用 | BabelDOC 当前只支持 OpenAI-compatible 翻译器。 |
| `--openai-model` | `gemini-2.5-flash` | 可按你的额度和质量需求替换为其他 Gemini 模型。 |
| `--openai-base-url` | `https://generativelanguage.googleapis.com/v1beta/openai/` | Gemini 的 OpenAI-compatible API 地址。 |
| `--openai-api-key` | `<Gemini API Key>` | Google AI Studio / Gemini API 的 key。 |
| `--no-send-temperature` | 可选 | 如果某个兼容接口不接受 `temperature`，可加这个参数。 |

## 配置文件说明

所有以 `--` 开头的参数通常也可以写入 TOML 配置文件，并通过 `-c` / `--config` 指定。配置文件需要使用 `[babeldoc]` 段，例如：

```toml
[babeldoc]
files = "D:\\path\\input.pdf"
openai = true
openai-model = "gemini-2.5-flash"
openai-base-url = "https://generativelanguage.googleapis.com/v1beta/openai/"
openai-api-key = "your-api-key"
lang-in = "en"
lang-out = "zh"
qps = 4
output = "D:\\path\\output"
```

优先级通常是：命令行参数 > 配置文件 > 默认值。

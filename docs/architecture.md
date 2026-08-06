# 项目架构

项目按三个阶段拆分；当前实现第一、第二阶段，第三阶段暂缓。

## 1. 文档解析：`file/`

文档解析层负责把 PDF 原生文本、MinerU 结构化结果和可选 OCR 结果按页合并，过滤重复
页眉页脚，并生成统一输出。

```text
PDF + 可选 MinerU 导出
  -> file.pdf_backend（原生文本与 MinerU 坐标区域渲染）
  -> file.text_quality（中文字符与乱码质量检测）
  -> file.hybrid（MinerU / 原生文本 / OCR 页级路由）
  -> file.ocr（低质量页面 OCR 回退）
  -> file.header_footer（重复页眉页脚过滤）
  -> file.citations（参考文献提取）
  -> file.output（结果落盘）
```

目标目录结构：

```text
result/
├── jsonl/<文章名称>/
│   ├── content.jsonl
│   ├── filtered_headers_footers.jsonl
│   └── manifest.json
├── figures/<文章名称>/
│   ├── image_*.png|jpg
│   └── table_*.md|png|jpg
└── citations/<文章名称>/
    └── citations.jsonl
```

`content.jsonl` 按阅读顺序保留中文、英文、数字、标点和公式。正文中的图片、表格块通过
`asset_paths` 与 `figures/` 下的文件关联。表格至少保留结构化 Markdown；有表格截图时同时保存。
过滤掉的页眉页脚另存为审计文件，不进入正文。

当前适配器接受 MinerU `content_list.json`、包装后的 `content_list_json`，以及可选的
`middle_json`；读取 `*_content_list.json` 时会自动加载同目录的 `*_middle.json`。混合解析中的
图片必须具有 MinerU `bbox`；若坐标缺失会立即报导出不完整，
不再按 PDF 内嵌图片顺序猜测匹配。

混合解析按页选择文本来源：优先保留中文质量合格的 MinerU 结果；若 PDF 原生文本包含更多
有效中文，则用原生文本替换该页普通文本块，同时保留 MinerU 的公式、图片和表格信息；两者
均不合格时才渲染页面并调用 OCR。公式继续使用 LaTeX，表格统一转换为 Markdown。每页选择结果、
候选质量和仍需人工处理的页码写入 `manifest.json`。

原生文本进入输出前会先判断正文栏数。`Abstract/摘要` 和 `Keywords/关键词` 用于定位正文
起点，但仍保留在输出中，不参与单双栏证据统计。单栏正文按页面从上到下排序；双栏正文按
每页左栏从上到下、再右栏从上到下排序，之后进入下一页。页首标题、摘要及页内跨栏表格等
全宽块按纵向位置插入。检测结果与证据页写入 `manifest.json` 的 `layout` 字段。

图片结构、页码、范围、图注和图脚均以 MinerU 为准。若提供 `middle_json`，程序会合并
`image_body/image_caption/image_footnote`（以及对应 chart 类型）的坐标；否则使用
`content_list` 的 0–1000 `bbox`。校正坐标后从原 PDF 以至少 450 DPI 渲染，不再额外提取或
补充 `pdf_image_*`。MinerU 资源缺失但表格块中存在 `bbox` 时，仍会生成表格截图。
图片内文字的 OCR 不能替代原图；使用 `--ocr-figures` 时，识别结果以 `*.ocr.json` sidecar
保存。MinerU 的 page、0–1 和 0–1000 坐标会在裁剪前统一换算为 PDF 点坐标。

表格优先按 PDF 原生版面识别以“表 1 / Table 1”等表题开头的块，并以同栏下方“注：/
Note:”段落的末尾作为结束边界。边界内文字通过文本坐标重建为 Markdown，同时将完整区域
渲染为 450 DPI PNG；多行注释会连续纳入。只有原生边界识别结果不足以覆盖 MinerU 表格时，
才保留 MinerU 的结构化表格作为回退。

PDF 中小字号且基线下沉的公式数字按下标处理，并转换为 Unicode 下标字符，例如
`CHA₂DS₂-VASc`、`H₂O`。这一规则同时用于正文原生文本和 Markdown 表格；术语若恰好在行末
连字符处换行，会在写入 `content.jsonl` 前重新合并，避免产生独立的 `DS`、`2` 等碎片块。

运行示例：

```bash
hospital-file normalize-mineru first_ten --result-root result
```

推荐使用混合解析：

```bash
python -m file.cli parse-hybrid first_ten \
  --mineru-export-dir first_ten \
  --result-root result
```

需要 OCR 回退时安装 Tesseract 与简体中文语言包，然后增加：

```bash
--ocr-engine tesseract --ocr-language chi_sim+eng --require-complete-text
```

若还要识别图片内部文字，增加 `--ocr-figures`。原始图片或裁剪图仍会保留。

## 2. 质量评估：`src/hospital_eval/`

质量评估层不负责调用解析器，只消费第一阶段的标准化结果和人工评估集。现有指标包括：

- 字符编辑相似度；
- 答案 Exact Match 与 Token-F1；
- 检索 Recall@K；
- 失败类型及严重度数据模型。

后续解析质量指标（字符、公式、图片、表格、参考文献）继续在该目录实现。

## 3. 长尾增强

图像增强、复杂表格修复、标题层级恢复等长尾增强暂不实现。后续应作为独立阶段消费质量
评估报告，避免与基础解析和评估代码耦合。

## 测试

所有阶段的测试统一放在 `tests/`，并保持不依赖 GPU 或在线模型。

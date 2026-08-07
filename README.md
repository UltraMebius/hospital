# 研究方向

面向循证医疗知识库的文档解析质量评估与长尾增强
聚焦循证 AI 产品上游的文档解析环节(指南、共识、文献、药品说明书等 PDF/书籍 → 结构化 chunk)。不同于通用解析以孤立解析准确率为目标,本方向以下游医疗 RAG 的检索与回答质量为最终评价标尺,在充分利用解析工具自身快速迭代(如 MinerU 2.5→3.1 的版本红利)的基础上,研究升级仍无法覆盖的长尾失败模式的系统性评估、归因与针对性增强,形成可跨工具版本复用的方法论。

# 项目任务描述:

第一阶段(基线对齐与评估体系,~2 周):梳理现有解析链路;将基线从 MinerU 2.5-VLM 升级到 3.1 + 新版模型,并系统对比 VLM 与 pipeline 后端在医学文档上的表现与选型;构建覆盖典型医学文档类型(电子版指南、低质量扫描件、含复杂表格的药典/说明书)的解析质量评估集;设计双层指标——解析层(版面/表格/标题结构/文本准确率)与 RAG 层(由解析结果产出的 chunk 在检索召回与回答正确率上的表现)。本阶段同时量化"版本升级解决了哪些问题、剩余哪些长尾",为后续聚焦提供依据。
第二阶段(失败归因,~2 周):在评估集上跑升级后基线,对照人工标注与下游 RAG 表现,建立解析失败 taxonomy(扫描质量、复杂表格结构错乱、层级结构丢失、文本/符号后处理错误等),定位升级后仍高频、对循证场景高影响的失败模式,产出可量化的失败分布。
第三阶段(长尾增强,~2 周):选取 1–2 个升级无法覆盖、对循证准确率影响最大的失败模式,实现并验证改进方案,给出改进前后在解析层与 RAG 层的对比增益。建议优先方向:低质量扫描件的图像层增强、复杂医学表格的保结构解析。
六周末阶段汇报交付:评估集 + 双层指标体系 + 版本升级收益量化 + 失败归因报告 + 1–2 个长尾失败模式的改进原型与效果。

## 快速开始

项目采用 Python 3.10+。代码按“文档解析 → 质量评估 → 长尾增强”分层；当前先实现前两层，
长尾增强暂缓。开发环境安装：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
make check
```

推荐使用 PDF、MinerU 和 OCR 的混合解析。程序会自动按 PDF 文件名匹配对应的
`*_content_list.json` 或 `.jsonl`；使用官方 content-list 文件时还会自动读取同目录的
`*_middle.json`，优先恢复中文原生文本，并保留 MinerU 的 LaTeX 公式；
表格统一输出为 Markdown：

```bash
python -m file.cli parse-hybrid first_ten --result-root result
```

程序会从摘要和关键词之后的正文块判断单双栏。双栏页面按“左栏完整读取 → 右栏完整读取 →
下一页”的顺序写入；具体判断可在每篇文章 `manifest.json` 的 `layout` 字段查看。

如果已安装 Tesseract 及 `chi_sim` 中文语言包，可为中文仍不完整的页面开启 OCR：

```bash
python -m file.cli parse-hybrid first_ten --result-root result \
  --ocr-engine tesseract --ocr-language chi_sim+eng \
  --ocr-figures --require-complete-text
```

仅将现有 MinerU 导出归一化到 `result/`：

```bash
python -m file.cli normalize-mineru first_ten --result-root result
```

输出分别位于 `result/jsonl/<文章名称>`、`result/figures/<文章名称>` 和
`result/citations/<文章名称>`。正文结果保留中英文、数字和公式，重复页眉页脚会被过滤并
另存审计记录。

校验人工评估集及计算 RAG 指标：

```bash
hospital-eval validate-dataset data/processed/evaluation_cases.jsonl
hospital-eval score data/processed/evaluation_cases.jsonl predictions.jsonl
```

MinerU 的命令行、后端、超时时间和归一化参数通过 `configs/baseline.example.json`
记录，避免将 GPU/模型环境与评估代码耦合。详细数据契约与扩展方式见
[`docs/architecture.md`](docs/architecture.md)。

## 需解决的关键技术问题：

解析质量的下游导向度量:定义并自动化评估"对 RAG 有用的解析质量",建立解析层指标与下游检索/回答质量之间的可量化关联,而非仅看孤立解析准确率。
低质量扫描件的鲁棒识别:DPI<150、模糊、噪声、褶皱场景下识别率骤降(实测可低至 67%)。OCR 模型升级无法解决图像质量本身的退化,需研究图像层预处理/去噪/超分与 OCR 选型的组合策略,在准确率与吞吐间取得平衡。
复杂医学表格的保结构解析:嵌套表格、跨页合并、复杂对齐(剂量表、诊断标准表、推荐等级表)是循证回答最依赖的 chunk 类型。新版虽增强了表格能力,但长尾复杂表格仍易结构错乱;需研究保结构抽取与"保结构地转 chunk"的方法,避免表格语义在切块时被破坏。
文档层级结构恢复与后端选型:多级标题/章节树的还原,服务于层级化/语义化切块(对应 RAG 失败 taxonomy 中的 C1)。需结合 VLM 与 pipeline 各自特性,研究版面信号 + 文本信号联合推断标题级别的可靠方案。
文本与符号后处理(附属):英文词边界粘连/断裂修复、公式标识符规整等。工程性强、研究深度低,作为附属任务;复杂 LaTeX 公式对医疗场景价值有限,建议剔除。

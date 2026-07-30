# 基础架构

## 设计目标

架构以“解析结果是否提升医疗 RAG”为主线，将具体解析工具与评估逻辑解耦，便于在
MinerU 版本和 VLM/pipeline 后端变化后复用数据集、归因方法及指标。

## 数据流

```text
PDF / 扫描件
  -> Parser adapter (MinerU VLM / pipeline)
  -> 标准化 chunks.jsonl
  -> 解析层指标（文本、版面、表格、标题）
  -> 检索与回答实验
  -> RAG 层指标（Recall@K、EM、Token-F1）
  -> failure taxonomy 与增强实验
```

## 目录

- `configs/`：可追溯的实验配置；每次实验复制示例配置并记录模型与工具版本。
- `data/raw/`：原始医学文档（不提交 Git）。
- `data/interim/`：各解析后端的原始输出（不提交 Git）。
- `data/processed/`：统一 chunk 和人工标注（不提交 Git）。
- `data/reports/`：指标与失败分布报告（不提交 Git）。
- `src/hospital_eval/parsers/`：解析工具适配器。
- `src/hospital_eval/evaluation.py`：解析/RAG 指标实现。
- `src/hospital_eval/models.py`：文档、chunk、评估问题及失败类型的数据契约。
- `tests/`：不依赖模型或 GPU 的确定性单元测试。

## 标准交换格式

解析器应在每个文档输出目录生成 `chunks.jsonl`。每行字段如下：

```json
{"id":"guide-001:0","text":"推荐意见……","page":1,"heading_path":["治疗","用药"],"is_table":false,"metadata":{}}
```

评估集同样使用 JSONL，每行包含 `id`、`question`、`expected_answer`、
`relevant_chunk_ids`，可选 `document_id`。RAG 预测文件每行包含 `id`、`answer` 和
按相关性排序的 `ranked_chunk_ids`。

## 扩展点

1. 实现 `Parser` 协议即可接入其他 MinerU 版本或 OCR 工具。
2. 图像增强应作为解析器前的可组合步骤，同时保存增强参数和原图关联。
3. 表格应保持为单一语义 chunk，并在 `metadata` 保存 HTML/单元格关系。
4. 新失败类型先加入 `FailureType`，再由标注规范定义严重度和边界案例。


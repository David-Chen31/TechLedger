# 冻结评测集格式

`python -m techledger.evaluation path/to/frozen.json --mode bm25 --output report.json` 在当前数据库的已审核来源上重放检索。`--mode` 可选 `bm25`、`vector`、`hybrid`；其中 `vector` 是本地字符 n-gram TF-IDF 余弦向量基线，不是语义嵌入模型。每条用例包含唯一 `id`、`question`、人工核对的 `expected_source_urls`，可选 `expected_terms`。格式示例：

```json
{"version":1,"cases":[{"id":"fact-001","question":"durable execution","expected_source_urls":["https://docs.langchain.com/oss/python/langgraph/overview"],"expected_terms":["durable execution"]}]}
```

报告保留逐例命中、来源召回、术语召回与引用完整性。`null` 表示没有足够样本计算。此脚本只评测检索，不代表事实正确率、决策质量或人工收益。正式 20 条事实题和 10 条选型题仍需人工核查、冻结快照后才能发布成绩。

种子集 `evaluation/seed-v0.1.json` 包含 6 条直接事实检索题；`seed-v0.2.json` 加入改写问法与无关负例。两版已在本地审核索引后生成 `frozen-*.json`，绑定当时来源 SHA-256。后续使用 `--mode bm25/vector/hybrid` 分别重放；只要来源当前哈希或审核状态变化，评测会拒绝运行。实测结果与失败说明见[评测结果](evaluation-results-v0.2.md)。种子集规模不足以作为正式产品效果结论。

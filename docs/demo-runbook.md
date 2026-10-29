# TechLedger 演示脚本（Python Agent 编排选型）

目标时长约 5 分钟。演示应说明当前是可审查原型，不把模拟模型摘要或小样本检索分数称为选型质量结论。本脚本可直接用于录屏，逐步显示浏览器、终端和报告。

有界补检索的最新演示和失败记录见[演示记录 v0.1](bounded-repair-demo-v0.1.md)。

## 准备

1. `docker compose up -d --build --wait`，打开 `http://localhost:3100`。
2. 使用当前本地数据时，确认 [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview) 与 [CrewAI introduction](https://docs.crewai.com/en/introduction) 已审核并索引；新的安装环境则先登记、同步、审核来源用途并重建索引。系统不会自动批准来源。审核依据见[来源审核记录](source-review-v0.1.md)。
3. 确认当前来源快照与 `evaluation/research-holdout-frozen-v0.1.json` 中的哈希一致；若不同，旧评测必须拒绝重放，不能悄悄换来源后沿用原数字。不要将本地抓取正文提交到仓库。

## 展示

1. 在“证据检索”依次搜索 `durable execution` 和 `event-driven workflows`，切换 BM25、字符向量和融合模式；打开固定快照引用。
2. 在“技术调研”运行两个问题：
   - `在需要持久化执行和人工审查的 Python Agent 服务中，应如何比较 LangGraph 与 CrewAI？`；硬约束：`必须记录中断恢复机制和人工审核依据`。
   - `在需要多个角色协作且工作流包含条件分支的服务中，应如何比较 CrewAI 与 LangGraph？`；硬约束：`必须说明状态管理与分支控制的证据及未知项`。
3. 查看运行阶段、证据原文、未知项、模型模式与 Token 用量。历史三次真实 DeepSeek Flash 调用及逐张审核记录见[模型审核记录](model-review-v0.1.md)；录屏不必再产生付费调用。若当场演示新运行，先确认模型配置并说明费用；模拟模式必须明确标示。证据不足则退回。
4. 打开决策库，展示两张由开发代理逐字核查、修订后批准的本地卡片及一张退回草稿的操作历史。准确说明这不是独立用户审核。
5. 打开[冻结对照报告](research-retrieval-comparison-v0.1.md)，展示 6 题的输入证据覆盖、漏检题和字符数。可用 `evaluation/research-holdout-frozen-v0.1.json` 调用 `POST /api/evaluation/research-retrieval` 重放；来源快照变化后，旧冻结集会拒绝重放。

## 来源更新演示

真实官网何时更新不可控。稳定的“来源变化→决策需复核→换证据再批准”演示由 `backend/tests/test_card_lifecycle.py` 的受控用例提供；运行 `python -m pytest tests/test_card_lifecycle.py -q`，展示测试中模拟的旧/新快照和状态断言。不要将受控样例称为真实官网发生的更新。

## 录屏检查

录屏应包含来源审核、可打开引用、两张决策卡、一次退回、一条受控更新测试、逐例评测报告与两处漏检。每个数字应能回到本地报告或测试输出。不要把本地密钥、`.env`、`compose.override.yaml` 或 Docker 环境变量页面录入画面。

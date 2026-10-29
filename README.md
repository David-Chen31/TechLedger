# TechLedger（技术决策账本）

让研发团队的技术选型**有证据、能复核、可复用**。

当前状态：**可运行的纵向原型，尚未达到完整 PRD 验收**。已实现来源登记、异步同步、不可变快照、人工审核后的本地文本索引、BM25/字符向量/融合检索和可核查片段；另有后台调研、决策卡人工审查/修订/归档、来源变更复核和持久化运行事件。字符向量是本地 n-gram TF-IDF 基线；种子集评测显示它并未改善负例拒答，因此调研默认仍用 BM25。语义嵌入与正式评测集仍待开发，详见[剩余工作](docs/remaining-work.md)。

## 本地启动

启动 Docker Desktop 后，在本目录执行 `docker compose up --build`。浏览器打开 `http://localhost:3100`；API 健康检查为 `http://localhost:8000/health`，接口文档为 `http://localhost:8000/docs`。Compose 会启动 PostgreSQL、API、单独的来源同步 worker 和网页。

来源默认仅保存标题、内容 SHA-256、类型、字节数及同步时间。**记录来源使用审核依据并允许本地索引后**，再次同步才保存提取文本与片段；撤销允许会清除本地索引。检索结果包含快照哈希和字符范围，可以打开片段核对。调研无模型密钥时使用模拟模式；如需真实 DeepSeek 模型，在 `.env` 设置 `MODEL_BASE_URL=https://api.deepseek.com`、`MODEL_NAME=deepseek-flash`，将密钥单独写入 `.deepseek_api_key`，复制 `compose.deepseek.example.yaml` 为 `compose.override.yaml`。后两个文件均被 Git 忽略，密钥只挂载给 worker。可登记的地址被限制在首批官方文档和发布页范围内。真实来源抓取需要本机能访问相应网站；自动测试使用固定模拟内容，不依赖外网。

后端测试：进入 `backend`，安装 `requirements-dev.txt`，执行 `python -m pytest tests -q`。前端验证：进入 `frontend`，执行 `npm ci` 和 `npm run build`。容器验证执行 `docker compose config --quiet` 后，再进行完整启动与网页操作。实际已运行的结果应以本次开发记录为准。

浏览器端到端测试：先启动 Compose，再在 `frontend` 执行 `npm run test:e2e`。本机默认使用已安装的 Chrome；CI 使用 Playwright Chromium。五分钟演示步骤见[演示脚本](docs/demo-runbook.md)；10 条开发种子题位于 `evaluation/seed-v0.3.json`，另有[六题冻结对照](docs/research-retrieval-comparison-v0.1.md)及逐题原始报告。两组结果都只适用于当前两份来源和有限问题，不作为正式产品效果结论。

本地演示现有两张由开发代理逐字核查并修订的决策卡；三次真实 DeepSeek 调用、Token 与审核决定见[模型审核记录](docs/model-review-v0.1.md)。来源使用依据见[来源审核记录](docs/source-review-v0.1.md)。这些记录不等同于独立用户研究。

面试介绍与证据入口见[项目展示提纲](docs/portfolio-brief.md)。

当前有界证据补检索会记录每次工具查询、缺失能力、证据字符数和停止原因；[演示及失败记录](docs/bounded-repair-demo-v0.1.md)显示新题 4 题仅 1 题覆盖目标片段。词面覆盖不是事实核验，仍需改进语义召回。

## 产品要解决什么

面对具体技术选型问题，TechLedger 从批准的官方资料中整理证据，生成可审查的决策卡。用户确认后，决策进入知识库；来源更新时，系统提醒复核受影响的结论。首个候选领域是 Python Agent 编排框架选型，具体来源和版本将在开发前冻结。

TechLedger 与另一个项目 DevFlow-Agent 分工明确：DevFlow 聚焦公开 Issue 的复现、补丁和测试；TechLedger 聚焦技术资料、决策依据与知识更新。

## 准备文档

| 文档 | 内容 |
|---|---|
| [PRD.md](PRD.md) | 用户、MVP 范围、流程、异常、非功能需求与验收标准 |
| [产品定位与用户研究](docs/01-product-brief.md) | 场景、假设、反证和访谈问题 |
| [来源与证据规范](docs/02-source-and-evidence.md) | 来源许可、快照、引用、冲突和失效状态 |
| [架构与接口准备](docs/03-architecture.md) | 组件、数据对象、状态机、REST/SSE 与取舍 |
| [评测计划](docs/04-evaluation-plan.md) | 数据集、基线、指标、人工审查和结果发布 |
| [开发计划](docs/05-development-plan.md) | 阶段门槛、测试重点和开工检查表 |
| [旧版 PRD](PRD.v0.2.archive.md) | 原 Issue 定位方向，已被 DevFlow-Agent 的范围覆盖，保留对照 |

## 后续验证

正式评测需人工冻结来源和题集；检索评测脚本的输入格式见[评测集格式](docs/evaluation-dataset-format.md)。当前运行结果仅证明基本流程可用，不代表调研质量已经达标。

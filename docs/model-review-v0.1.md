# 真实模型调用与代理人工审核记录

日期：2026-10-28。模型：`deepseek-flash`，关闭思考模式；每次最多 4 条、每条最多 220 字符的检索证据，输出上限 256 Token。密钥只放在本地忽略文件 `.deepseek_api_key`，由 worker 的 Compose secret 读取；仓库不保存密钥。

| 运行 ID 前缀 | 输入 / 输出 / 总 Token | 审核结果 | 主要发现 |
|---|---:|---|---|
| `9676d104` | 661 / 102 / 763 | 退回 | 旧 HTML 解析器索引导航，模型无法核实关键能力。 |
| `7aed3721` | 494 / 101 / 595 | 修订后批准 | 正文索引已修复，但模型漏读 LangGraph 概览的明确能力；代理逐字核查两条当前来源片段后修订。 |
| `d0138ac3` | 496 / 122 / 618 | 修订后批准 | 模型漏读 CrewAI 状态/分支与 LangGraph 确定性步骤；代理逐字核查三条当前来源片段后修订。 |

共 1,651 个缓存未命中输入 Token、325 个输出 Token，缓存命中为 0。按 [DeepSeek 官方价格表](https://api-docs.deepseek.com/quick_start/pricing/)所列的非高峰 Flash 单价估算，模型费用约 **$0.00044265**；这是依据返回用量的估算，不是账户账单。未调用 DeepSeek 的付费 Search/Fetch API。当前模型名与关闭思考模式的参数依据 [官方 Chat Completions 文档](https://api-docs.deepseek.com/api/create-chat-completion/)。

两张批准卡 ID 为 `574bf765-b79d-4802-8bd0-d33c4d6d8253` 与 `e7dc5e08-2150-4dc9-a937-17b7f4b2b464`。原模型稿、修订内容、引用片段和审核理由均在本地决策卡历史中。审核者是本次开发的 AI 代理，**不等同于独立人类评审或用户研究**。批准只表示所保留的短结论与当前 [LangGraph 概览](https://docs.langchain.com/oss/python/langgraph/overview)、[CrewAI 介绍](https://docs.crewai.com/en/introduction)片段相符；不代表完整技术选型已被验证。

## 发现的工程缺口

模型两次漏读相关片段，说明原先“候选名称检索前两条 + 问题检索补齐”的证据选择策略仍不可靠。当前通过代理人工修订补齐，不把模型原稿当作通过审查的答案。已加入按能力维度与候选来源检索的确定性规划，并用测试验证两候选覆盖；该改进尚未通过新的真实模型调用验证，后续应先在固定题集上测证据覆盖与成本，再决定是否增加调用。

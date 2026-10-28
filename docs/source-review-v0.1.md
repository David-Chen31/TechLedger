# 首批来源使用审核记录

审核时间：2026-10-28；审核者：本次开发的 AI 代理。范围仅限本地演示索引，不将抓取正文或长段摘录打包进公开仓库。

| 来源 | 本地处理 | 核查依据 | 限制 |
|---|---|---|---|
| [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview) | 保存当前快照哈希与本地正文索引，公开报告只含 URL、片段 ID 和哈希 | [LangChain 文档仓库 LICENSE](https://github.com/langchain-ai/docs/blob/main/LICENSE) 显示 MIT 许可 | 未单独核定网站其他服务条款；若公开再分发正文，需要重新核查。 |
| [CrewAI introduction](https://docs.crewai.com/en/introduction) | 同上 | [CrewAI 仓库 LICENSE](https://github.com/crewAIInc/crewAI/blob/main/LICENSE) 显示 MIT 许可，官方仓库包含文档目录 | 同上。 |

两份来源通过应用的白名单与本地索引审核流程，原始抓取正文保存在本机数据库，不进入 `evaluation/report-*.json`。本记录说明本地试验的依据与限制，不是独立法律意见，也不代表用户或第三方审查结论。

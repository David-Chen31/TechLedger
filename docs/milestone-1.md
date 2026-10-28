# G1 开发记录：来源登记与快照闭环

记录时间：2026-10-28｜状态：代码、本地验证与 Docker 容器验证完成

## 本阶段已实现

- FastAPI 来源登记、列表、详情、同步入队、任务查询、快照查询与健康检查。
- 仅允许首批官方文档/发布页 URL；每次跳转重新校验目标；限制类型、下载大小、时间和跳转次数。
- 独立 worker 处理数据库队列；相同内容哈希复用旧快照，变化时创建不可变新快照；失败保留旧快照与错误码。
- 默认只保存标题、SHA-256、类型、大小和时间，不保存未经使用方式审查的来源正文或摘录。
- PostgreSQL/SQLite 兼容的 SQLAlchemy 模型和 Alembic 初始迁移；Next.js 来源登记和快照网页；Docker Compose 定义。
- 初始化本地 Git 仓库；依赖版本固定，前端生成 package-lock.json。

## 实际验证

| 检查 | 结果 |
|---|---|
| `pytest backend/tests -q` | 11 passed，1 条 Starlette TestClient 依赖弃用警告 |
| `npm run build` | Next.js 生产构建与 TypeScript 检查通过 |
| `alembic upgrade head` | 本地 SQLite 迁移成功 |
| `alembic check` | ORM 与迁移无待生成差异 |
| `docker compose config --quiet` | Compose 配置检查通过 |
| 本地 API + worker 烟雾测试 | `/health` 为 ok；官方文档元数据同步任务完成，生成 1 个快照 |
| `docker compose up --build -d` | Docker Desktop daemon 连通；PostgreSQL、API、worker、网页均启动。API 与数据库健康，网页经 `http://localhost:3100` 返回 200 |

测试覆盖白名单拒绝、恶意跳转、过大响应、URL 规范化、重复登记、同步去重、不可变快照、失败保留旧快照和 API 错误。正式评测和产品价值指标尚未运行。

## 已知限制与下一步

本阶段不提供全文索引、检索、调研 Agent 或决策卡。同步只获取页面元数据；来源正文能否索引需完成 `docs/02-source-and-evidence.md` 中的使用方式审查。Docker 容器内已完成公开文档元数据同步并生成快照；浏览器交互仍需用户实测。下一阶段先建立可允许索引的来源快照、结构化切片和引用定位，再在冻结题集上比较关键词与向量检索。

## 面试复盘问题

1. 为什么每次 HTTP 跳转都要重新检查白名单？仅检查用户提交的初始 URL 有什么风险？
2. 为什么来源快照不可原地覆盖？内容哈希相同、同步失败时分别应该怎样处理？
3. 为什么让 API 入队、worker 同步来源，而不在请求线程直接抓取？单 worker 的并发边界是什么？

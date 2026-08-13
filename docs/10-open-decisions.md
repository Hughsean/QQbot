# 待决策清单

这里记录尚未获得足够产品证据的选择。它们不是允许随意实现的空白；进入对应阶段前必须形成 ADR 或更新需求文档。

截至 2026-08-13，MVP 实现所需的产品与技术决策均已关闭。保留本文件用于记录已接受选择、质量门禁和未来重新评估条件；实现中不得自行重新打开已关闭范围。

## OD-01 日程事实源

- 状态：Decided
- 当前决定：不接入任何日历 Provider；Agenda 模块在 PostgreSQL 中维护项目内部权威日程，QQ 负责主动提醒。
- 结果：Microsoft 应用只用于 Outlook 邮件只读能力，不请求 Calendar 权限。

## OD-02 QQ Bot 接入方式

- 状态：Decided for MVP
- 已决定：使用 QQ 开放平台和官方 Python SDK `qq-botpy`，不采用 OneBot、NapCat、Mirai 等非官方协议。
- 已确认：已经创建 QQ Bot 并具备沙箱测试账号；MVP 只处理所有者与 Bot 的 C2C 私聊，并需要主动提醒。
- 交付前检查：确认 QQ 开放平台对主动消息的权限、场景和上线审核状态；权限不足时不得用非官方协议规避。

任何框架对象只能留在 QQ Adapter，不得成为领域模型。

## OD-03 技术栈

- 状态：Decided
- 已决定：Python 3.12、uv、项目内 `.venv`、LangGraph、`.env` 配置注入。
- 兼容记录：Python 3.14.6 可解析和导入依赖，但 `qq-botpy 1.2.1` 创建 Client 时调用 `asyncio.get_event_loop()` 并在 3.14 抛出 `RuntimeError`；2026-08-13 已按预设门禁降级至 Python 3.12，不采用猴子补丁。
- 已接受推荐：FastAPI + Uvicorn、PostgreSQL + pgvector、SQLAlchemy 2 + Alembic、数据库 Outbox/Job Worker；第一版不引入 Redis/Celery。

选择必须满足：成熟 OAuth/Graph SDK、清晰模块封装、可靠 schema 校验、异步任务、架构测试和低成本部署。

## OD-04 数据保留时长

- 状态：Decided
- 内部日程、任务和个人笔记保留到所有者主动删除。
- Outlook 邮件正文、QQ 来源文本及对应 RAG 数据保留 365 天。
- 主动删除的在线来源、chunk 和向量立即停止检索，并在 24 小时内物理删除。
- DeepSeek 完整请求/回答不持久化；调用元数据保留 180 天。
- 审计保留 365 天，应用日志/失败任务保留 30 天，备份滚动保留 30 天。
- 附件、图片和网页在 MVP 中不保存、不索引。
- 旧备份恢复后必须重放删除记录，不能让已删除内容重新进入检索。

## OD-05 AI Provider 与数据策略

- 状态：Decided for MVP
- 已决定：使用 DeepSeek API，并通过 AI Gateway 适配，不让领域层依赖模型名称。
- 默认模型策略：`deepseek-v4-flash` 用于分类和常规提取，`deepseek-v4-pro` 用于低置信度复核和复杂推理；全部可由 `.env` 替换。
- 已决定：不设置月度预算或用量硬上限，但仍记录 token、模型、耗时和调用结果，用于故障诊断和异常用量告警。
- 数据范围：只发送清洗后的当前命令、完成任务所需的最小正文和最多 `RAG_RETRIEVAL_LIMIT` 条带来源片段；禁止凭据、`.env`、原始 HTML、附件和全量邮箱内容。
- 超时与重试：Flash 30 秒、Pro 60 秒，最多重试 2 次；所有工作流仍受总模型调用和步骤上限约束。
- 降级：模型不可用时明确告知暂时无法理解，不创建新日程；既有内部日程和 Reminder Worker 继续运行。

AI Provider 必须位于统一 AI Adapter 后，领域层不得依赖厂商模型名称。

## OD-06 默认排程规则

- 状态：Decided for MVP
- 时区：`Asia/Shanghai`。
- 工作窗口：周一至周五 09:00–18:00，午休 12:00–13:30；周末不自动排程。
- 默认耗时：普通任务和固定事件均为 30 分钟。
- 默认提醒：开始前 15 分钟；用户在单条命令中可覆盖。
- 跨天任务：MVP 不自动拆分，先向用户确认。

所有默认值都必须在 Proposal 中显示为假设，用户可覆盖。

## OD-07 自动化等级

- 状态：Decided for MVP
- 当前决定：所有内部日程写入逐次确认，不启用自动创建；已确认日程产生的到期提醒可以自动发送。
- 重新评估条件：阶段 7 有足够真实使用数据，并且错误创建率达到约定阈值。

## OD-08 用户与发布范围

- 状态：Decided
- 当前决定：仅项目所有者本人使用，不提供多租户、公开注册或受控测试用户。
- 所有者 QQ OpenID 由 `.env` 白名单注入；非所有者请求在进入 Inbox/AI/RAG 前拒绝。

## OD-09 RAG 实现

- 状态：Decided for MVP
- 已决定：Windows 本机 Ollama、`qwen3-embedding:4b`、1024 维、Docker PostgreSQL `pgvector`、cosine/HNSW 和混合检索。
- 已决定：DeepSeek 不生成 embedding；RAG 不是 Agenda 或任务状态的事实源。
- 首批来源：已同步 Outlook 邮件正文、所有者明确转发给 Bot 的 QQ 文本、所有者直接提交的笔记；MVP 不索引附件、图片或网页。
- 数据保留已由 OD-04 关闭。
- 质量门禁：实现阶段先建立去敏固定评估集，再以向量检索为基线，要求混合检索 Recall@10 不低于 0.85；达不到时不得以主观演示替代调优。

## OD-10 生产运行位置与公网入口

- 状态：Decided
- 当前决定：Agent、Worker、Docker PostgreSQL 和 Ollama 运行在 Windows 本机；腾讯云只承担 Caddy HTTPS 与 SSH 中继。
- 公网路径：Caddy → 腾讯云回环 `127.0.0.1:8000` → SSH 反向隧道 → Windows 回环 `127.0.0.1:8000`。
- 已验证本机硬件与 `qwen3-embedding:4b` 的 1024 维输出；默认单并发、30 分钟 keep-alive。
- 可用性代价：Windows 主机或隧道离线时 OAuth/Web 入口不可用；必须配置开机自启、失败重连与外部健康告警。

## 决策记录要求

每个 Open 项关闭时必须记录：

1. 选择及状态。
2. 被否决的主要方案。
3. 选择依据和已知代价。
4. 对现有模块边界、接口和数据迁移的影响。
5. 需要新增或修改的验收测试。

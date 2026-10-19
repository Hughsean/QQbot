# QQ Time Agent 文档索引

本目录是项目需求、架构边界和验收标准的唯一事实来源。代码实现不得绕过这里定义的边界；需求发生变化时，先修改文档和决策记录，再修改代码。

## 项目定义

QQ Time Agent 是一个仅供项目所有者本人使用、以 QQ 为主要交互入口的个人时间管理 Agent。它从用户直接输入、用户转发的 QQ 消息和已授权邮箱中发现未来事件与任务，在项目内部维护权威日程、完成编排，并通过 QQ 主动提醒。

核心闭环：

```text
信息进入 → 规范化 → 理解 Event/Task → 查询内部日程与相关知识
→ Agent 理解与上下文检索 → Calendar System 校验 → Actions 幂等写入 → 到期主动提醒 → 记录结果
```

## 文档地图

| 文档 | 解决的问题 |
|---|---|
| [01-product-requirements.md](01-product-requirements.md) | 做什么、不做什么、如何验收 |
| [02-system-context.md](02-system-context.md) | 系统参与者、信任边界和端到端数据流 |
| [03-domain-model.md](03-domain-model.md) | 核心对象、状态机和领域不变量 |
| [04-module-boundaries.md](04-module-boundaries.md) | 模块职责、数据所有权、依赖规则和禁止事项 |
| [05-email-connectors.md](05-email-connectors.md) | Outlook 首发接入及 Gmail、QQ 邮箱扩展边界 |
| [06-security-and-privacy.md](06-security-and-privacy.md) | 凭据、隐私、提示注入、审计和数据保留 |
| [07-contracts.md](07-contracts.md) | 外部 HTTP 接口及模块间契约 |
| [08-deployment-and-operations.md](08-deployment-and-operations.md) | 域名、Caddy、服务、配置和可观测性 |
| [09-delivery-plan.md](09-delivery-plan.md) | 分阶段交付顺序和每阶段完成定义 |
| [10-open-decisions.md](10-open-decisions.md) | 已关闭决策、质量门禁和未来重新评估条件 |
| [11-technology-stack.md](11-technology-stack.md) | Go 迁移技术栈、QQ SDK、DeepSeek 和版本策略（含原 Python 基线） |
| [12-rag-system.md](12-rag-system.md) | Ollama、Qwen3 Embedding、pgvector 和检索边界 |
| [13-development-guardrails.md](13-development-guardrails.md) | 分层、文件规模、架构测试和阶段质量门禁 |
| [14-development-goal.md](14-development-goal.md) | 新对话 Goal mode 的完整开发结果、约束和完成定义 |
| [15-owner-trial-and-operations.md](15-owner-trial-and-operations.md) | 所有者试用、授权、监控、备份恢复与扩展门槛 |
| [16-final-verification-report.md](16-final-verification-report.md) | MVP 最终验证证据、限制和需批准的生产步骤 |
| [17-local-oauth-migration-report.md](17-local-oauth-migration-report.md) | 本机公共客户端迁移、腾讯云清理与控制台验证证据 |
| [18-qq-mail-imap-verification-report.md](18-qq-mail-imap-verification-report.md) | QQ 邮箱 IMAP 扩展的验证证据与试用步骤 |
| [19-containerization-verification-report.md](19-containerization-verification-report.md) | Python 应用容器化部署的验证证据、事件恢复与剩余风险 |
| [20-agent-context-and-rag-upgrade.md](20-agent-context-and-rag-upgrade.md) | 会话上下文、通用回复、RAG 工具和提醒更新契约 |
| [21-agent-harness-and-calendar-system.md](21-agent-harness-and-calendar-system.md) | Agent loop、日程系统工具边界和自动更新策略 |
| [22-agent-conversation-context-plan.md](22-agent-conversation-context-plan.md) | 持久化统一会话时间线、快照和分层摘要实施计划 |
| [23-agent-conversation-context-todo.md](23-agent-conversation-context-todo.md) | 会话上下文改造完成项与生产门槛 |
| [24-agent-conversation-context-verification-report.md](24-agent-conversation-context-verification-report.md) | 会话上下文改造最终验证证据与生产基线 |
| [25-microsoft-todo-requirements.md](25-microsoft-todo-requirements.md) | Microsoft To Do 仅作日程视图、完成标记及 QQ 提醒门禁的需求与验收 |
| [26-microsoft-todo-module-design.md](26-microsoft-todo-module-design.md) | Task Projection 模块拆分、契约、数据所有权、竞态与实施阶段 |
| [27-microsoft-todo-17b-verification.md](27-microsoft-todo-17b-verification.md) | Microsoft To Do 授权接入、模块骨架和受管列表解析的本地验证证据 |
| [28-microsoft-todo-17c-verification.md](28-microsoft-todo-17c-verification.md) | Agenda 到 Microsoft To Do 单向投影、Outbox 和崩溃恢复的本地验证证据 |
| [29-microsoft-todo-17d-verification.md](29-microsoft-todo-17d-verification.md) | To Do 完成回写、QQ 发送前门禁、租约取消和抑制记录的本地验证证据 |
| [30-qq-ingress-turn-coalescing.md](30-qq-ingress-turn-coalescing.md) | QQ 连续消息合并、同会话串行、信任分段和默认时间策略 |
| [31-qq-ingress-turn-verification.md](31-qq-ingress-turn-verification.md) | QQ 连续消息合并实现、迁移、恢复与本地验证证据 |
| [32-go-migration.md](32-go-migration.md) | 保留全部功能和数据的 Go 分阶段迁移与验收 |
| [33-go-foundation-verification.md](33-go-foundation-verification.md) | Go 基础验证、旧实现分支清理与 HP 停止保留记录 |
| [34-go-account-migration.md](34-go-account-migration.md) | Go 账号、凭据、邮箱授权的本地验证和待完成沙箱门禁 |
| [adr/](adr/) | 已接受的关键架构决策（含 Microsoft To Do 外部投影、迁移链单基线） |

## 决策优先级

发生冲突时按以下顺序处理：

1. 安全与隐私约束。
2. 模块边界与领域不变量。
3. 产品需求和验收条件。
4. 接口契约。
5. 部署与实现细节。

## 术语

| 术语 | 含义 |
|---|---|
| Inbox Item | 进入系统的一份原始信息信封，不代表可执行命令 |
| Event | 有确定发生时间的事件 |
| Task | 有目标和约束、但需要安排执行时间的任务 |
| Proposal | 尚未执行的安排建议 |
| Agenda Entry | 项目内部保存的权威日程条目 |
| Task Projection | Agenda 到外部任务平台的非权威视图，以及受控完成信号回流 |
| Action | 修改内部日程或向 QQ 发消息的受控操作 |
| Knowledge Chunk | 可被 RAG 检索、但不是日程事实源的带来源文本片段 |
| Connector | QQ、邮箱、AI、嵌入模型等外部系统的适配器 |
| Direct Command | 用户直接发给 Bot、具有命令权限的消息 |
| External Content | 邮件、转发消息、附件和网页等不可信信息 |

## 当前已确定的运行条件

2026-10-19 Go 迁移分支说明：G1 基础层已通过；G2 的账号、凭据、邮箱授权和 HTTP 契约已完成
本地实现与自动化验证，真实 QQ 邮箱沙箱已通过，Microsoft 沙箱已获授权并等待浏览器回调；
G3–G10 尚待迁移。HP 上的旧 Python
Web/Worker/QQ 容器已按所有者要求停止且保留，数据库和 Ollama 继续运行。下文既有阶段与版本
记录属于 Python 历史验证，不能视为 Go 功能已实现。Go 默认 Compose 使用独立开发项目和卷。

- Agent HTTP 入口：仅生产主机 `http://127.0.0.1:8000`，不提供公网入口
- 腾讯云职责：仅托管 `hughsean.online` / `www.hughsean.online` 静态站点和 SSH 管理，不代理 Agent
- 外部连接器：Microsoft Graph `Mail.Read` + `Tasks.ReadWrite` 与单一所有者 QQ 邮箱只读 IMAP
- Microsoft OAuth 客户端：移动和桌面公共客户端，Authorization Code + PKCE，不使用客户端密码
- Microsoft OAuth 回调：`http://localhost:8000/oauth/microsoft/callback`，只允许本机回环访问
- 新开发语言：Go 1.27.2（ADR-0017）；完整迁移按 [32-go-migration.md](32-go-migration.md) 推进
- Go 依赖管理：Go Modules、`go.mod`、`go.sum`；本 Go 分支已按所有者要求移除 Python，原 `Main@c63eae1` 保留对照与回退依据
- 部署：容器模式（ADR-0012），Docker Compose 承载 PostgreSQL + pgvector 与 Web/Worker/QQ
  容器，`APP_CONTAINER` 精确值门禁；Ollama 与应用同在 Compose 私有网络
- Agent 编排目标：Go 显式可恢复状态机；保留原 LangGraph 的控制状态、预算、幂等和门禁语义
- QQ 接入目标：官方 `tencent-connect/botgo v0.2.1`；没有公网服务器，保留出站 WebSocket，真实沙箱通过后才切换
- AI Provider：DeepSeek API，通过独立适配器和 `.env` 注入配置
- 日程存储：项目内部 PostgreSQL，不接入外部日历 Provider
- 用户范围：仅项目所有者本人，拒绝其他 QQ 身份，不设计多租户
- 提醒出口：QQ 官方 Bot 主动消息；Microsoft To Do 原生提醒保持关闭
- RAG：Docker Ollama `qwen3-embedding:4b` + Docker PostgreSQL `pgvector`，混合检索
- 数据保留：日程/任务/笔记随用户删除，邮件与 QQ/RAG 来源 365 天，分层清理策略见 ADR-0009
- 当前阶段：阶段 1 已通过本地基础设施、Ollama 与真实 QQ 沙箱门禁；阶段 2 已通过
  Microsoft 真实连接、refresh、Graph 账号读取、明确确认断开和凭据删除验证；阶段 3
  邮件 Inbox、确定性规范化、Graph delta 同步、异步任务、来源追溯与两轮真实 Mail.Read
  沙箱同步已通过；阶段 4 DeepSeek 结构化理解、受限可恢复 LangGraph 和固定去敏评估已完成，
  阶段 5 Identity 偏好、Agenda 事实源、硬约束排程与版本化 Proposal 已完成；阶段 6 已完成
  QQ 直接/转发文本信任隔离、版本化确认/修改/拒绝、Actions 幂等 Agenda 写入、两步撤销、
  Reminder 持久化租约/重试/推迟/取消，以及真实 QQ 主动提醒恢复验证；阶段 7 已完成
  来源版本、确定性清洗/切块、Ollama 1024 维嵌入、pgvector HNSW + pg_trgm 混合检索、
  DeepSeek 带来源只读回答、删除传播，固定 24 项去敏评估 Recall@10=1.000；阶段 8 已完成
  分层保留、追加式审计、tombstone 恢复重放、指标、隔离备份恢复演练与容器运维制品。
  MVP 后已按 ADR-0010 移除 Agent 公网入口和 SSH 反向隧道依赖；阶段 9 按 ADR-0011 扩展
  QQ 邮箱只读 IMAP，仍复用统一 Inbox/Understanding/RAG 与删除门禁。阶段 10 已按 ADR-0013
  启动统一内容资产与多连接基础实施；Gmail 保持关闭。当前生产环境为 Ubuntu Server Docker
  Compose，Ollama 与应用同栈运行。2026-08-26 已完成首个目标主机部署，数据库迁移至
  `0018_agent_run_delivery`，Web readiness 与 Ollama GPU 模型探针均通过。2026-09-12 已在隔离库
  集成验证、生产备份和日程数据摘要校验后将生产发布升级为 `0029-0912`（提交 `ee5012e`），
  数据库仍为 `0028_summary_contract`；Web readiness 的数据库与嵌入检查均通过。该发布修复了
  多日程请求只执行一条却汇报全部成功、当前日程清单未读取事实源、纯标点检索触发空 embedding、
  DeepSeek 非法结构化输出缺少重试、上下文失败遗留 PENDING 运行以及 QQ 暴露内部异常的问题。
  同日使用本地 `.env` 中更新后的 `QQ_MAIL_BOOTSTRAP_AUTH_CODE` 完成真实 IMAP 校验和生产凭据更新，
  QQ 邮箱连接已恢复为 ACTIVE；授权码值未进入日志、文档或 Git。2026-09-13 又完成
  `0030-0913`（提交 `0975e4c`）生产修复：完成日程保留为 `COMPLETED` 审计记录但从当前
  `ACTIVE` 清单排除，权威清单在模型空输出时采用确定性结果；QQ 直接请求的 Worker 恢复结果
  使用独立幂等通知，不再误套邮件来源策略。部署前后 Agenda/Reminder 完整摘要一致。
  2026-09-13 随后发布 `0031-0913`（提交 `9513019`）：Reminder 正文移除旧 UUID 回复命令，
  只保留交互式完成/推迟按钮；完成按钮改经 Actions 幂等审计门禁执行，按钮异常会向用户返回
  状态中立的安全提示。日程经过结束时间不会自动判定完成。
  2026-09-13 随后发布 `0032-0913`（提交 `5c17b3f`）：修复 `127.0.0.1` 授权入口与固定
  `localhost` 回调不同主机导致的 Cookie 丢失，并使默认入口对现有活动 Microsoft 连接做增量授权；
  OAuth 范围加入委托 `Tasks.ReadWrite`，为“小智建议”To Do 投影提供授权基础。To Do 投影与完成
  回写仍属于阶段 17 后续项，内部 Agenda 继续是唯一事实源。阶段 17 的产品需求、失败矩阵、
  Task Projection 模块边界和实施拆分已在 `25`、`26` 文档冻结；17B 已在 `dev` 完成模块骨架、
  `0029_task_projection` 迁移、短期 task access grant、Graph 列表适配器和“小智建议”唯一列表
  解析的本地门禁；17C 也已在 `dev` 完成 Agenda Transactional Outbox、Worker 幂等投影、每分钟
  ACTIVE 对账补投影、完成/取消收敛以及不确定创建结果的稳定标记恢复。真实账号验证、完成回写和
  QQ 发送前门禁已在 17D 本地完成：每分钟 delta 同步、发送前 3 秒强读取、Actions 幂等完成、已
  租约 Reminder 取消和 Notifications 抑制记录均已接入，所有未知或失败结果继续发送 QQ。17E 的
  独立功能开关已实现且默认关闭。2026-09-14 已完成生产备份、空库及生产副本迁移、实际数据库
  `0028 → 0030` 迁移和 Agenda/Reminder 完整数据比对；真实“小智建议”列表的创建、读取、完成、
  删除沙箱通过，生产已按所有者授权启用 To Do 投影。当前版本为 `0035-0914 / 6edfdb7`，目标 READY、
  3 条活动映射和 delta 游标均正常，Web/Worker/QQ 同镜像零重启且健康检查通过。Graph 列表查询兼容、
  delta 链接规范化校验和 Provider URL/游标日志脱敏问题已修复。真实到期 Reminder 前勾选 To Do 并
  抑制 QQ 仍待自然场景观察，因此 17E 尚未全部完成；未知或失败路径继续发送 QQ。生产主机 NVIDIA
  驱动与 NVML 不匹配，本次以 CPU Ollama 回退保持服务就绪，GPU 恢复留待独立维护窗口。
  阶段 18 已在独立开发分支完成 QQ 连续文本静默窗合并、同会话串行租约、T1/T2 分段、持久化恢复
  Job 和配置化默认日程时长/提醒的本地实现与验证；尚未合并或部署生产。

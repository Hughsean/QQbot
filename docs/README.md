# QQ Time Agent 文档索引

本目录是项目需求、架构边界和验收标准的唯一事实来源。代码实现不得绕过这里定义的边界；需求发生变化时，先修改文档和决策记录，再修改代码。

## 项目定义

QQ Time Agent 是一个仅供项目所有者本人使用、以 QQ 为主要交互入口的个人时间管理 Agent。它从用户直接输入、用户转发的 QQ 消息和已授权邮箱中发现未来事件与任务，在项目内部维护权威日程、完成编排，并通过 QQ 主动提醒。

核心闭环：

```text
信息进入 → 规范化 → 理解 Event/Task → 查询内部日程与相关知识
→ 生成建议 → 用户确认 → 写入内部日程 → 到期主动提醒 → 记录结果
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
| [11-technology-stack.md](11-technology-stack.md) | Python、uv、LangGraph、QQ SDK、DeepSeek 和版本策略 |
| [12-rag-system.md](12-rag-system.md) | Ollama、Qwen3 Embedding、pgvector 和检索边界 |
| [13-development-guardrails.md](13-development-guardrails.md) | 分层、文件规模、架构测试和阶段质量门禁 |
| [14-development-goal.md](14-development-goal.md) | 新对话 Goal mode 的完整开发结果、约束和完成定义 |
| [15-owner-trial-and-operations.md](15-owner-trial-and-operations.md) | 所有者试用、授权、监控、备份恢复与扩展门槛 |
| [16-final-verification-report.md](16-final-verification-report.md) | MVP 最终验证证据、限制和需批准的生产步骤 |
| [17-local-oauth-migration-report.md](17-local-oauth-migration-report.md) | 本机公共客户端迁移、腾讯云清理与控制台验证证据 |
| [18-qq-mail-imap-verification-report.md](18-qq-mail-imap-verification-report.md) | QQ 邮箱 IMAP 扩展的验证证据与试用步骤 |
| [19-containerization-verification-report.md](19-containerization-verification-report.md) | Python 应用容器化部署的验证证据、事件恢复与剩余风险 |
| [adr/](adr/) | 已接受的关键架构决策 |

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
| Action | 修改内部日程或向 QQ 发消息的受控操作 |
| Knowledge Chunk | 可被 RAG 检索、但不是日程事实源的带来源文本片段 |
| Connector | QQ、邮箱、AI、嵌入模型等外部系统的适配器 |
| Direct Command | 用户直接发给 Bot、具有命令权限的消息 |
| External Content | 邮件、转发消息、附件和网页等不可信信息 |

## 当前已确定的运行条件

- Agent HTTP 入口：仅 Windows 本机 `http://127.0.0.1:8000`，不提供公网入口
- 腾讯云职责：仅托管 `hughsean.online` / `www.hughsean.online` 静态站点和 SSH 管理，不代理 Agent
- 邮箱连接器：Microsoft Graph `Mail.Read` 与单一所有者 QQ 邮箱只读 IMAP
- Microsoft OAuth 客户端：移动和桌面公共客户端，Authorization Code + PKCE，不使用客户端密码
- Microsoft OAuth 回调：`http://localhost:8000/oauth/microsoft/callback`，只允许本机回环访问
- 开发语言：Python 3.12（`qq-botpy 1.2.1` 在 Python 3.14 客户端初始化失败，已按兼容策略降级）
- 项目与依赖管理：uv、项目内 `.venv`（开发）、提交 `uv.lock`
- 部署：容器模式（ADR-0012），Docker Compose 承载 PostgreSQL + pgvector 与 Web/Worker/QQ
  容器，`APP_CONTAINER` 精确值门禁；Ollama 保持主机回环监听
- Agent 编排：LangGraph，确定性流程为主、受限 Agent 节点为辅
- QQ 接入：QQ 开放平台官方 Python SDK `qq-botpy`
- AI Provider：DeepSeek API，通过独立适配器和 `.env` 注入配置
- 日程存储：项目内部 PostgreSQL，不接入外部日历 Provider
- 用户范围：仅项目所有者本人，拒绝其他 QQ 身份，不设计多租户
- 提醒出口：QQ 官方 Bot 主动消息
- RAG：Windows 生产主机 Ollama `qwen3-embedding:4b` + Docker PostgreSQL `pgvector`，混合检索
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
  QQ 邮箱只读 IMAP，仍复用统一 Inbox/Understanding/RAG 与删除门禁。尚未执行生产部署

# 交付计划

## 阶段 0：需求和边界冻结

交付物：

- 产品范围和不做清单。
- 模块边界和数据所有权。
- 安全模型、领域模型和接口契约。
- 单用户范围、内部日程、RAG 边界和 Microsoft 公共客户端应用注册。

完成标准：文档无冲突，所有后续实现都能归属到唯一模块。

## 阶段 1：基础骨架

交付物：

- 项目结构、配置加载、日志脱敏。
- `pyproject.toml`、`.python-version`、`uv.lock` 和项目内 `.venv`。
- Python 3.12 与 QQ 官方 SDK 的沙箱网关、C2C 收发和重连测试；已记录 Python 3.14 Client 初始化不兼容。
- Web/Worker 进程和健康检查。
- PostgreSQL + pgvector、数据库迁移、Outbox/Job 基础设施。
- Docker Ollama `qwen3-embedding:4b` 健康检查、冷/热启动和 1024 维契约测试。
- Data Lifecycle、Tombstone、模块级清理端口和保留策略配置骨架。
- 架构边界测试。

完成标准：生产主机 `http://127.0.0.1:8000/health/ready` 正常，所有服务只监听回环或使用出站连接，未接入任何真实用户数据。

## 阶段 2：Microsoft 账号连接

交付物：

- OAuth start/callback/disconnect。
- Credential Vault。
- Connections 状态机。
- Graph 账号信息读取。

完成标准：自己的 Outlook 账号可以连接、刷新、断开；数据库和日志中找不到明文 token。

## 阶段 3：邮件收件箱

交付物：

- 最近邮件读取和增量同步。
- MIME/正文规范化。
- Inbox 去重、重试和状态机。
- 邮件来源追溯视图。

完成标准：重复同步不产生重复 InboxItem，授权失效能正确进入 `REAUTH_REQUIRED`。

## 阶段 4：理解能力

交付物：

- Event/Task/无关信息分类。
- 时间解析、结构化提取和 schema 校验。
- 提示注入隔离和低置信度处理。

完成标准：去敏固定测试集的分类准确率不低于 90%、Event/Task 结构化提取准确率不低于
85%、提示注入隔离样例通过率为 100%；任何模型输出都不能直接形成 Action。

## 阶段 5：内部日程与排程

交付物：

- Agenda 内部日程、忙闲查询、用户偏好和 Scheduling Proposal。
- 冲突解释和备选时间。

完成标准：Proposal 遵守硬约束，Task 与 Event 语义保持分离。

## 阶段 6：QQ 确认闭环

交付物：

- QQ 直接输入和转发文本。
- Proposal 确认、修改、拒绝。
- Actions 幂等写内部日程、结果通知和撤销。
- Reminder 持久化调度、主动提醒、完成和推迟。

完成标准：三个核心场景端到端通过，重复确认不会创建重复事件。

## 阶段 7：RAG

交付物：

- Knowledge 来源版本、确定性清洗和切块。
- Ollama Embedding Adapter 和 pgvector 索引。
- 向量、关键词、元数据过滤的混合检索和来源引用。
- 删除同步、索引重建和固定检索评估集。

完成标准：检索结果可追溯；删除来源后不可再召回；RAG 不能修改日程或绕过确认；去敏固定评估集的混合检索 Recall@10 不低于 0.85。

## 阶段 8：个人试用与加固

交付物：

- 隐私政策、数据删除说明和用户授权说明。
- 监控、告警、备份恢复演练。
- 项目所有者本人真实使用和指标收集。

完成标准：安全检查通过，错误创建和撤销率处于可接受范围，再决定是否扩展 Gmail、QQ 邮箱和附件。

## 实施顺序约束

当前 Agent harness 架构决策见 `docs/21-agent-harness-and-calendar-system.md`：所有者的合规日程
更新默认自动执行并返回结果，不再要求用户输入确认码；歧义、冲突、过期版本和策略不允许的操作
仍由 Calendar System 拒绝并交给 Agent 追问。该决策替代早期“所有日程写入必须用户二次确认”的
交互要求，但不削弱所有者鉴权、版本校验、幂等和审计门禁。
QQ 与邮件统一创建持久化 AgentRun，通过 Job 租约、有限重试和死信恢复；Calendar System 不得直接
调用 Agenda/Reminder 命令端口，所有写入必须经 Actions 形成持久化执行记录与审计。
AgentRun 关联明确的 Conversation 或 EventCase；Understanding 可作为可选提取，不能成为 Agent
执行的强制前置任务。

- 不得在 Credential Vault 完成前保存真实 refresh token。
- 不得在 Inbox 去重完成前启用周期性邮件同步。
- 不得在确认和 Actions 门禁完成前启用内部日程写入。
- 不得在来源版本、删除传播和引用契约完成前把 RAG 用于正式回答。
- 不得通过统一清理任务跨模块直接删表；所有删除必须调用数据所有模块的清理端口。
- 不得为赶进度让 Provider DTO 或 SDK 穿透模块边界。
- 所有环境都不得关闭所有者 QQ 身份白名单；测试其他身份必须使用隔离的假 Provider。

## 阶段 9：QQ 邮箱只读 IMAP 扩展

前置条件：阶段 8 已完成，所有者明确决定启用 QQ 邮箱扩展；Microsoft 已保持本机公共客户端
PKCE，禁止恢复公网入口、SSH 反向隧道、公网回调或客户端密码。

交付物：

- 本机所有者连接、状态、重新认证和确认断开；授权码经 Credential Vault 加密。
- `imap.qq.com:993` 强制证书校验 TLS，只读 INBOX 定时轮询。
- UIDVALIDITY/UID 不透明游标、稳定 Provider 唯一键、游标重置二次幂等和错误分类。
- header、multipart text/html 与附件元数据映射，附件内容不下载。
- 统一 Inbox、Normalization、Understanding、RAG、保留与 tombstone 删除传播。
- 单元、契约、PostgreSQL/Worker 集成与显式真实 QQ 邮箱两轮沙箱。

完成标准：真实沙箱 TLS 登录和两轮增量同步通过，第二轮不重复创建 InboxItem；UIDVALIDITY
变化测试无遗漏/重复；断开后凭据、待执行任务和所有连接来源派生数据清理；Microsoft、QQ Bot、
Agenda、Reminder、RAG 全量门禁无回归。

## 阶段 10：P1 内容资产与多连接基础

前置条件：阶段 9 与 ADR-0013 已完成并接受。

交付物：Inbox-owned SourceAsset 契约/元数据/状态机、受限 BlobStore Port、连接账号 fingerprint 与
多连接 schema、保留/删除端口、迁移和安全上限配置。此阶段不下载真实附件，也不启用新通知。

完成标准：0013 → 新 head 升级、降级和空库重建通过；现有连接无损回填；资产幂等、状态转换、
24 小时原始 blob 清理与 tombstone 删除测试通过；模块边界和秘密扫描通过。

当前状态：已完成。Inbox-owned SourceAsset、受限本地 BlobStore、版本化资产任务、HMAC 账号 fingerprint、
多连接 schema 与 24 小时原始 blob 保留策略已落地；资产幂等、重启恢复、父来源先删 blob 再级联、
tombstone 重放、迁移往返与空库重建均通过。

## 阶段 11：多邮箱连接生命周期

交付物：Microsoft/QQ Mail 多连接创建、列表、标签、默认项、独立同步/暂停/断开；Job、游标、
凭据、限流和删除传播全部按 connection 隔离。

完成标准：同 Provider 两个连接可独立同步和删除，断开一个不会读取、取消或删除另一个连接的数据；
所有者页面和日志不暴露凭据或完整账号标识。

当前状态：已完成。Microsoft 与 QQ Mail 连接均使用 HMAC 账号 identity、独立 label/default/sync 开关；
同步 Job、游标、Inbox 去重、附件抓取、断开取消和删除传播全部按 connection 隔离。双连接持久化、默认项切换、
单连接断开及来源清理测试通过，公开视图和日志仅保留掩码/脱敏标识。

## 阶段 12：标准 ICS 确定性解析

交付物：RFC 5545 Parser Port、VEVENT/VTIMEZONE/UID/SEQUENCE/METHOD/RECURRENCE-ID 映射、版本
幂等和待确认 Event/Cancellation Candidate。

完成标准：REQUEST、更新、CANCEL、重复规则、DST、未知 TZID 和畸形输入 fixture 全部通过；
ICS 不能直接写 Agenda 或发送通知。

当前状态：已完成。解析器、HMAC 外部事件键、UID/RECURRENCE-ID/SEQUENCE 持久化幂等、过期版本隔离、
Agenda 来源匹配和待确认创建/更新/取消候选均已接入 Worker；删除传播、迁移往返和 PostgreSQL 测试通过。

## 阶段 13：邮件附件与 PDF

交付物：Microsoft/QQ Mail 附件描述和按需抓取、受限 MIME/大小策略、PDF 文本提取、扫描 PDF OCR、
规范化来源引用和删除传播。

完成标准：附件不会改变邮件已读状态；超大/不支持/损坏文件终态隔离；相同资产不重复解析；
删除连接或来源后 blob、文本、chunk 和向量均不可见。

当前状态：已完成。Microsoft Graph 与 QQ IMAP 已完成元数据优先、按需只读附件抓取；PDF 文本、扫描 PDF
离线 OCR、资产规范化、Knowledge 重建、24 小时 blob 清理、重启恢复和可终止的进程级解析超时已完成；
blob、规范化文本、Knowledge chunk/向量的 tombstone 删除及旧备份重放测试通过。

## 阶段 14：QQ 图片、截图与合并转发

交付物：官方 QQ 媒体描述/抓取 Adapter、本地 OCR、合并转发节点模型与稳定顺序规范化；caption T1、
资产和嵌套节点 T2。

完成标准：官方沙箱图片/OCR/合并转发可用性验证；权限不足时明确失败且无非官方降级；嵌套内容
不能触发命令，重复事件不重复建 Inbox/Asset/Knowledge。

当前状态：已完成。官方 C2C 图片描述映射、受限 QQ CDN 抓取、离线 OCR、媒体消息命令隔离、
直接消息资产幂等/删除传播，以及合并转发稳定顺序和资源上限的 Provider-neutral 规范化已通过本地、契约和
PostgreSQL 门禁；共享镜像已验证非 root Linux 容器中的 ONNX Runtime、包内模型、独立解析子进程和 Web
健康检查。当前安装的官方 SDK 公开 `Message.attachments`，但未公开合并转发节点模型；该类型会
明确回复“不支持或无权限”，且不接入非官方降级。真实 QQ 沙箱已验证 URL-only C2C 图片事件、
受限 CDN 下载和离线 OCR 端到端成功；合并转发在官方节点模型缺失时按能力不可用处理。

## 阶段 15：每日摘要与主动状态提醒

交付物：NotificationIntent、所有者通知偏好、确定性 Daily Digest、Agenda 冲突提醒、Connection
重新授权提醒、幂等/cooldown/静默时段和运行指标。

完成标准：重启和至少一次执行不产生重复通知；冲突只在版本产生新冲突时提醒；授权恢复后不再提醒；
摘要不含已删除或未确认内容；QQ 沙箱主动消息与全量回归门禁通过。

当前状态：已完成。Notifications-owned `NotificationIntent`、模板/主题/版本幂等键、
`FOR UPDATE SKIP LOCKED` 租约、发送边界静默时段/DST 复核、24 小时重新授权 cooldown 和公开状态指标已接入；
Worker 只生成持久化意图，QQ 进程发送前重新校验 Agenda/Connection/偏好并取消失效来源。部分唯一索引阻止
同一 subject 积累多个未决意图；明确发送前失败有限重试并可死信，未知发送结果与过期租约进入
`AMBIGUOUS` 且不自动重发。每日摘要只读取 ACTIVE Agenda 快照，冲突键规范化排序 Agenda ID 并包含双方版本，
重新授权 episode 仅在状态转入 `REAUTH_REQUIRED` 时递增。0014/0015 往返、空库直升 head、PostgreSQL
幂等/并发租约/重启恢复、Ruff、strict mypy、架构和全量非沙箱回归已通过；官方 QQ 主动消息沙箱验证成功。

## 阶段 16：邮件通知策略修复（ADR-0014）

交付物：邮件分类 × 投递矩阵提示词、确定性投递层（Identity 邮件规则 > 模型判定）、
`MAIL_DIGEST` 次日邮件摘要兜底、邮件 run 日程变更工具授权拒绝、`ToolCallContext` 来源
溯源与 `source_refs` 渲染、`find_recent_mail` 只读工具、`register_mail_rule` 规则工具、
`create_agenda` 显式 `reminder_due_at`、固定去敏投递评估集和 `identity_mail_rules` 迁移。

完成标准：以 2026-08-31 事件为原型的固定评估集中，面试/测评/到期类邮件必须 NOTIFY，
确认/记录类 HOLD，不确定类倾向 NOTIFY；邮件来源 run 调用日程变更工具被授权层拒绝；
规则命中双向覆盖模型判定；每个完成的邮件 run 摘要出现在次日邮件摘要（已推送的除外）；
提示词改动必须通过该评估集；Ruff、strict mypy、架构与全量非沙箱回归通过。

## 阶段 17：Microsoft To Do 投影（ADR-0015）

目标：Microsoft To Do 仅作为 Agenda 外部视图和完成标记入口；QQ 仍是唯一主动提醒出口。详细需求
与模块设计见 `docs/25-microsoft-todo-requirements.md` 和 `docs/26-microsoft-todo-module-design.md`。

### 17A：需求与模块边界冻结

交付物：完成状态回流边界、QQ 提醒决策矩阵、`Task Projection` 数据所有权、公共端口、竞态策略、
实施与回滚拆分。

完成标准：明确 Agenda 唯一事实源、To Do 原生提醒关闭、只有核验完成才能抑制 QQ；任务缺失、
超时、失权、限流和版本过期一律继续发送 QQ；文档之间无冲突。

当前状态：已完成。

### 17B：授权接入、模块骨架与列表解析

交付物：Microsoft OAuth `Tasks.ReadWrite` 增量授权、Task Projection 模块和迁移、Graph task adapter、
短期 task access grant、固定“小智建议”列表解析。

完成标准：已有邮件连接增量授权不重复建连接或中断邮件同步；`127.0.0.1` 授权入口与固定
`localhost` 回调同主机；授权失败可按脱敏分类诊断；零个或多个同名列表明确失败且不猜测。

当前状态：本地开发已完成。`127.0.0.1` 入口规范化、已有活动连接增量授权、失败分类日志、
`Tasks.ReadWrite` 同意范围和邮件刷新保持最小旧范围均已验证；Task Projection 模块骨架、
`0029_task_projection` 迁移、短期 task access grant、Graph 列表适配器、“小智建议”唯一且私有的
所有者列表解析、OAuth 成功后的非阻断解析和受 CSRF 保护的显式重试接口已通过本地自动化门禁。
真实 Microsoft 账号列表解析留在 17E 沙箱与生产启用门禁，不在本阶段宣称完成。

### 17C：Agenda 单向投影

交付物：Agenda 创建/修改/完成/取消 Outbox 消费、幂等 upsert、活动历史条目补投影、重试、死信和
对账。To Do 标题、时间、正文编辑不反向写 Agenda，任务原生提醒保持关闭。

完成标准：相同 Agenda 版本不产生重复任务；外部写失败不回滚 Agenda；Worker 重启、Graph 成功后
本地事务前崩溃、Outbox 重放和对账重建均能收敛。

当前状态：本地开发已完成。Agenda 创建、修改、完成和取消与 Outbox 同事务提交；Worker 以事件 ID
幂等入队并使用持久化租约、有限重试和死信。每分钟有界扫描当前 `ACTIVE` 条目，既补投影历史数据，
也用 Agenda 当前字段覆盖外部视图；任务原生提醒始终关闭。Graph 创建结果不确定时不盲目重发 POST，
而是先按不可逆稳定标记恢复既有任务；Agenda 完成标记为 To Do 完成，Agenda 取消则删除外部任务，
两者均不反向接受外部标题、时间或正文。真实 Microsoft 账号写入留在 17E 沙箱门禁。

### 17D：完成回写与 QQ 提醒门禁

交付物：每分钟 delta 同步、发送前 3 秒预算强读取、Actions `COMPLETE_AGENDA` 幂等回写、已租约
Reminder 安全取消、Notifications 抑制记录。

完成标准：核验完成且 Actions 成功时不发 QQ；未完成、未映射、任务删除/移动、授权失效、限流、
网络错误、超时或版本不符时继续发送；QQ 按钮和 To Do 完成竞态只形成一次完成状态变更。

### 17E：沙箱、生产启用与回滚

交付物：隔离库集成测试、Microsoft/QQ 真实沙箱、生产备份和迁移、活动 Agenda 分批补投影、指标、
告警和关闭开关。

完成标准：发布前后 Agenda/Reminder 摘要一致；真实 To Do 勾选能在提醒前抑制 QQ；关闭 Task
Projection 后内部日程查询、QQ 按钮与提醒恢复原有行为；Provider ID、token 和游标不进入日志。

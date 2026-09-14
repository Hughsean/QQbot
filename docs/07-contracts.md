# 接口契约

本文只定义稳定语义，不绑定具体 Web 框架、ORM 或消息队列。

## 1. 外部 HTTP 接口

### 健康检查

```text
GET /health/live
GET /health/ready
```

- `live` 只表示进程可响应。
- `ready` 检查必要依赖，但不得泄露依赖地址和凭据。

### Microsoft OAuth

```text
GET  /oauth/microsoft/owner-start
POST /api/v1/owner/session
GET  /oauth/microsoft/start[?connection_id=<uuid>]
GET  /oauth/microsoft/callback
POST /api/v1/oauth/microsoft/disconnect
GET  /api/v1/connections/microsoft
GET  /api/v1/connections/microsoft/status
POST /api/v1/connections/microsoft/todo/resolve
```

约束：

- `owner-start` 只接受 Windows 本机回环访问。`127.0.0.1` 入口必须先无秘密地重定向到
  `localhost`，再设置短期 `HttpOnly` Cookie，保证授权起点与固定 callback 同主机；签名不进入
  URL、访问日志或跨站 Referer。
- `owner/session` 只通过本机回环 POST 接收短期签名会话，验证后写入
  `HttpOnly`、`SameSite=Lax` Cookie，再跳转到 `start`；Lax 用于让 Microsoft 的顶层 GET
  回调携带短期 OAuth 会话，不能放宽为跨站子请求。
- `start` 必须绑定当前已认证所有者；不得接受 URL 查询参数中的会话或 token。
- `owner/session`、`start`、`callback`、连接状态和断开接口均拒绝非回环 Host。
- `callback` 不把授权码、token 或 Provider 原始错误展示给用户。
- 默认 `owner-start` 若发现已有活动 Microsoft 默认连接，必须对该 Connection 发起增量授权；
  授权未完成或失败时不得把原连接改为不可用，也不得产生同账号重复连接。
- `disconnect` 使用 CSRF 防护和明确确认。
- 列表/状态接口只返回 Connection ID、所有者 label、默认/同步开关、能力、账号掩码、同步时间
  和健康状态。无 `connection_id` 的旧 status 接口只返回显式默认连接；新操作必须携带 Connection ID。
- OAuth 成功后自动尝试解析“小智建议”列表；列表解析失败不得回滚已成功的连接授权。`todo/resolve`
  提供本机所有者显式重试，要求同源 CSRF，只返回内部 target ID、连接 ID、列表显示名、状态和版本，
  不返回 Microsoft list ID。零个或多个同名列表均返回安全冲突提示。

### 同步

```text
POST /api/v1/connections/{connection_id}/sync
GET  /api/v1/sync-jobs/{job_id}
GET  /api/v1/inbox/{inbox_item_id}/source
```

同步请求返回任务 ID，不在 HTTP 请求内完成全量邮件处理。任务状态只返回状态、尝试次数、
错误分类和更新时间，不返回 job payload、增量游标或邮件正文。来源追溯视图返回来源类型、
Provider 消息 ID、线程 ID、发件人掩码、主题、原始时间、处理状态和删除标记。

### QQ 邮箱 IMAP

```text
GET  /qq-mail/owner-start
GET  /qq-mail/connect
POST /api/v1/connections/qq-mail
GET  /api/v1/connections/qq-mail
GET  /api/v1/connections/qq-mail/status
POST /api/v1/connections/qq-mail/disconnect
```

- 全部接口只接受回环 Host 和已签名所有者会话；写接口要求同源 CSRF。
- connect body 只接收完整 QQ 邮箱地址与秘密授权码，不接收 QQ 登录密码、Host、Port 或 TLS
  开关。授权码不得进入 URL、响应、日志、异常或 Job payload。
- connect 可新增不同 QQ 邮箱，也可用于匹配账号的 `REAUTH_REQUIRED`/`DISCONNECTED` 重新
  认证；同一账号活动连接重复提交被拒绝。所有后续操作按 Connection ID 隔离。
- disconnect 需要连接 ID 和显式确认，取消该连接待执行 Job、删除凭据，再触发连接来源删除传播。

## 2. 模块契约

### InboxCommandPort

```text
ingest(sourceEnvelope) -> IngestResult
markProcessing(itemId, expectedVersion)
markCompleted(itemId, expectedVersion)
markFailed(itemId, failureClass, expectedVersion)
```

`ingest` 必须根据 Provider 唯一键幂等。

### AgentTurnIntakePort

```text
stage(segment: AgentTurnSegment) -> StagedTurnSegment
settle(conversationKey, generation) -> SettledAgentTurn | Superseded
complete(turnId, result) -> TurnCompletion
```

`AgentTurnSegment` 携带 Inbox ID、来源/信任标签、`msg_seq`、引用哈希和有界长度；正文与附件仍由
Inbox 持有，不复制到 Turn 表。Provider ID 只用于幂等与关联，不进入日志。`stage` 必须先持久化
Inbox，再登记 turn segment；`settle` 使用
有界静默窗口且同一 Conversation 只能有一个执行租约。`SettledAgentTurn` 分开返回 T1 live command
与 T2 evidence，不得返回无信任标签的拼接文本。重复 stage/complete 必须返回已有结果。

### OwnerGroupAliasPort

```text
listOwnerGroupAliases(userId) -> OwnerGroupAlias[]
registerOwnerGroupAlias(userId, alias) -> OwnerGroupAlias
```

群聊展示昵称是所有者身份资料的一部分，由 Identity 模块保存。只有经过 QQ 直接身份验证的
所有者 AgentRun 可以调用登记命令；别名归一化后按所有者幂等。上下文装配可以读取别名，将其作为
可信的发言归属规则，但转发聊天记录本身仍是 T2 外部内容，不能获得命令权限。缺少映射时必须要求
所有者登记，禁止依据聊天语气、日程或模型猜测身份。

### MailRulePort（ADR-0014）

```text
listMailRules(userId) -> MailRule[]
registerMailRule(userId, matchField, pattern, action) -> MailRule
```

所有者邮件通知规则由 Identity 保存。`matchField` 只允许 `SENDER`/`SUBJECT`（包含匹配，大小写不敏感），
`action` 只允许 `NOTIFY`/`HOLD`。只有 QQ 直接身份验证的所有者 AgentRun 可以经
`register_mail_rule` 工具登记；规则按所有者与归一化 pattern 幂等。通知投递解析读取规则并
双向覆盖模型判定；上下文装配以只读方式注入规则，使模型自述与真实配置一致。

### RecentMailQueryPort（ADR-0014）

```text
listRecentMail(limit, keyword?) -> RecentMailItem[]
```

Inbox 拥有的只读近期邮件元数据查询，支撑 Agent 的 `find_recent_mail` 工具。返回项只包含
inbox_item_id、source_type、主题、脱敏发件人、occurred_at、状态与删除标志；`limit` 上限 20，
`keyword` 只匹配主题。不得暴露正文、附件、凭据或 Provider 内部标识。

### MailRunSummaryQueryPort（ADR-0014）

```text
listRecentMailSummaries(since, limit) -> MailRunSummary[]
```

Agent 拥有的邮件 run 摘要只读查询，供 Notifications 生成每日邮件摘要。返回项只包含 run_id、
inbox_item_id、source_type、final_content 摘要与完成时间；只返回 COMPLETED 的邮件来源 run。

### 统一 MailProvider

```text
MailAccessGrant(connection_id, user_id, account_id, mail_credential)
fetchPage(mailCredential, accountId, opaqueCursor, since) -> MailDeltaPage
fetchContent(mailCredential, accountId, change) -> MailChange
```

`MailChange` 同时包含 Provider 唯一键和跨游标重置去重键。QQ Provider 唯一键必须包含邮箱不可逆
标识、INBOX、UIDVALIDITY 和 UID；统一层把 cursor 当作不透明字符串，不解释 UID。Provider DTO、
IMAP/MIME 对象在 Adapter 内转换后销毁。

### UnderstandingPort

```text
classify(inboxItemId) -> ClassificationDecision
extractCandidate(inboxItemId, classificationKind, classificationConfidence) -> ExtractionDecision
validateAndSaveCandidate(inboxItemId, candidateDraft) -> UnderstandingResult
```

`ClassificationDecision` 必须包含分类、置信度、复核原因和已有 Candidate 引用；只有 Event/Task
且尚无 Candidate 的结果可以进入提取。`ExtractionDecision` 只携带 Provider 中立的有界草稿、
置信度和复核原因，不能携带 Provider DTO。输出必须包含依据字段和显式假设。

阶段 4 的实现使用 DeepSeek JSON Output，但 Provider JSON 必须先转换并经过本地 Pydantic
schema（拒绝额外字段）、时间/时区、证据、来源和信任校验。`MEDIUM` 优先级只在 Adapter
后的本地 schema 中白名单归一为领域 `NORMAL`，其他未知枚举拒绝。模型只返回候选，不存在
Action、Agenda 或 Notification 工具。

相对日期使用 Inbox 来源的 `occurred_at` 与所有者时区解释，不使用 Worker 当前墙上时间。
Event 缺少持续时间时使用强类型配置的默认值并追加显式假设；Task deadline 不得填入 Event
的开始/结束字段。置信度低于 0.75、时间含糊、schema/证据非法或模型不可用时进入
`NEEDS_REVIEW`，不会静默形成候选。

Workflow 依次执行 `classify`、`extract_candidate`、`validate_candidate`、`persist_decision` 和
`apply_disposition`。checkpoint 仅在 `CLASSIFIED`、`DECIDED`、`COMPLETE` 持久化控制状态；候选
草稿不持久化，合法 Candidate 仍由 Understanding 模块在自己的事务中保存。

### AgendaQueryPort

```text
getBusyIntervals(range) -> BusyInterval[]
getEntry(entryId) -> AgendaEntryView
```

### AgendaCommandPort

```text
createEntry(actionContext, agendaDraft, idempotencyKey) -> AgendaEntryRef
reviseEntry(actionContext, entryId, expectedVersion, patch, idempotencyKey) -> AgendaEntryRef
cancelEntry(actionContext, entryId, expectedVersion, idempotencyKey) -> CancelResult
```

只有 Actions 或 Calendar System 内部用例可以调用 AgendaCommandPort；Agent 和其他模块只能调用 Calendar System 的公开工具。Calendar System 必须执行所有者授权、参数、冲突、版本和幂等校验。

### SchedulingPort

```text
propose(subject, constraints, busyIntervals, retrievedContextRefs?) -> SchedulingProposal
revise(proposalId, expectedVersion, userFeedback) -> SchedulingProposal
expire(proposalId, expectedVersion)
```

阶段 5 的 Scheduling 是确定性只读用例，只依赖 `CandidateQueryPort`、`UserPreferencesPort`、
`AgendaQueryPort` 和自己的 Proposal Repository；不得取得 `AgendaCommandPort`。Task 在 15 分钟
网格上搜索，硬约束包括 Identity 所有者时区、工作日、工作时段、午休、允许窗口、deadline、
预计时长和 Agenda 忙时；无 deadline 的搜索窗口最多 14 天。返回一个主时段和最多两个备选，
找不到时必须给出冲突/无空闲解释。

Event 的固定起止时间不由 Scheduling 移动；若与不可移动 Agenda 条目重叠，Proposal 的推荐
时段为空并列出冲突。Task deadline 只限制可选执行块，绝不直接作为 Event/Agenda 时段。
Proposal 保存约束快照、来源、假设、过期时间和版本，初始状态为 `PENDING_CONFIRMATION`；创建
Proposal 本身不写 Agenda，也不发送通知。

### ConfirmationPort

```text
confirm(userId, proposalId, version, confirmationToken) -> ConfirmationResult
reject(userId, proposalId, version, reason?) -> RejectionResult
```

阶段 6 的 QQ 确认码格式为 `<proposal UUID 前 8 位>-<版本>`，仅由已认证所有者的独立
`QQ_DIRECT` 消息解析。`QQ_FORWARD` 固定为 T2 数据，即使正文包含“确认”也只会进入 Inbox、
Normalization 和 Understanding。修改只能选择当前 Proposal 已提供的主/备选时段，并产生新版本；
旧确认码随即失效。确认成功后 Actions 使用 `proposal:{proposal_id}:v{confirmed_version}:create`
稳定键写 Agenda，并使用派生键安排 Reminder；重复确认或进程中断后的重放不会创建重复条目。

撤销分两步：`撤销 <agenda_entry_id>` 只创建待确认的 `CANCEL_AGENDA` Action，随后必须以
`撤销确认 <action_id> <token>` 执行。完成命令只把活动条目标记为 `COMPLETED`；推迟命令只对
已经发送的具体 Reminder 轮次生效，每次推迟增加 occurrence，使同一轮重试去重而新轮次可发送。

### NotificationPort

```text
sendConfirmation(userId, proposalView) -> DeliveryRef
sendResult(userId, actionResultView) -> DeliveryRef
sendReauthRequired(userId, connectionView) -> DeliveryRef
```

Notifications 保存稳定投递键和 QQ 回执；相同 Proposal 版本、Action 结果或 Reminder occurrence
不会由应用主动重复发送。QQ 官方主动 C2C API 没有业务幂等键；`msg_id + msg_seq` 仅适用于被动
回复。因此“Provider 已接收但本地回执事务尚未提交时进程崩溃”仍是一个极窄重复窗口，必须通过
重复发送监控与用户可见的 Reminder 标识审计，不能声称 Provider 提供 exactly-once。

Reminder 主动消息正文只展示标题、本地时间和提前量，不展示 Agenda/Reminder UUID，也不再包含
“回复完成/推迟”的旧文本命令。完成与推迟由 QQ 交互式按钮承载；按钮数据只携带随机令牌。令牌
绑定所有者、动作类型、Agenda 版本和 Reminder occurrence，24 小时内有效，同一 occurrence 的
完成/推迟按钮只有第一个有效领取，重复、串改、过期或状态已变化的点击不能再次执行副作用。
完成按钮必须经 Actions 的幂等 `COMPLETE_AGENDA` 操作写入审计并取消旧版本提醒；推迟按钮只能经
Reminders 门禁把已发送的当前 occurrence 增加为下一轮。到达 Agenda `ends_at` 本身不改变状态，
未点击按钮或未发直接命令时条目继续保持 ACTIVE，不得把时间经过推断成用户已完成。
QQ 回调确认、业务动作与结果消息是三个独立阶段；动作异常时必须返回不推断最终状态的安全提示，
不得在回调已确认后只记录日志而让用户无反馈，也不得暴露内部异常。

QQ 直接消息的同步执行会直接回复当前消息，其 30 秒延迟 Job 只用于崩溃或 Provider 失败恢复。
同步路径已完成的 Job 必须无副作用结束；只有 Worker 实际完成的 `QQ_DIRECT` Run 才冻结
`NOTIFY` 恢复标记并创建 `QQ_DIRECT_AGENT_RESULT` intent。该 intent 按 Run ID 幂等，不依赖邮件
来源，也不受邮件静默时段影响。若 `list_agenda` 已成功而最终模型 JSON 无效，Agent Harness 必须
直接使用该权威观察结果生成清单，不得返回通用失败或复用历史日程文本。

### ReminderCompletionGatePort（ADR-0015）

```text
evaluateBeforeDelivery(
  userId,
  agendaEntryId,
  expectedAgendaVersion,
  reminderOccurrence,
  observedAt,
) -> ReminderCompletionDecision
```

该端口由 Task Projection 实现，Notifications 在调用 QQ Provider 前使用。决策只允许：

```text
SUPPRESS_COMPLETED
SEND_NOT_COMPLETED
SEND_UNMAPPED
SEND_UNAVAILABLE
SEND_STALE
```

只有强读取映射任务为 `completed`，且 Actions 已成功完成 Agenda 或确认该条目已经完成，才能返回
`SUPPRESS_COMPLETED`。其他结果全部继续发送 QQ。任务缺失、删除、移动、授权失效、限流、网络
错误、超时和版本不一致不能解释为完成。默认总调用预算为 3 秒，提醒关键路径内不做长退避重试。
结果只返回内部原因码和审计引用，不返回 Provider ID、token、delta link 或原始异常。

### TaskProjectionCommandPort（ADR-0015）

```text
projectAgendaEntry(entryId, expectedVersion, idempotencyKey) -> ProjectionResult
closeProjection(entryId, expectedVersion, reason, idempotencyKey) -> ProjectionResult
reconcileConnection(connectionId, cursor?) -> ReconciliationResult
```

Agenda 创建、修改、完成和取消以 Outbox/Event 驱动该端口。相同 Agenda 版本重复调用必须幂等；
外部失败只改变投影 Job/映射状态，不能回滚 Agenda 或阻断 QQ。首次启用只补投影 `ACTIVE` 条目。

### TaskProviderPort（ADR-0015）

```text
resolveManagedList(accessGrant, normalizedName) -> ManagedTaskList
upsertTask(accessGrant, listRef, taskDraft, providerTaskRef?) -> ExternalTaskView
getTask(accessGrant, listRef, taskRef) -> ExternalTaskView
completeTask(accessGrant, listRef, taskRef, expectedRevision?) -> ExternalTaskView
deleteTask(accessGrant, listRef, taskRef, expectedRevision?) -> ExternalTaskResult
fetchDelta(accessGrant, listRef, opaqueCursor?) -> ExternalTaskDeltaPage
```

首个受管列表的归一化名称固定为“小智建议”。零个匹配和多个同名匹配均明确失败，不得猜测列表
ID。`ExternalTaskView` 是 Provider 中立 DTO；Microsoft Graph SDK 类型、响应头和异常不得越过
Adapter。任务投影禁用 Provider 原生提醒，外部标题、时间、正文、删除、移动和重新打开都不形成
Agenda 命令。

### ConnectionTaskAccessPort（ADR-0015）

```text
acquireTaskAccess(userId, connectionId, requiredCapability) -> TaskAccessGrant
```

Connections 校验所有者、连接状态和 `TASKS_READ_WRITE` 能力，Credential Vault 提供短生命周期凭据
句柄。`TaskAccessGrant` 不可持久化、序列化或日志化；Task Projection 不读取凭据表或环境变量。

### CalendarActionPort 完成扩展（ADR-0015）

```text
completeAgenda(actionContext, entryId, expectedVersion, idempotencyKey) -> CompleteAgendaResult
```

To Do 完成回写必须调用该端口，稳定幂等键由连接、映射和 Provider revision 派生。Actions 在自己的
事务中写 ActionRequest，并通过 Agenda/Reminder 公开端口完成条目和取消旧提醒。QQ 按钮与 To Do
完成并发时，两条路径必须收敛到一个成功的 Agenda 最终状态；Task Projection 不得直接写 Agenda
或 Reminder。

### EmbeddingPort

```text
embed(texts, modelId, dimensions) -> EmbeddingBatch
health() -> EmbeddingProviderHealth
```

返回结果必须包含实际模型标识和维度；与索引契约不一致时拒绝写入。

### KnowledgeIndexPort

```text
upsertSource(sourceRef, sourceVersion, normalizedContent, metadata) -> IndexResult
deleteSource(sourceRef) -> DeleteResult
rebuild(indexVersion) -> RebuildJobRef
```

### RetrievalPort

```text
retrieve(query, filters, limit) -> RetrievedChunk[]
```

每个 `RetrievedChunk` 必须包含 `chunk_id`、`source_ref`、来源时间、片段内容和各阶段得分。调用方不能把检索排序分数解释为事实置信度。
查询改写后若不含任何可检索词元，必须直接返回空集合，不得向 EmbeddingPort 发送空文本。

### ReminderPort

```text
schedule(entryId, entryVersion, dueAt, idempotencyKey) -> ReminderRef
cancelForEntry(entryId, expectedVersion) -> CancelResult
leaseDue(now, workerId, limit, leaseDuration) -> ReminderLease[]
markSent(leaseId, deliveryRef)
markFailed(leaseId, failureClass, nextAttemptAt?)
```

Reminder 到期领取使用数据库 `FOR UPDATE SKIP LOCKED`，查询与写入租约在单事务内完成；过期租约可
由新 Worker 恢复。Reminder 必须匹配 `AgendaEntry` 的当前活动版本，否则进入
`StaleAgendaVersion` 死信且不得发送。QQ/Provider 失败采用有限指数退避，达到上限进入死信。

`cancelForEntry` 必须能以版本和租约 fencing 幂等取消 `SCHEDULED`、`RETRY_WAIT` 或正在执行完成
门禁的 `LEASED` 提醒。若 Task Projection 已核验 To Do 完成，Notifications 只有在 Actions 成功
完成 Agenda 并取消当前提醒后才记录 `SUPPRESSED_COMPLETED`；不得再调用 `markSent`。

### RetentionPort

```text
recordDeletion(subjectRef, requestedAt, purgeBy) -> TombstoneRef
findDueSubjects(now, limit) -> RetentionSubject[]
recordModulePurge(tombstoneId, moduleName, result)
completeDeletion(tombstoneId)
```

每个保存受保留策略约束数据的模块必须实现自己的 `PurgePort`：

```text
purgeSubject(subjectRef, tombstoneId) -> PurgeResult
purgeExpired(cutoff, policyVersion, limit) -> PurgeBatchResult
```

Data Lifecycle 只能调用公开清理端口，禁止直接访问其他模块 Repository 或数据表。清理操作按 `tombstoneId` 幂等。

## 3. SourceEnvelope

所有入口先转换为统一信封：

```json
{
  "source_type": "QQ_DIRECT | QQ_FORWARD | MICROSOFT_MAIL | QQ_MAIL | ...",
  "ingress_type": "DIRECT | FORWARDED | SYNC | WEBHOOK | UPLOAD",
  "external_id": "provider-stable-id",
  "thread_id": "optional-thread-id",
  "occurred_at": "RFC3339 timestamp",
  "received_at": "RFC3339 timestamp",
  "sender": { "provider_id": "...", "display": "..." },
  "content_ref": "opaque-content-reference",
  "content_hash": "sha256:...",
  "trust_level": "T1 | T2 | T3",
  "metadata": {}
}
```

`metadata` 必须有白名单 schema，不得成为随意穿透 Provider DTO 的通道。

## 4. 错误分类

| 分类 | 处理方式 |
|---|---|
| Validation | 不重试，向用户给出可修正信息 |
| Authentication | 尝试一次刷新，失败后要求重新授权 |
| Authorization | 不重试，说明权限或组织策略问题 |
| RateLimit | 按 Provider 提示和退避重试 |
| TransientProvider | 有上限重试，之后进入死信 |
| PermanentProvider | 不重试，人工或用户处理 |
| Conflict | 重新读取状态后重新生成 Proposal |
| SecurityPolicy | 阻止操作并写安全审计 |

对用户的错误消息不得直接透传 Provider 异常或内部堆栈。

## 5. 版本与兼容

- 公共 HTTP API 使用 `/api/v1` 前缀（健康检查和 OAuth 回调除外）。
- 领域事件必须包含 `event_type` 和 `schema_version`。
- 契约字段只做向后兼容新增；删除或改义需要新版本。
- Provider API 版本仅存在于适配器内部。

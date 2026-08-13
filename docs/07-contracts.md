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
GET  /oauth/microsoft/start
GET  /oauth/microsoft/callback
POST /api/v1/oauth/microsoft/disconnect
GET  /api/v1/connections/microsoft/status
```

约束：

- `owner-start` 只接受 Windows 本机回环访问，生成的短期签名会话只放在
  `no-store` 页面中的隐藏 POST 字段；表单只 POST 到本机同源端点。页面使用一次性 CSP
  nonce 脚本自动提交，按钮作为无脚本回退；签名不进入 URL、访问日志或跨站 Referer。
- `owner/session` 只通过本机回环 POST 接收短期签名会话，验证后写入
  `HttpOnly`、`SameSite=Lax` Cookie，再跳转到 `start`；Lax 用于让 Microsoft 的顶层 GET
  回调携带短期 OAuth 会话，不能放宽为跨站子请求。
- `start` 必须绑定当前已认证所有者；不得接受 URL 查询参数中的会话或 token。
- `owner/session`、`start`、`callback`、连接状态和断开接口均拒绝非回环 Host。
- `callback` 不把授权码、token 或 Provider 原始错误展示给用户。
- `disconnect` 使用 CSRF 防护和明确确认。
- 状态接口只返回能力、账号掩码、同步时间和健康状态。

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
GET  /api/v1/connections/qq-mail/status
POST /api/v1/connections/qq-mail/disconnect
```

- 全部接口只接受回环 Host 和已签名所有者会话；写接口要求同源 CSRF。
- connect body 只接收完整 QQ 邮箱地址与秘密授权码，不接收 QQ 登录密码、Host、Port 或 TLS
  开关。授权码不得进入 URL、响应、日志、异常或 Job payload。
- connect 可用于首次连接及 `REAUTH_REQUIRED`/`DISCONNECTED` 后重新认证；活动连接重复提交被拒绝。
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
classify(normalizedContent, trustContext) -> Classification
extractEvent(normalizedContent, temporalContext) -> EventCandidate
extractTask(normalizedContent, temporalContext) -> TaskCandidate
```

输出必须包含置信度、依据字段和显式假设。

阶段 4 的实现使用 DeepSeek JSON Output，但 Provider JSON 必须先转换并经过本地 Pydantic
schema（拒绝额外字段）、时间/时区、证据、来源和信任校验。`MEDIUM` 优先级只在 Adapter
后的本地 schema 中白名单归一为领域 `NORMAL`，其他未知枚举拒绝。模型只返回候选，不存在
Action、Agenda 或 Notification 工具。

相对日期使用 Inbox 来源的 `occurred_at` 与所有者时区解释，不使用 Worker 当前墙上时间。
Event 缺少持续时间时使用强类型配置的默认值并追加显式假设；Task deadline 不得填入 Event
的开始/结束字段。置信度低于 0.75、时间含糊、schema/证据非法或模型不可用时进入
`NEEDS_REVIEW`，不会静默形成候选。

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

只有 Actions 模块可以调用 AgendaCommandPort。

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

# 领域模型

## 1. 核心聚合

### UserAccount

代表唯一项目所有者，不等同于 QQ 或 Microsoft 账号。部署时只能存在一条有效记录。

关键字段：

- `user_id`
- `timezone`
- `locale`
- `working_hours`
- `default_event_duration`
- `created_at`

### ExternalConnection

代表用户授权的外部账号。

关键字段：

- `connection_id`
- `user_id`
- `provider`
- `provider_account_id`
- `capabilities`
- `credential_ref`
- `status`
- `last_synced_at`

`credential_ref` 只是凭据存储引用，领域对象不得包含明文 token 或授权码。

### InboxItem

保存外部输入的不可变信封。

关键字段：

- `inbox_item_id`
- `user_id`
- `source_type`
- `ingress_type`
- `trust_level`
- `external_id`
- `thread_id`
- `sender`
- `occurred_at`
- `received_at`
- `raw_content_ref`
- `content_hash`
- `status`

### EventCandidate

从内容中识别出的固定事件候选。

- `title`
- `starts_at`
- `ends_at`
- `timezone`
- `location`
- `participants`
- `confidence`
- `assumptions`
- `source_refs`

### TaskCandidate

从内容中识别出的任务候选。

- `title`
- `deadline`
- `estimated_duration`
- `priority`
- `allowed_windows`
- `confidence`
- `assumptions`
- `source_refs`

### SchedulingProposal

代表尚未执行的建议。

- `proposal_id`
- `version`
- `subject_ref`
- `recommended_slot`
- `alternative_slots`
- `conflicts`
- `rationale`
- `expires_at`
- `status`

### ActionRequest

代表经过策略允许、准备对外执行的副作用。

- `action_id`
- `proposal_id`
- `action_type`
- `idempotency_key`
- `requested_by`
- `confirmed_at`
- `status`
- `resource_id`

### AgendaEntry

项目内部日程的权威记录，不由 RAG 或 LangGraph checkpoint 替代。

- `agenda_entry_id`
- `kind`（EVENT/TASK_BLOCK）
- `title`
- `starts_at`
- `ends_at`
- `timezone`
- `status`
- `source_refs`
- `proposal_id`
- `version`

### Reminder

- `reminder_id`
- `agenda_entry_id`
- `agenda_entry_version`
- `due_at`
- `status`
- `attempt_count`
- `lease_until`
- `idempotency_key`

### KnowledgeChunk

RAG 检索单元，仅保存知识索引，不保存日程状态。

- `chunk_id`
- `source_ref`
- `source_version`
- `content`
- `content_hash`
- `metadata`
- `embedding_model`
- `embedding_dimensions`
- `embedding`
- `indexed_at`

## 2. 状态机

### InboxItem

```text
RECEIVED → NORMALIZED → UNDERSTOOD → PROPOSED → COMPLETED
    └──────────────→ IGNORED
    └──────────────→ NEEDS_REVIEW
    └──────────────→ FAILED_RETRYABLE → RECEIVED
    └──────────────→ FAILED_FINAL
```

### SchedulingProposal

```text
DRAFT → PENDING_CONFIRMATION → CONFIRMED → EXECUTED
                         ├────→ REJECTED
                         ├────→ EXPIRED
                         └────→ SUPERSEDED
```

### ExternalConnection

```text
PENDING → ACTIVE → DEGRADED → REAUTH_REQUIRED
              └────────────→ DISCONNECTED
```

### Reminder

```text
SCHEDULED → LEASED → SENT
                 ├→ RETRY_WAIT → SCHEDULED
                 ├→ DEAD_LETTER
                 └→ CANCELLED
```

## 3. 领域不变量

1. Event 必须有明确的 `starts_at`、`ends_at` 和时区，且结束晚于开始。
2. Task 的截止时间不等于执行时间；没有排程结果时不得伪装成 Event。
3. Proposal 每次修改必须增加版本号，确认只能针对最新有效版本。
4. 外部内容不能把 `trust_level` 从 T2/T3 提升到 T1。
5. 未确认的 Proposal 不得生成可执行 ActionRequest。
6. 每个 ActionRequest 必须有稳定的幂等键。
7. 同一个 Provider 的同一 `external_id` 对同一连接只能生成一个 InboxItem。
8. 所有时间在持久化时必须包含 UTC 值和原始时区。
9. 凭据不进入领域对象、领域事件或审计载荷。
10. 删除连接时，凭据删除必须先于连接状态变为 `DISCONNECTED`。
11. 部署中只能存在一个有效 UserAccount，QQ 命令身份必须匹配配置的所有者身份。
12. AgendaEntry 是日程事实源；RAG chunk、向量和 LangGraph checkpoint 都不得推导性覆盖它。
13. Reminder 必须绑定 AgendaEntry 的具体版本；条目修改或取消后旧提醒不得发送。
14. 同一向量索引版本内的 embedding 模型、模型摘要和维度必须一致。

## 4. 领域事件

- `InboxItemReceived`
- `ContentNormalized`
- `CandidateExtracted`
- `ClarificationRequested`
- `ProposalCreated`
- `ProposalConfirmed`
- `ProposalRejected`
- `ActionRequested`
- `ActionSucceeded`
- `ActionFailed`
- `AgendaEntryCreated`
- `AgendaEntryChanged`
- `ReminderDue`
- `ReminderSent`
- `KnowledgeSourceChanged`
- `KnowledgeChunkIndexed`
- `ConnectionReauthRequired`
- `ConnectionDisconnected`

领域事件只能携带标识和最小业务数据，不携带完整邮件正文、附件或 token。

# Microsoft To Do 投影与提醒门禁模块设计

## 1. 设计目标

本设计落实 [25-microsoft-todo-requirements.md](25-microsoft-todo-requirements.md)，在不把 Microsoft
语义渗透到 Agenda、Reminders 或 Notifications 的前提下，提供：

1. Agenda 到外部任务视图的可靠、幂等投影。
2. Microsoft To Do 完成状态到 Agenda 的受控完成回写。
3. QQ 提醒发送前的短时、可降级完成门禁。

新增 `Task Projection` 模块承载 Provider 中立的投影业务。Microsoft Graph SDK、URL、DTO、etag、
delta link 和 OAuth token 仍只能留在 Adapter、Connections、Credential Vault 与该模块自己的
Infrastructure 边界。

## 2. 模块职责拆分

| 模块 | 本功能中的职责 | 明确不负责 |
|---|---|---|
| Agenda | 保存权威日程及当前版本，发布条目变化事件 | To Do ID、Graph 调用、投影重试 |
| Actions | 幂等执行 `COMPLETE_AGENDA`，更新 Agenda、取消提醒并审计 | 轮询 To Do、决定提醒是否投递 |
| Reminders | 保存计划、租约和发送状态，允许 Actions 安全取消已租约提醒 | 读取 Microsoft、解释完成状态 |
| Notifications | 编排提醒发送；发送前调用完成门禁并记录投递或抑制结果 | 直接访问 Graph、映射表或修改 Agenda |
| Task Projection | 映射、投影状态、同步游标、完成核验、对账和门禁决策 | 成为日程事实源、直接发送 QQ |
| Connections | 校验连接所有者、状态和 `TASKS_READ_WRITE` 能力，提供短期访问授权 | 保存投影映射、解释任务状态 |
| Credential Vault | 保存 token 并提供短生命周期凭据句柄 | Graph 业务调用、完成决策 |
| Microsoft Graph Adapter | 把统一任务端口转换为 Graph 请求和 Provider DTO | 跨模块编排、直接写数据库 |
| Audit | 追加投影失败、完成证据和 Action 结果 | 驱动业务状态 |

## 3. 依赖方向

```text
Agenda ──Outbox/Event──► Task Projection ──TaskProviderPort──► Microsoft Graph Adapter
                              │                    │
                              │                    └──受控授权──► Connections / Vault
                              │
                              ├──AgendaQueryPort──► Agenda
                              └──CalendarActionPort──► Actions ─► Agenda + Reminders + Audit

Reminder Worker ─► Notifications ─► ReminderCompletionGatePort ─► Task Projection
                         │
                         └──只有 SEND 决策──► QQ Adapter
```

依赖规则：

- Agenda 和 Actions 不依赖 Task Projection。
- Notifications 只依赖 `ReminderCompletionGatePort`，不知道 Microsoft、列表或任务 ID。
- Task Projection 只能通过公开的 `AgendaQueryPort` 和 `CalendarActionPort` 读取、完成日程。
- Microsoft Graph Adapter 实现 `TaskProviderPort`，Provider DTO 必须在 Adapter 内转换并销毁。
- Bootstrap 负责把 Connections、Vault、Graph Adapter 和 Task Projection 装配起来；业务模块不得
  通过 Service Locator 获取 token 或 SDK。
- 所有跨模块写入由各模块自己的事务完成，并以 Outbox/Job 补偿，不建立跨模块事务。

## 4. Task Projection 内部结构

```text
src/modules/task_projection/
  contracts/        # ReminderCompletionGatePort、公开视图和结果枚举
  domain/           # 映射、投影状态、完成证据和状态转换
  application/      # 投影、对账、完成门禁和列表解析用例
  infrastructure/   # 本模块 Repository、Outbox consumer、Job handler
```

Microsoft 实现继续位于：

```text
src/adapters/outbound/microsoft_graph/
  todo_client.py    # TaskProviderPort 实现和 DTO 转换
```

不得把 `todo_client.py`、Graph DTO 或 Microsoft 枚举放进 `task_projection/domain` 或跨模块契约。

## 5. 数据所有权

Task Projection 独占以下逻辑数据；其他模块不得直接查询或 JOIN：

### TaskProjectionMapping

| 字段 | 含义 |
|---|---|
| `mapping_id` | 内部映射标识 |
| `user_id` | 所有者引用 |
| `agenda_entry_id` | Agenda 条目引用 |
| `agenda_entry_version` | 已投影或已核验的 Agenda 版本 |
| `connection_id` | Microsoft Connection 引用 |
| `provider` | 当前为 `MICROSOFT_TODO` |
| `provider_list_ref` | 加密或受控保存的外部列表引用 |
| `provider_task_ref` | 加密或受控保存的外部任务引用 |
| `status` | 投影状态 |
| `provider_revision` | 不透明的 etag/change key |
| `last_projected_at` | 最近成功投影时间 |
| `last_checked_at` | 最近核验完成状态时间 |
| `last_observed_completion` | 最近观察摘要，不是 Agenda 事实 |
| `version` | 映射乐观锁版本 |

约束：

- `(provider, connection_id, agenda_entry_id)` 唯一。
- `(provider, connection_id, provider_task_ref)` 唯一。
- Provider 引用不得出现在用户消息或普通结构化日志中。
- `last_observed_completion` 只用于诊断和后台对账；发送门禁必须强读取，不能用其直接抑制 QQ。

### TaskProjectionCursor

| 字段 | 含义 |
|---|---|
| `connection_id` | 连接引用 |
| `provider_list_ref` | 受管列表引用 |
| `opaque_cursor` | 不透明 delta link 或游标 |
| `updated_at` | 最近推进时间 |
| `version` | 乐观锁版本 |

游标只在成功处理整页后推进；失效时允许重建，但不得绕过映射唯一约束。

### 投影状态

```text
PENDING → ACTIVE → RETRY_WAIT → ACTIVE
             ├──→ DETACHED → PENDING
             ├──→ CLOSED
             └──→ FAILED_FINAL
```

- `DETACHED` 表示外部任务消失、被移动或不再位于受管列表，不等于完成。
- `CLOSED` 表示 Agenda 已完成或取消且外部状态已收敛。
- `FAILED_FINAL` 只终止当前投影任务，不改变 Agenda 状态或 Reminder 决策。

## 6. 公开契约

### ReminderCompletionGatePort

```text
evaluateBeforeDelivery(
  userId,
  agendaEntryId,
  expectedAgendaVersion,
  reminderOccurrence,
  observedAt,
) -> ReminderCompletionDecision
```

`ReminderCompletionDecision` 只允许：

- `SUPPRESS_COMPLETED`：Provider 已核验完成，且 Actions 已成功完成 Agenda 或确认其已完成。
- `SEND_NOT_COMPLETED`：Provider 已核验为未完成。
- `SEND_UNMAPPED`：没有可用映射。
- `SEND_UNAVAILABLE`：超时、失权、限流、网络或 Provider 故障。
- `SEND_STALE`：映射或 Agenda 版本不匹配。

除 `SUPPRESS_COMPLETED` 外都必须继续 QQ 发送。返回值包含内部原因码和审计引用，不包含 Provider
任务 ID、token 或原始异常。

### TaskProjectionCommandPort

```text
projectAgendaEntry(entryId, expectedVersion, idempotencyKey) -> ProjectionResult
closeProjection(entryId, expectedVersion, reason, idempotencyKey) -> ProjectionResult
reconcileConnection(connectionId, cursor?) -> ReconciliationResult
```

Agenda 事件消费者和 Worker 只能调用该端口，不导入 Repository 或 Graph Adapter。

### TaskProviderPort

```text
resolveManagedList(accessGrant, normalizedName) -> ManagedTaskList
upsertTask(accessGrant, listRef, taskDraft, providerTaskRef?) -> ExternalTaskView
getTask(accessGrant, listRef, taskRef) -> ExternalTaskView
completeTask(accessGrant, listRef, taskRef, expectedRevision?) -> ExternalTaskView
deleteTask(accessGrant, listRef, taskRef, expectedRevision?) -> ExternalTaskResult
fetchDelta(accessGrant, listRef, opaqueCursor?) -> ExternalTaskDeltaPage
```

`ExternalTaskView` 是 Provider 中立 DTO，只包含投影所需的标题、时间、完成布尔值、不透明引用和
版本摘要。Graph SDK 对象、响应头和错误对象不能越过 Adapter。

### ConnectionTaskAccessPort

```text
acquireTaskAccess(userId, connectionId, requiredCapability) -> TaskAccessGrant
```

`TaskAccessGrant` 是短生命周期、不可日志化、不可持久化的句柄。Connections 校验连接归属、状态与
能力，Vault 负责凭据；Task Projection 不读取凭据表或环境变量。

### CalendarActionPort 扩展

```text
completeAgenda(
  actionContext,
  entryId,
  expectedVersion,
  idempotencyKey,
) -> CompleteAgendaResult
```

To Do 完成使用稳定键：

```text
todo-complete:{connection_id}:{mapping_id}:{provider_revision}
```

键的明文只存在于内部存储，不进入 QQ 或普通日志。重复 delta、重复门禁和 QQ 按钮竞态必须收敛
到同一 Agenda 最终状态。

## 7. 关键流程

### 7.1 Agenda 投影

```text
Agenda 事务提交 + Outbox
→ Task Projection 幂等消费 AgendaEntryCreated/Changed
→ 查询 Agenda 当前版本
→ 取得 TASKS_READ_WRITE 短期授权
→ 解析或读取“小智建议”列表映射
→ Graph Adapter upsert
→ Task Projection 自己的事务保存映射和投影结果
```

任何外部失败只更新投影状态并安排有限重试，不回滚 Agenda。

### 7.2 To Do 完成后台对账

```text
周期 Job / webhook 变化提示
→ fetchDelta
→ 通过 connection + list + task 映射定位 Agenda
→ 对 completed 任务执行一次强读取
→ 校验所有者、列表、映射和 Agenda 当前版本
→ Actions.completeAgenda(稳定幂等键)
→ 保存观察结果并推进游标
```

外部删除、移动、重新打开或普通字段更新不调用 Actions。

### 7.3 QQ 提醒发送门禁

```text
Reminders 租约领取到期项
→ Notifications 校验 Agenda 仍 ACTIVE 且版本一致
→ ReminderCompletionGatePort.evaluateBeforeDelivery
   ├─ SUPPRESS_COMPLETED
   │   └─ Actions 已完成 Agenda、取消提醒 → 记录 SUPPRESSED_COMPLETED，不发 QQ
   └─ 任一 SEND_*
       └─ 调用 QQ Adapter → 按既有契约记录 SENT/失败/AMBIGUOUS
```

门禁只在 QQ Provider 调用前执行，默认总预算 3 秒且关键路径不做长重试。门禁确认完成时，Actions
需要能以版本和租约 fencing 安全取消当前 `LEASED` Reminder；Notifications 不把它再标记为已发送，
只保存一条抑制投递结果。若 Actions 没有成功或不能确认 Agenda 已完成，门禁不得返回
`SUPPRESS_COMPLETED`。

## 8. 一致性与竞态处理

| 竞态 | 收敛方式 |
|---|---|
| QQ 完成按钮与 To Do 完成同时发生 | Actions 幂等键和 Agenda 版本门禁；后到请求读取已完成结果 |
| 后台 delta 与发送前强读取同时发生 | 两者可并发，只有 Actions 能写 Agenda；门禁以 Actions 最终结果决定抑制 |
| 强读取后用户才勾选完成 | 本次可能发送一次 QQ；后台对账随后完成 Agenda |
| Agenda 更新与旧映射读取同时发生 | `expectedAgendaVersion` 不符返回 `SEND_STALE`，不使用旧证据完成 |
| Actions 完成时 Reminder 已租约 | Reminders 以 fencing 取消该租约；Worker 看到取消结果后不发送 |
| Graph 已写成功、本地映射事务前崩溃 | 以 Agenda 稳定标记搜索/对账并恢复映射，不盲目创建第二条 |
| QQ 已接收、本地回执前崩溃 | 保留既有 `AMBIGUOUS` 语义，不宣称跨 Provider exactly-once |

## 9. Job 与失败策略

| Job | 触发 | 幂等范围 | 失败策略 |
|---|---|---|---|
| `task-projection-upsert` | Agenda 创建/更新 Outbox | Agenda ID + 版本 | 有限退避，终态告警 |
| `task-projection-close` | Agenda 完成/取消 Outbox | Agenda ID + 版本 + 原因 | 有限退避，后台对账 |
| `task-projection-delta` | 每分钟或变化提示 | Connection + 游标页 | 页成功后推进游标 |
| `task-projection-reconcile` | 游标失效、重启、人工修复 | Connection + 批次 | 有界扫描、唯一约束去重 |

认证或授权错误通知 Connections 进入相应健康状态，但不得删除映射或取消内部提醒。Rate limit 遵循
Provider 提示；临时网络错误有限退避；永久列表歧义和缺失进入可诊断状态，等待用户修正。

## 10. 实施拆分

### 17A：需求与边界冻结

- 本需求文档、模块设计、ADR、公共契约和交付计划一致。
- 明确“未知则发 QQ”、不反向同步编辑和 To Do 原生提醒关闭。

### 17B：Task Projection 骨架与列表解析

- 新模块、迁移、Repository、公开契约和架构测试。
- Connection task capability grant 与 Graph TaskProvider Adapter。
- 精确解析“小智建议”，处理零个或多个同名列表。

### 17C：Agenda 单向投影

- 创建/修改/完成/取消 Outbox 消费。
- ACTIVE 历史条目补投影。
- 幂等 upsert、崩溃恢复、重试、死信和对账。

### 17D：完成回写与 QQ 门禁

- delta 完成同步和发送前强读取。
- Actions `COMPLETE_AGENDA` 幂等回写。
- 已租约 Reminder 安全取消和 Notifications 抑制记录。
- 未映射、超时、失权、删除、版本过期一律继续发送 QQ。

### 17E：沙箱、生产启用与回滚

- 隔离 PostgreSQL 集成测试和 Microsoft/QQ 真实沙箱。
- 生产备份、迁移、只对所有者连接启用、活动 Agenda 分批补投影。
- 核对 Agenda/Reminder 摘要不变；可独立停用 Task Projection 而不影响 QQ。

## 11. 测试门禁

- Domain：映射状态机、唯一约束、版本校验、删除不等于完成。
- Contract：Graph DTO 不泄漏、访问句柄不可序列化、门禁结果穷举。
- Application：所有门禁结果矩阵、Actions 失败不得抑制、3 秒超时降级发送。
- Integration：Outbox 重放、delta 游标、已租约取消、Worker 重启和数据库迁移往返。
- Concurrency：QQ 按钮、delta、强读取和 Agenda 更新竞态只产生一个完成结果。
- Security：非所有者连接、错误列表、伪造任务 ID、失权、日志与异常脱敏。
- Sandbox：真实 To Do 创建/更新/完成、QQ 抑制与未完成正常提醒。
- Regression：Agenda 清单只显示 ACTIVE、结束时间不自动完成、QQ 卡片按钮流程和原有邮件同步。

## 12. 可运维性与回滚

- 指标至少包括投影积压、投影成功/失败、delta 延迟、门禁结果分类、门禁耗时、抑制数量和因未知
  继续发送数量；标签不得使用 Provider 任务 ID。
- 关闭功能开关后停止新的 Graph 调用，Agenda、Actions、Reminders 和 QQ 仍按原路径工作。
- 回滚应用版本前不得删除投影表；旧版本可忽略这些表。数据库迁移必须支持往返和空库直升 head。
- 断开 Microsoft Connection 时先停止相关 Job 和访问，再按数据保留规则关闭映射；不得修改 Agenda。

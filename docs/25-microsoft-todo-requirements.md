# Microsoft To Do 视图与完成门禁需求

## 1. 目标

Microsoft To Do 仅作为内部 Agenda 的外部视图和用户勾选完成的入口。项目内部 Agenda 继续保存
日程事实、版本、来源和状态；Reminders 继续保存提醒计划；QQ 继续是唯一主动提醒出口。

系统把活动日程投影到 Microsoft To Do 的“小智建议”列表。提醒到期时，系统在决定是否发送 QQ
消息前检查对应 To Do 任务：只有从 Microsoft 重新读取并确认任务已完成，才完成内部日程并抑制
该次 QQ 提醒。

## 2. 产品边界

### 2.1 To Do 负责

- 展示 Agenda 中仍有效的 Event 和 Task Block。
- 展示标题、开始时间、结束或截止时间，以及不含内部标识的简要说明。
- 接收用户对任务的“完成”勾选。
- 为跨设备查看和完成提供便利。

### 2.2 To Do 不负责

- 不替代 Agenda、Actions、Reminders、Notifications 或 Audit。
- 不计算忙闲、冲突、排程建议或日程版本。
- 不在 Microsoft 侧设置提醒；主动提醒仍只由 QQ 发送。
- 不把 Microsoft 侧的标题、时间、正文、列表移动或删除反向写入 Agenda。
- 不因任务到期、日程结束、任务消失或读取失败而推断日程已完成。
- 不把已完成任务重新打开解释为恢复内部日程。

## 3. 权威性和同步方向

```text
Agenda 标题/时间/状态 ──单向投影──► Microsoft To Do“小智建议”

Microsoft To Do completed ──经核验和 Actions 门禁──► Agenda COMPLETED
```

同步不是一般意义上的双向同步。允许从 To Do 回流的唯一业务信号是：受管列表中、与当前所有者
Agenda 条目存在有效映射的任务，其最新 Provider 状态明确为 `completed`。

Agenda 的创建和修改异步投影到 To Do；Agenda 完成时把映射任务标为完成；Agenda 取消时移除或
关闭外部投影。外部投影失败不得回滚 Agenda，也不得阻断日程查询、QQ 按钮或 QQ 提醒。

## 4. 受管列表

- 首个且唯一自动管理的列表显示名称为“小智建议”。
- 系统通过 Microsoft Graph 枚举列表并解析其 Provider ID，不接受模型生成的 ID。
- 未找到列表时停止投影并报告设置问题；找到多个同名列表时停止并报告歧义，不得猜选。
- 列表 ID、任务 ID 和同步游标属于内部映射信息，不出现在 QQ 文本、To Do 正文或普通日志中。
- 用户可以在 Microsoft To Do 中查看和勾选任务，但不应依赖该列表的原生提醒。

## 5. 投影规则

### 5.1 创建和更新

- 每个 Agenda 条目最多有一个当前有效的 Microsoft To Do 投影。
- Event 和 Task Block 都可以投影；两者在 To Do 中都是任务，只是视图，不改变内部类型。
- 标题、开始时间、结束或截止时间以 Agenda 当前版本为准。
- To Do 任务的提醒字段保持关闭，避免与 QQ 重复提醒。
- Agenda 版本变化触发幂等更新；重放相同版本不会创建重复任务。
- 用户在 To Do 中修改标题、时间或正文不改变 Agenda；后续对账可用 Agenda 值覆盖这些字段。

### 5.2 完成和取消

- QQ 按钮或直接命令完成 Agenda 后，系统异步把 To Do 任务标为完成。
- 从 To Do 核验到完成后，系统必须先通过 Actions 的幂等 `COMPLETE_AGENDA` 操作把 Agenda
  变为 `COMPLETED`，再决定不发送 QQ 提醒。
- Agenda 取消后，外部投影应从活动视图移除；具体采用删除还是关闭由适配器能力决定，但不能
  把取消伪装成用户完成。
- Agenda 到达 `ends_at` 不会自动完成；To Do 任务到期也不会自动完成。

### 5.3 既有数据

- 首次启用时，幂等补投影当前 `ACTIVE` Agenda 条目。
- 已经 `COMPLETED` 或 `CANCELLED` 且从未投影的历史条目不补建任务。
- 已存在映射的完成或取消条目需要收敛外部状态，避免继续出现在活动视图。

## 6. QQ 提醒完成门禁

提醒 Worker 在取得到期提醒租约并确认 Agenda 版本仍有效后、调用 QQ Provider 前执行一次有界的
完成门禁。门禁必须读取映射任务的最新 Provider 状态，不能只相信 webhook、delta 缓存或本地
上一次观察。

| 门禁结果 | 内部动作 | QQ 决策 |
|---|---|---|
| 已核验 `completed` | 经 Actions 完成 Agenda，取消旧提醒并审计 | 不发送 |
| 已核验未完成 | 不改变 Agenda | 发送 |
| 没有映射 | 不改变 Agenda，并安排补投影 | 发送 |
| 任务被删除、移动或无法定位 | 不视为完成，标记映射待修复 | 发送 |
| 授权失效、限流、网络错误或超时 | 不改变 Agenda，异步重试同步 | 发送 |
| 映射或 Agenda 版本过期 | 不使用旧观察改变状态，安排对账 | 发送 |

这里采用“提醒不中断”的容错策略：未知结果默认发送 QQ。该策略宁可在极端竞态或 Provider
故障时多发一次提醒，也不能把未知状态错误解释为完成而漏发提醒。

门禁调用使用可配置的短超时，默认总预算 3 秒；提醒关键路径内不做长退避重试。后台增量同步和
对账负责随后恢复。若用户恰好在完成门禁读取之后、QQ Provider 接收之前勾选 To Do，仍可能收到
一次提醒；跨 Provider 无法承诺严格的 exactly-once。

## 7. 后台同步和补偿

- Agenda 创建、修改、完成和取消通过持久化事件或 Outbox 驱动投影，不依赖进程内临时回调。
- Microsoft 变化通知只用于提示“可能发生变化”；任何完成写回都必须重新读取 Provider 状态。
- 使用 delta 或等价游标周期性同步完成状态，并至少每分钟启动一次增量检查。
- 游标失效时执行有界重建；重建仍按映射和幂等键去重。
- 发送前的强读取与后台增量同步可以同时发生，但 Actions 幂等键保证只完成一次。
- Provider 不可用时，待投影和待对账工作进入有限重试或死信，不影响 Agenda 与 QQ 的核心能力。

## 8. 安全和隐私

- 只使用所有者当前有效 Microsoft Connection 的委托 `Tasks.ReadWrite` 权限。
- 只有目标连接、受管列表和有效映射三者一致的任务完成状态可以形成完成证据。
- webhook 载荷、模型输出和用户提供的 Provider ID 都不能直接改变 Agenda。
- token、授权码、完整账号、列表 ID、任务 ID、delta link 和原始 Provider 异常不得出现在用户回复
  或普通日志中。
- 完成回写保存最小审计证据：连接引用、映射引用、观察时间、Provider 状态摘要和 Actions 结果；
  不保存 token 或完整 Provider DTO。

## 9. 用户可见行为

- 授权并解析到“小智建议”后，现有活动日程会逐步出现在该列表。
- 用户在 To Do 勾选完成后，系统最终把内部日程标为完成；若恰逢提醒发送前，QQ 提醒会被抑制。
- 用户未勾选完成，也未通过 QQ 完成或取消时，日程经过结束时间仍保持 `ACTIVE`。
- 用户删除 To Do 任务不会删除、取消或完成 Agenda；相应 QQ 提醒仍会发送。
- Microsoft 暂时不可用时，QQ Bot 应继续列出权威日程并按原计划提醒，同时以脱敏方式提示连接
  需要处理或同步正在重试。

## 10. 验收场景

1. 创建一个 Agenda 条目后，“小智建议”中只产生一条任务；重复消费事件仍只有一条。
2. 修改 Agenda 时间后更新同一 To Do 任务，不创建第二条，内部版本保持权威。
3. 在提醒前勾选 To Do 完成，门禁重新读取到 `completed`，Actions 只执行一次，Agenda 变为
   `COMPLETED`，旧提醒取消，QQ 不发送。
4. To Do 未完成时，QQ 提醒正常发送，Agenda 仍为 `ACTIVE`。
5. Microsoft 超时、限流、失权或任务被删除时，QQ 提醒仍发送，Agenda 不被错误完成。
6. 用户只修改 To Do 标题、时间或正文时，Agenda 不变化；对账后视图恢复为 Agenda 当前值。
7. 用户未进行任何完成操作时，即使超过 `ends_at`，Agenda 仍为 `ACTIVE`。
8. QQ 完成按钮与 To Do 完成同步竞态时，只生成一条成功的完成 Action 和一致的最终状态。
9. 连接重新授权、Worker 重启、delta 重放和游标重建后，不产生重复任务或重复完成动作。
10. To Do 任务不启用 Microsoft 原生提醒，用户只收到 QQ 主动提醒。

## 11. 不在本阶段范围

- 从 To Do 创建新 Agenda。
- 从 To Do 修改 Agenda 标题、时间、正文、提醒时间或类型。
- To Do 删除、移动列表、重新打开任务触发 Agenda 变更。
- Microsoft Planner、Outlook Calendar 或其他任务平台。
- 使用 To Do 代替内部数据库、Reminder 租约或 Audit。

# Microsoft To Do 17D 本地验证报告

## 1. 范围与结论

本报告记录阶段 17D“完成回写与 QQ 提醒门禁”的本地完成证据。内部 Agenda 仍是唯一日程事实源；
Microsoft To Do 只提供外部视图和 `completed` 信号，标题、时间、删除、移动和重新打开均不反向写入。

结论：17D 本地开发与 PostgreSQL 门禁通过。真实 Microsoft 任务勾选、真实 QQ 抑制、生产备份与启用
属于 17E，本报告不宣称这些外部门禁或生产发布已经完成。

## 2. 完成同步与保守门禁

- Worker 每分钟为每个 READY “小智建议”目标投递唯一 delta Job；游标按连接和列表持久化，只有一页
  处理完成后推进。游标失效时删除旧游标，后续周期重新建立基线。
- delta 只把 `completed` 当作候选信号，随后仍按映射的 connection、受管 list 和 task ref 强读取；
  删除、移动、未完成和其他字段变化不会完成 Agenda。
- QQ Reminder 在调用 QQ Provider 前执行同一强读取，整个门禁默认最多 3 秒且不做长退避。授权失效、
  限流、网络错误、超时、任务缺失、无映射、目标或 Agenda 版本不符一律降级为继续发送。
- 只有强读取明确为完成、当前映射和 Agenda 版本仍有效、Actions 完成操作成功或确认已收敛时，门禁
  才返回抑制。发送前读取之后才发生的勾选仍可能多发一次，系统不承诺跨 Provider exactly-once。

## 3. Actions、租约与投递记录

- To Do 完成通过公开 Actions 完成端口执行 `COMPLETE_AGENDA`；稳定幂等键只在内部保存摘要，不进入
  QQ 文本或普通日志。Agenda 已被 QQ 按钮并发完成时，Actions 会确认终态并再次收敛旧提醒取消。
- `cancel_for_entry` 可以取消当前 `LEASED` Reminder；门禁返回抑制后 Worker 不再调用 `mark_sent`。
  若 QQ 按钮恰好在发送结算阶段取消租约，Worker 识别租约丢失，不崩溃也不把已取消项改回 SENT。
- Notifications 使用独立唯一键记录提醒抑制；Worker 重试时先读取既有投递或抑制记录，避免重复 QQ
  消息或重复抑制记录。
- 日程超过 `ends_at` 仍不会自动完成；只有 QQ 完成动作或经核验的 To Do 完成动作可以改变状态。

## 4. 自动化证据

- Ruff：完整 `src`、`tests` 与 `alembic` 检查通过。
- strict mypy：391 个 source files 无错误。
- 非 integration、非 sandbox 回归：621 passed，52 deselected。
- PostgreSQL integration：42 passed，631 deselected。
- Alembic：`0029_task_projection → 0030_todo_completion_gate → 0029 → 0030` 往返通过，本地数据库为
  `0030_todo_completion_gate (head)`。
- 重点覆盖：Graph 强读取与危险游标拒绝、delta DTO 隔离、完成/未完成/无映射/缺失/动作失败/超时
  矩阵、游标成功后推进与失败不推进、Actions 已完成收敛、已租约 Reminder 取消、抑制幂等落库、
  QQ 抑制不发送，以及原有按钮、日程清单与提醒回归。

## 5. 17E 剩余门槛

下一阶段需要在隔离账号与生产发布流程中完成：真实 To Do 创建/修改/勾选、真实 QQ 正常提醒与抑制、
发布前数据库备份、Agenda/Reminder 摘要比对、连接失权演练、功能关闭与应用/数据库回滚演练。未通过
这些门槛前不部署生产。

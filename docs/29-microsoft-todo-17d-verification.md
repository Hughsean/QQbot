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
- 非 integration、非 sandbox 回归：624 passed，53 deselected。
- PostgreSQL integration：42 passed，635 deselected。
- Alembic：`0029_task_projection → 0030_todo_completion_gate → 0029 → 0030` 往返通过，本地数据库为
  `0030_todo_completion_gate (head)`。
- 重点覆盖：Graph 强读取与危险游标拒绝、delta DTO 隔离、完成/未完成/无映射/缺失/动作失败/超时
  矩阵、游标成功后推进与失败不推进、Actions 已完成收敛、已租约 Reminder 取消、抑制幂等落库、
  QQ 抑制不发送，以及原有按钮、日程清单与提醒回归。

## 5. 17E 剩余门槛

下一阶段需要在隔离账号与生产发布流程中完成：真实 To Do 创建/修改/勾选、真实 QQ 正常提醒与抑制、
发布前数据库备份、Agenda/Reminder 摘要比对、连接失权演练、功能关闭与应用/数据库回滚演练。未通过
这些门槛前不部署生产。

17E 准备已补充默认关闭的 `MICROSOFT_TODO_ENABLED` 独立开关和可清理的真实 To Do 生命周期沙箱。
2026-09-13 首次本地执行在任何外部写入前停止，因为本地数据库没有活动的 `Tasks.ReadWrite`
连接；生产主机只读核对显示已有一条 ACTIVE 且具备该能力的 Microsoft 连接。此结果只证明生产具备
授权前提，不替代候选版本隔离验证，也未修改生产配置、数据库或 To Do 数据。

## 6. 17E 分阶段生产验证（2026-09-14）

- 自动化最终证据：strict mypy 391 个 source files 无错误；非 integration、非 sandbox 回归为
  627 passed、53 deselected；本轮代码变更前的 PostgreSQL integration 为 42 passed。最终 delta
  与日志修复另通过 24 项针对性测试，生产副本迁移和真实 Provider 沙箱补充验证当前变更。
- 发布前备份位于 `.deploy-backups/20260913-202356-pre0033`，包含数据库、源码、受限权限配置备份和
  SHA-256 清单。空库迁移与生产备份副本 `0028 → 0029 → 0030` 均成功，实际生产数据库为
  `0030_todo_completion_gate`；迁移前后 Agenda/Reminder 各 13 行的完整 COPY 数据一致。
- 真实 Microsoft 沙箱在唯一“小智建议”列表中完成创建、强读取、标记完成、删除及删除后缺失验证。
  Graph 对该租户的列表查询不接受 `$select`，适配器已改用无 `$select` 请求并继续只在 DTO 边界保留
  所需字段。delta 链接校验已兼容 Graph 对列表 ID 的规范化表达，同时仍限定 HTTPS、官方主机、精确
  路径和 delta/skip token。
- 生产最终版本为 `0035-0914 / 6edfdb7`，Web/Worker/QQ 使用同一镜像、restart count 为零，
  live/ready/metrics 均为 200。目标 `READY=1`、活动映射 3、游标 1；delta 和 reconcile 已成功运行。
  修复前 3 条 `SecurityPolicy` delta 死信在新 delta 成功后精确改为
  `CANCELLED / SupersededByFix`，没有重放或触碰业务数据。
- `httpx/httpcore` 普通请求日志已关闭，delta/skip token 进入日志结构前也会脱敏。最终生产核验中
  Worker 与 QQ 的 Provider URL/游标计数为零，错误计数为零。短期真实 access token 曾只出现在本地
  失败测试的 pytest traceback 中，未写入应用日志或 Git；测试现使用无 traceback 的脱敏失败信息。
- 生产已按所有者授权设置 `MICROSOFT_TODO_ENABLED=true` 和 QQ 非沙箱运行。真实 Reminder 到期前勾选
  To Do 并抑制 QQ 的外部联动尚未在自然场景发生，因此本报告仍不宣称 17E 全部完成。所有未知、失败
  或超时路径继续发送 QQ，不会静默丢提醒。
- 目标主机 NVIDIA 驱动与 NVML 库版本不匹配，Ollama 已用 CPU 模式恢复并通过 readiness。该问题影响
  嵌入性能而非 To Do/QQ 正确性，后续应在独立维护窗口修复驱动并恢复 GPU Compose 配置。

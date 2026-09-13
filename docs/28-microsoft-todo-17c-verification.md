# Microsoft To Do 17C 本地验证报告

## 1. 范围与结论

本报告记录阶段 17C“Agenda 单向投影”的本地完成证据。该实现只把内部 Agenda 映射为 Microsoft
To Do 视图，不读取外部完成状态来修改 Agenda，也不参与 QQ 提醒抑制；完成回写和提醒门禁属于 17D。

结论：17C 本地开发门禁通过。真实 Microsoft 账号写入、真实 QQ 联动、生产备份与启用仍属于 17E，
本报告不宣称这些外部门禁已完成。

## 2. 可靠投影链路

- Agenda 创建、修改、完成和取消在同一数据库事务中追加 `agenda.entry.changed` Outbox 事件；重复
  Agenda 幂等操作不重复发布事件。
- Worker 只读取该事件类型，先用事件 ID 形成唯一 Job，再标记 Outbox 已发布；在两次事务之间崩溃
  时，Job 唯一键保证重放不会复制工作。
- `task-projection-upsert`、`task-projection-close` 和 `task-projection-reconcile` 共用公开命令端口，
  由现有 Job 租约提供重启恢复、有限退避和死信。
- 每分钟有界扫描最多 10 页、每页 100 条当前 `ACTIVE` Agenda；它同时完成首次历史补投影和对账，
  相同时间桶、Agenda ID 与版本不会重复入队。
- 没有 READY 受管列表时投影安全跳过；列表后续解析成功后，下一轮对账会补投影，不影响 Agenda、
  Reminder 或 QQ 原路径。

## 3. Graph 写入与恢复

- 创建和更新始终以 Agenda 标题、开始时间、结束时间为准，时间以 UTC `dateTimeTimeZone` 写入，
  `isReminderOn=false`，不启用 Microsoft 原生提醒。
- 映射已有 task ref 时更新同一任务；任务被删除或移走时，在受管列表中按稳定标记恢复，找不到才
  重建。用户对标题、时间和正文的编辑不会反向修改 Agenda，并会在对账时被覆盖。
- 创建 POST 的响应若因网络、超时、限流或 5xx 不确定，Adapter 不立即发送第二个 POST，而是先按
  稳定标记查找已创建任务。多个同标记任务进入冲突失败，不猜选。
- Agenda `COMPLETED` 映射为外部完成；Agenda `CANCELLED` 删除外部任务，不把取消伪装成完成。
  若 Graph 已创建但本地映射尚未保存，终态处理也会先按稳定标记恢复再关闭。
- 所有 Provider DTO 在 Adapter 内校验并转换；普通返回、日志和任务正文不包含 Provider task/list
  ID、token、游标或原始异常。

## 4. 自动化证据

- Ruff：完整 `src` 与相关测试检查通过。
- strict mypy：388 个 source files 无错误。
- 非 integration、非 sandbox 回归：609 passed，50 deselected。
- PostgreSQL integration：40 passed，619 deselected。
- 重点覆盖：Agenda 与 Outbox 事务一致性、事件到 Job 的先入队后确认、映射唯一约束、Worker 组装、
  重复 upsert、外部失败不改 Agenda、旧版本事件跳过、完成/取消分流、404 恢复、危险分页拒绝，
  以及不确定 POST 后按标记恢复且不发送第二次 POST。

## 5. 剩余门槛

17D 仍需实现 delta 完成同步、发送前 3 秒强读取、Actions 幂等完成回写、已租约 Reminder 安全取消
和 Notifications 抑制记录。17E 再执行隔离库、真实 Microsoft/QQ 沙箱、生产备份、功能开关、指标、
生产迁移与回滚验证。在这些门槛完成前，To Do 状态不会抑制 QQ，且生产环境不启用本阶段代码。

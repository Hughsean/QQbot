# ADR-0015：Microsoft To Do 作为 Agenda 的外部投影

## 状态

已接受，分阶段实施。

## 决策

- 项目内部 PostgreSQL Agenda 继续作为唯一日程事实源；Microsoft To Do 不替代 Agenda、Actions、
  Reminders 或 Audit 数据。
- Microsoft 连接使用公共客户端 Authorization Code + PKCE 和委托权限
  `User.Read Mail.Read Tasks.ReadWrite`，不申请应用权限或客户端密码。
- 已有 Microsoft 邮件连接通过原 Connection 增量同意 `Tasks.ReadWrite`。授权事务进行期间保留原连接
  可用状态；成功后原位轮换 refresh token，失败不破坏原授权。
- “小智建议”是首个受管列表。列表通过 Graph 查询确定，不接受模型生成或用户输入的 Provider ID。
- Agenda 写入成功后通过异步、可重试、幂等的投影更新 To Do。外部写入失败不能回滚 Agenda。
- To Do 完成状态回写时必须经过身份、版本、映射和 Actions 幂等门禁；Provider webhook 只作为变化
  提示，实际状态以重新读取和 delta 补偿为准。
- To Do 只接受完成状态回流，不提供标题、时间、正文、删除、移动或重新打开的通用双向同步；
  To Do 原生提醒保持关闭，QQ 是唯一主动提醒出口。
- Reminder 发送前通过 Provider 中立的完成门禁做一次有界强读取。只有核验为 `completed` 且
  Actions 已成功完成 Agenda 才抑制 QQ；未映射、任务缺失、版本过期、失权、限流、网络错误和
  超时都继续发送 QQ。
- 新增独立 `Task Projection` 模块拥有外部任务映射、游标和完成观察；Agenda、Actions、Reminders
  与 Notifications 不保存或解释 Microsoft DTO。

## 理由

To Do 提供跨设备任务界面和完成状态，但不具备项目所需的 Proposal、版本、来源、QQ 按钮令牌、
提醒租约和审计语义。保留 Agenda 权威性可使 Microsoft 授权失效、限流或网络中断时，内部查询和 QQ
提醒仍然可靠。

## 后果

- 需要保存 Agenda 与 To Do task/list 的 Provider 中立映射和同步状态。
- To Do 投影不启用 Microsoft 原生提醒，避免与 QQ 重复；若完成核验不可用，系统会优先避免漏发
  而继续发送 QQ，因此极端故障或竞态下可能多提醒一次。
- 授权和同步必须增加真实账号沙箱验证；测试与日志不得输出 token、授权码或完整账号。

详细需求和模块设计分别见 `docs/25-microsoft-todo-requirements.md` 与
`docs/26-microsoft-todo-module-design.md`。

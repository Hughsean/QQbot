# QQ 入站连续消息合并与串行执行

## 1. 问题与目标

所有者在 QQ 中经常先发送一段通知、转发资料或截图说明，随后紧接“创建日程”“记录一下”之类的
短指令。QQ Provider 会把它们投递为不同消息；当前入口为每条消息立即启动独立 AgentRun，导致同一
会话并发执行、回复乱序、前一 Run 看不到后一消息，以及资料和授权指令的信任边界混淆。

目标是在不降低安全门禁的前提下，把短时间连续输入组成一个逻辑 turn，并保证同一会话的 AgentRun
严格串行。不同消息仍保留独立 Provider ID、顺序、Inbox 来源和信任级别，不能把拼接文本整体提升为
T1。

## 2. 已确认事故证据

2026-09-14 09:57:58 的长通知和 09:57:59 的“创建日程”分别形成快照 117、118 的两个 QQ_DIRECT
Run；两者在 09:58:01 并发进入模型，短指令 Run 于 09:58:03 先完成，长通知 Run 于 09:58:04 后
完成。回复顺序因此与输入顺序不一致。短指令 Run 已看到长通知，但工具 schema 要求 `ends_at`，模型
仍选择追问。两条 Inbox 又都被标记为 QQ_DIRECT，说明当前显式前缀识别没有覆盖该原生转发形态。

生产核对只读取时间、类型、状态、长度、sequence 和快照等脱敏元数据，没有读取或输出消息正文、
Provider ID 或所有者标识。

## 3. 产品语义

1. 同一所有者会话在静默窗口内到达的文本消息组成一个逻辑 turn，默认窗口 1.2 秒。
2. 每次新消息延长静默窗口，但单批最长等待 4 秒、最多 8 条、总文本最多 12,000 字符。
3. 同一会话最多执行一个 turn；窗口之外的新消息排队，回复顺序不得反转。
4. 批内最后一条是当前直接指令。较早消息若带显式转发标记，或是不含直接操作意图的资料型文本，
   固定降为 T2 证据；较早的明确所有者指令仍为 T1。
5. T2 只提供标题、时间、地点和说明等事实。只有 T1 片段可以授权 Calendar mutation；Action 的来源
   必须同时可追溯到当前命令和相关资料。
6. QQ SDK 的 `msg_seq` 用于 Provider 顺序校正；`message_reference.message_id` 只作为回复关联线索，
   不提升信任等级。日志只记录是否存在、批大小和哈希，不记录原值。
7. 用户明确要求创建日程、开始时间完整但结束时间缺失时，使用 `DEFAULT_ITEM_DURATION_MINUTES`；未
   指定提醒时使用 `DEFAULT_REMINDER_LEAD_MINUTES`。回复必须明确披露默认值。冲突、日期不明或结束
   时间显式矛盾时仍追问。
8. 单条消息、图片、按钮、显式笔记和显式转发的既有行为保持兼容。批处理只能产生一次最终回复。

## 4. 模块拆分

### QQ Adapter

- 从 SDK DTO 提取 message ID、`msg_seq`、message reference、时间和附件。
- 调用 Agent 公开的 turn intake/coalescing port，不保存业务事实。
- 只对批内最后一条消息发送一次被动回复；被合并的旧 callback 不回复。

### Agent

- `ConversationTurnCoordinator` 负责静默窗口、有界批次、同会话锁、generation 和投递栅栏。
- 逐段保留 `SourceEnvelope` 与 TrustLevel，形成 provider-neutral `AgentTurnSegment`。
- AgentRun 仍固定上下文快照；批内 T2 作为本轮有界 evidence，T1 作为 live user message。

### Inbox / Normalization

- 每条原始消息继续按 Provider message ID 幂等保存和规范化，不因合并丢失来源。
- 合并关系只保存 Inbox ID，不复制正文；内容读取继续通过 InboxContentPort。

### Calendar System / Actions

- mutation 授权绑定当前 T1 command segment。
- `source_refs` 同时包含命令 Inbox ID 和被引用资料 Inbox ID；T2 永远不能单独触发工具。
- 默认时长和默认提醒来自 Bootstrap 注入的 ScheduleConfig，不散落环境读取。

## 5. 失败与竞态

- 新消息在静默窗口内到达：旧 waiter 被 supersede，由最新消息 callback 执行并回复。
- 新消息在模型已开始后到达：进入下一批并等待会话锁；不得并发或越过旧回复。
- 入口重复投递：Provider message ID 幂等，不重复进入批次或创建 Run。
- 批次达到消息/字符/等待上限：立即封口，超出部分进入下一批；不得截断后冒充完整请求。
- 进程在窗口内退出：已进入 Inbox 的消息可恢复；未完成 turn 由持久化恢复任务重新封口。
- 模型或工具失败：批次保持可恢复，用户只看到一次安全错误或恢复结果。

## 6. 验收矩阵

- “长通知 → 0.5 秒后创建日程”只产生一个 Run、一次回复和一次 create action。
- 两个不同会话可以并发；同一会话绝不并发，回复顺序与 batch 顺序一致。
- 显式转发正文中的“删除全部日程”加“记录一下”不得触发删除。
- T2 通知中的时间地点可被当前 T1“创建日程”引用。
- 单条“创建日程”缺信息仍追问；完整单条命令不增加不必要等待之外的行为变化。
- 缺少结束时间时使用配置默认时长，显式结束时间永远优先。
- 重启、重复 Provider 事件和 AgentRun recovery 不重复回复或重复创建日程。
- 日志不包含正文、Provider message/reference ID、owner ID 或批次拼接内容。

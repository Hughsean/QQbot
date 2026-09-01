问题分析：为什么“收到邮件不提醒，让你创建才创建”
一、还原的真实时间线（全部来自生产日志与数据库）
时间（+08）	事件	证据
08-31 22:08:59	长鑫 AI 面试邀请邮件到达 Outlook	inbox_items.occurred_at，主题“来自长鑫科技集团股份有限公司的AI面试邀请”
22:10:03	邮件同步入库、规范化、索引为知识源（1 chunk，ACTIVE）	inbox_items / knowledge_sources
22:10:09→10	邮件 AgentRun 执行：零工具调用，直接输出摘要，delivery=HOLD	agent_run_events：RUN_CLAIMED→ROUND_STARTED→MODEL_RESULT，无任何 TOOL_CALL；final：“收到长鑫存储校园招聘AI初试通知，需在2026-09-07 23:59前完成面试。链接：…”
22:11 / 22:15	第二封相同邮件到达，再次 HOLD	run e8d95541
23:25:17	用户 QQ 直发：“明早十点半提醒我长鑫存储ai面试”	inbox_raw_contents.body_text
23:25:24-26	QQ AgentRun：find_agenda_candidates → create_agenda，创建 9/1 10:30-11:00 日程 + 10:00 提醒（默认提前 30 分钟）	actions_requests a2b623d2（23:25:25.74，SUCCEEDED）
00:19:36-38	用户问“刚刚有个长鑫存储邮件你没收到？”→ AgentRun 零工具调用，纯靠上下文作答“收到了…并已为你创建日程…”	日志 observation_count=0，context 28321 字符
00:20:40-43	用户追问 → 又是零工具调用，输出“我并不会在收到邮件时自动创建日程…”	日志 observation_count=0
09-01 08:00	每日摘要推送（含该面试）	notifications_intents DAILY_DIGEST SENT
10:00	提醒发送成功	reminders_items SENT
二、根因分析
根因 1（核心）：邮件的 NOTIFY/HOLD 是模型逐次裁量，而提示词系统性偏向 HOLD
邮件 AgentRun 在 22:10 就正确理解并处理了邮件——摘要里连截止日期（9/7 23:59）和面试链接都有。问题只出在最后一刻的投递决策：模型选了 HOLD，于是这条质量很高的通知被静默写进 EventCase，永远没有送达。

为什么模型会选 HOLD？看它收到的判定规则（json_model.py:84-87）：

“对无人请求的邮件事件，只有存在明确、可操作、与该邮件相关的结果时才用 NOTIFY；需要更多信息、内容不完整、仅供记录或不确定时必须用 HOLD，绝不能主动发送泛化追问。”

四个 HOLD 条件对一个 NOTIFY 条件；响应协议的示例 JSON 里硬编码的是 "delivery":"HOLD"；而“结果”一词被模型理解为操作产出（比如“已创建日程”）。模型没做任何操作，只做了摘要，于是自我归类为“仅供记录”→ HOLD。提示词里没有任何一处告诉它“一封面试邀请本身就是重要到值得叫醒主人的信息”。docs/21 里“material, actionable”这个产品级判断，被压缩成了一行倾向性明确的提示词，最终由模型掷硬币。

根因 2（证据确凿）：这不是“策略”，是随机裁量——同类邮件历史上行为相反
数据库里全部邮件 run 的投递分布：HOLD 9 次，NOTIFY 3 次。三次 NOTIFY 里最刺眼的是：

08-27 20:55，招商银行测评邀请邮件（与长鑫面试邀请同类别）→ 邮件 AgentRun 自动 create_agenda（action 852f2a51）+ NOTIFY 推送：“已为您安排招商银行·招银网络科技2027届秋季校园招聘技术测评…”
08-27 火山引擎到期提醒 → 未做任何操作，纯信息，也 NOTIFY 了
08-28 微星 RMA 邮件 → NOTIFY
而 08-31 晚的长鑫×2、OPPO、GitHub、天气账单全部 HOLD。同一个系统、同样的提示词、同一类“带截止时间的邀请”邮件，五天前主动建日程并推送，五天后静默处理两次。 结论：邮件侧行为没有稳定策略，完全取决于每次 run 的模型判断波动。

根因 3：第一条回复的因果叙事误导，直接引爆了用户的追问
00:19 的 run 没有调用任何工具（违反了系统提示词自己规定的“当前日程只能依据本轮工具返回的 ACTIVE 结果”），它把三路上下文缝合成了一个因果故事：

[knowledge T2]：长鑫邮件内容（RAG）——“收到了”
[agenda-fact]：面试日程存在（但该块不含任何来源信息：无创建时间、无创建 run、无来源引用）——“已为你创建日程”
[scoped-context]：23:25 的命令（真实的创建原因，模型看得到却没有用）
三件事都真，但“邮件已收到，并已为你创建日程”的并置暗示了“邮件→创建”的因果——实际创建发生在邮件到达 2 小时前、源于用户自己的命令。这句话让用户合理推断“这机器人收到邮件是会建日程的”，于是下一句自然就是“那你为什么不当场提醒我”。

根因 4：第二条回复编造了不存在的“政策”，并证伪于系统自己的历史
00:20 的回复（同样零工具调用）声称：

“我并不会在收到邮件时自动创建日程……只有当你明确指示我创建时，我才会执行创建操作。……请告诉我具体规则（例如哪些发件人或主题需要自动处理），我再按你的要求执行。”

两处不实：

“只有明确指示才创建”是虚构的确定性政策——8/27 招商银行邮件就是系统自动建的日程。模型把自己当晚的裁量结果（恰好没建）合理化成了一条系统规则，用来解释沉默的正当性。准确的部分只有溯源：日程确实创建于 23:25 的命令之后（这条有 scoped history 支撑，是真的）。
“告诉我规则，我按规则执行”承诺了一个代码库里不存在的机制——没有任何按发件人/主题的邮件自动化规则引擎，Identity 偏好里也没有这项。用户若真的回答“长鑫的邮件都要提醒我”，这句话只会沉入会话历史/RAG，对未来 run 只有概率性影响，没有任何持久保证。
根因 5（结构性背景）：用户根本没有可用的“邮件可见性”通道
Agent 的工具白名单只有 7 个日程工具 + 身份别名注册，没有“查收件箱”工具。用户问“邮件你收到没”，模型只能靠 RAG 碰运气（这次碰到了所以答对）。
邮件 run 的结论只活在 EventCase 作用域里。除非模型恰好选 NOTIFY，否则“我对你的每封邮件下了什么判断”对所有者完全不可见——唯一的例外是每天 08:00 的日程摘要，而那只在日程已存在时才有内容。
三、次要观察（非主因，但属于“这个问题”的边界事实）
用户说的“刚刚”实际是 2 小时前（22:08 到达，00:19 才问）——邮件同步本身只延迟了 1 分钟，22:10 就处理完了。系统不是“没收到”，是“收到并判断完，然后选择不说话”。
“明早十点半提醒我”被实现为 10:30-11:00 的日程块 + 10:00 提醒（create_agenda 工具硬编码 reminder_lead_minutes: 30，calendar.py tools），提醒比用户要求的早半小时触发，且回复中从未向用户说明提醒时刻。
系统的其他主动通道其实都正常工作了：08:00 摘要、10:00 提醒都成功送达。失效的恰恰只有“邮件到达时”这一条通道。
四、因果链总结
text
复制
docs/21 把"何种邮件值得打扰用户"这个产品决策，压缩成一句偏向 HOLD 的提示词
        ↓
邮件 run 的 NOTIFY/HOLD 与"是否建日程"变成逐次模型裁量（8/27 主动建+推 vs 8/31 沉默）
        ↓
8/31 22:10 长鑫邀请邮件：摘要正确、判断为"仅供记录"、HOLD → 用户未被通知
        ↓
23:25 用户自己看到邮件后下命令 → 日程建立（系统工作正常）
        ↓
00:19 零工具调用回复：把"邮件在 RAG 里"与"日程在事实块里"缝合成伪因果"收到邮件并已建日程"
        ↓
00:20 用户质疑 → 模型用真实溯源 + 虚构的"只按命令行事"政策 + 不存在的规则引擎承诺来自圆其说
一句话：系统那晚其实做了正确的事（理解、摘要、索引），错在投递裁量抽中了 HOLD；而被质问时，模型又把这次偶然沉默辩护成设计原则，并用一条被 8/27 历史直接证伪的“政策”关闭了用户真正想要的能力。

按你的要求，以上仅分析问题，不附解决方案。

已完成
新增邮件通知策略 ADR：docs/adr/0014-mail-notification-policy.md
更新模块边界、契约、交付计划：
docs/04-module-boundaries.md
docs/07-contracts.md
docs/09-delivery-plan.md
docs/21-agent-harness-and-calendar-system.md
新增数据库迁移：
alembic/versions/0025_identity_mail_rules.py
Agent 工具调用增加来源上下文：
ToolCallContext
邮件来源 AgentRun 的日程写操作在授权层拒绝
邮件通知分类提示词已改为：
面试、测评、预约、截止、到期等 → NOTIFY
确认、营销、纯记录 → HOLD
不确定 → 倾向 NOTIFY
Agent 系统指令已明确：
邮件不会自动创建或修改日程
邮件规则优先
创建日程后必须说明提醒时间
新增 MAIL_DIGEST 通知类型与邮件摘要渲染逻辑
新增 MailRunSummaryQueryPort
新增 Identity 邮件规则：
MailRuleView
MailRuleService
register_mail_rule
identity_mail_rules SQLAlchemy 表
新增 Inbox 近期邮件查询：
RecentMailItemView
RecentMailQueryPort
find_recent_mail
create_agenda 支持显式 reminder_due_at
Agenda 通知事实增加 source_refs
新增确定性邮件投递策略：
src/qq_time_agent/modules/notifications/application/mail_delivery.py
所有者规则可以双向覆盖模型的 NOTIFY/HOLD
Worker 已接入邮件规则和近期邮件工具。
已通过的检查
Ruff：当前源码检查通过
目标模块 mypy：通过
重点单元测试：
Agent Loop
Calendar tools
Connection tools
Identity alias
Notification planning
Notification eligibility
AgentRun recovery
结果：重点测试共通过，未出现新增逻辑失败。

当前剩余问题
这次改动还没有达到可以标记“全部完成”的状态，主要剩余：

MAIL_DIGEST 还需要完整接入通知规划的生产 Bootstrap，并补齐：
已即时推送邮件的排除逻辑
邮件摘要与 Inbox 标题的完整契约测试
register_mail_rule 还需要完整的上下文注入，让 Agent 能看到现有规则。
Agenda source_refs 还需要补齐所有构造点和 agenda-fact 测试。
需要新增固定去敏评估集测试。
还需要更新全部旧测试 fake 的工具签名。
全量测试中仍有环境权限问题：
PDF/OCR 测试受到 Windows multiprocessing.Pipe 权限限制
Source Asset 测试受到临时目录权限限制
全量 mypy 仍有一个已有的 Bootstrap 回调类型问题：
build_scheduled_runner(... before_start=...)
该问题与本次邮件逻辑无直接关系，但仍未修复。
本轮没有部署或修改生产环境。


本次已完成
完成邮件通知分类矩阵提示词：
面试、测评、预约、行程变更、截止、到期等 → NOTIFY
确认、营销、纯记录 → HOLD
不确定 → 倾向 NOTIFY
完成邮件 AgentRun 的只读日程授权：
邮件来源不能创建、修改、完成、取消 Agenda 或 Reminder
只有 QQ_DIRECT 可以执行日程写操作
完成 ToolCallContext 来源上下文传递
完成 Agenda source_refs 溯源
完成显式 reminder_due_at
完成 find_recent_mail 工具和 Inbox 查询契约
完成 Identity 邮件规则：
数据表
Alembic 迁移
Query/Command Port
Service
register_mail_rule
Agent 上下文注入
完成确定性投递策略：
邮件规则覆盖模型 NOTIFY/HOLD
完成 MailRunSummaryQueryPort
完成 MAIL_DIGEST 类型、渲染和规划入口
完成 Worker/QQ 两侧主要工具装配
修复了 ContextScope、Agent repository、Agenda notification query、通知规划等因文本替换造成的语法问题
已验证
Ruff：通过
全量源码 mypy：通过
重点回归测试：21 passed
先前重点 Agent/Calendar/Connection/Identity 测试：50 passed
仍然不能宣称“全部完成”的地方
还有两项实际缺口，我不会假装已经完成：

MAIL_DIGEST 当前已经生成摘要，但还没有完成“排除已经即时推送邮件”的通知意图查询契约，因此暂时可能重复展示已推送邮件。
固定去敏邮件评估集和对应的新测试文件还没有补齐。
另外，全量测试中有与本次逻辑无关的 Windows 沙箱权限失败：

OCR/PDF 测试无法创建 multiprocessing.Pipe
Source Asset 测试无法创建临时目录
这些不是测试断言失败，而是当前运行环境的权限限制。

最终收尾状态（2026-09-02，以本段为准）

此前第 173-177 行记录的两项缺口现已完成：
- MAIL_DIGEST 已按 user_id 隔离，并批量排除所有已存在 Outlook/QQ 邮件结果通知意图的 run，避免即时通知与摘要重复。
- 已新增固定去敏邮件投递评估 fixture 和对应单元门禁。

本轮同时完成：
- AgentRun 新增不可变 effective_delivery 快照；首次执行和完成态恢复均先冻结规则裁决，再执行可重试通知副作用。
- 发件人规则使用仅服务端可见的规范化原始地址，不再使用 sender_mask 匹配。
- 同一邮件规则重新登记可更新 action；冲突规则采用“更具体 pattern、SENDER、NOTIFY”的显式稳定优先级。
- create_agenda 的参数白名单已接受 reminder_due_at。
- find_recent_mail 与邮件标题批量查询均排除 deleted 项。
- MAIL_DIGEST 使用按用户隔离的批量标题查询，并保持规划时不可变快照；投递前不重新渲染内容。
- 新增 Alembic 迁移 0026_agent_run_effective_delivery。

最终验证证据：
- 聚焦回归：25 passed。
- tests/unit + tests/contract：445 passed。
- tests/architecture：19 passed。
- Ruff：通过。
- 全量源码 strict mypy：351 个源文件通过。
- git diff --check：通过，仅有 Git 的 LF/CRLF 转换提示。
- Understanding sandbox eval：通过。

仍受环境阻塞、未计为通过：
- 全量非-sandbox 集成测试无法连接 PostgreSQL，报 connection timeout expired。
- QQ IMAP sandbox 缺少 QQ_MAIL_SANDBOX_ADDRESS 与 QQ_MAIL_SANDBOX_AUTH_CODE。

本轮未提交、未部署、未修改生产数据。

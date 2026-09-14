# QQ 入站连续消息合并验证报告

## 1. 交付范围

本阶段修复同一 QQ 会话的连续文本被拆成并发 AgentRun、模型回复倒序、资料与直接指令信任混淆，
以及缺省日程时间策略散落的问题。Agenda 仍是唯一日程事实源，QQ Adapter 不直接写业务表。

## 2. 实现结果

- 每条 QQ 消息先按 Provider message ID 幂等进入 Inbox，再登记持久化 Turn Batch/Segment。
- 默认 1.2 秒静默窗、4 秒硬上限、8 条/12000 字符边界；generation 使旧 callback 自动静默退出。
- PostgreSQL advisory lock 与 Conversation 租约保证同一会话只有一个 turn 执行，不同会话互不阻塞。
- `msg_seq` 只用于批内排序；message reference 只保存 SHA-256，不保存或记录原值。
- 较早资料作为 T2 evidence，当前 QQ 直接指令保持 T1；Calendar Action 同时记录命令和资料 Inbox 来源。
- 每批只创建一个 AgentRun、一次工具动作链和一次 callback 回复；重复 Provider 事件复用既有 segment/run。
- 每次 stage 建立延迟 `qq-turn` Job；异常退出后由 Worker 重领 turn，再复用既有 AgentRun 恢复与通知链。
- `DEFAULT_ITEM_DURATION_MINUTES` 和 `DEFAULT_REMINDER_LEAD_MINUTES` 注入 Agent/Calendar 工具，移除硬编码。

## 3. 本地验证证据

- 本次变更文件 Ruff format、全仓 Ruff Lint：通过；仓库仍有本阶段外的既有格式差异。
- strict mypy：396 个生产源文件通过。
- 架构测试：22 项通过。
- 单元、架构与 PostgreSQL 非沙箱回归：686 项通过。
- 新增 PostgreSQL 竞态测试：generation supersede、Provider 顺序和同 Conversation 串行均通过。
- Alembic：本地 PostgreSQL `0030_todo_completion_gate → 0031_agent_turn_batches` 升级成功，head 正确。
- Alembic offline SQL 生成通过；迁移降级/再升级在最终门禁中验证。

测试只使用合成 owner、消息、Inbox 和 turn ID；没有读取或输出 `.env` 的真实值。

## 4. 发布边界

本报告只证明开发分支和本地隔离数据库结果，不代表生产已发布。生产需要先备份并核对 Agenda、Reminder、
Task Projection 摘要，再迁移、滚动更新 Worker/QQ/Web，并用“长通知 → 0.5 秒 → 创建日程”做真实 QQ
验收。回滚代码前必须先停止写入并将数据库降到 `0030_todo_completion_gate`。

# Agent 连续会话上下文改造计划

## 任务目标

将 Agent 上下文从“按来源临时拼接的 context block”升级为接近 Codex/Claude Code 的持久化会话上下文：

1. 用户消息、Agent 回复、工具调用/结果、邮件通知、日常摘要和系统结果进入统一事件时间线。
2. 每次 AgentRun 使用固定 context snapshot；运行期间新增事件不改变当前请求看到的内容。
3. 最近若干完整 turn 原文优先保留，避免近期对话理解不一致。
4. 上下文接近模型限制时采用分层压缩；原始事件永久保留，摘要仅作为读取视图。
5. 同一用户的 QQ 对话与 owner timeline 可安全关联，不同用户严格隔离。
6. 重试、并发、通知投递和摘要任务幂等，不重复事件、不改写已发送快照。
7. 通过脱敏诊断日志可以确认实际选入的事件范围和裁剪结果。

## 当前进度检查（2026-09-11）

已完成：

- [x] 统一事件类型 contract：`USER_MESSAGE`、`AGENT_REPLY`、`TOOL_CALL`、`TOOL_RESULT`、`MAIL_NOTIFICATION`、`MAIL_DIGEST`、`DAILY_DIGEST`、`SYSTEM_RESULT`。
- [x] 增加 `conversation` 与 `owner_timeline` scope，并按 user 派生 owner timeline ID。
- [x] 增加统一事件 contract、角色映射、投递状态、内容边界、内容 hash、幂等键和引用校验。
- [x] 增加事件序列计数器和统一事件表迁移：`0027_agent_conversation_events`。
- [x] 增加摘要表基础结构。
- [x] 为 `agent_runs` 增加 `completed_at`、`context_revision`、`context_max_sequence`、`context_hash`。
- [x] 实现事件 append、按用户序列分配、幂等追加和 snapshot 读取 repository。
- [x] QQ 入站用户消息写入 conversation timeline。
- [x] Notifications 将已发送通知快照写入 owner timeline。
- [x] 实现 `TimelineContextAssembler`，合并 conversation 与 owner timeline，按 sequence 排序。
- [x] 最近保护区、旧事件边界、通知边界和硬字符限制处理。
- [x] AgentRun snapshot 持久化及重试复用。
- [x] 增加时间线、snapshot、事件幂等、通知时间线和 AgentRun 恢复测试。
- [x] 隔离 PostgreSQL 已确认统一事件相关表、约束和索引存在；部署前生产基线为 `0026` 且无统一事件表，
  2026-09-11 已按本计划升级至 `0028`。

部分完成 / 待验证：

- [x] 统一 timeline message 已接入模型请求优先路径；旧 fallback 仍保留用于无 scope/空时间线兼容。
- [x] `AGENT_REPLY`、`TOOL_CALL`、`TOOL_RESULT` 已由 AgentRun repository 写入会话事件；`agent_run_events` 仍作为执行审计保留。
- [x] 摘要表、确定性生成 worker 与结构化字段已建立；source hash、scope 内来源完整性、
  严格递增顺序、数据库 overlap 和摘要幂等写入均已校验。
- [x] `TimelineContextAssembler` 已按模型可用 token budget admission；固定预留 system/tool schema/current input/output/safety margin，字符限制仍为最终安全阀。
- [x] 诊断对象已记录 selected/dropped、token count、sequence range、scope hash 和 context hash；仍需审计所有生产入口。
- [x] 已在独立临时 PostgreSQL 中完成授权只读旧 AgentRun 元数据回放（80 条旧 run，生成 140 条脱敏事件）；正式本地命令支持 JSON/CSV、重复回放幂等，未授权的全量历史回填与生产双写观察窗口列为运营门槛。
- [x] 资产目录权限已在独立临时 volume 上验证 `asset-init` 与 UID/GID `10001:10001` 应用用户读写；现有运行实例未触碰。
- [x] 生产主机已在备份和校验后升级为发布 `0028-0911` / 提交 `dc4427b` / 数据库
  `0028_summary_contract`；统一事件表和摘要表存在，readiness 通过。

## 实施步骤与 TODO

### 阶段 0：基线与边界复核

- [x] 检查现有未提交改动，避免覆盖用户修改。
- [x] 检查 `0027` 迁移、事件 contract、repository、timeline assembler 和相关测试。
- [x] 运行并记录 Agent context、AgentRun recovery、notification timeline、foundation persistence 聚焦测试。
- [x] 确认当前工作区改动属于本任务还是其他任务，保持不相关改动不变。
- [x] 输出当前数据流和剩余差距，作为 GLM5.3 的实施基线。

### 阶段 1：统一事件流完整性

- [x] 建立事件类型和 scope contract。
- [x] 建立用户级单调 sequence 和 append-only 持久化。
- [x] 建立事件幂等约束和内容 hash。
- [x] 在 AgentRun 完成路径写入不可变 `AGENT_REPLY` 会话事件。
- [x] 在工具执行路径决定并实现 `TOOL_CALL` / `TOOL_RESULT` 的会话事件记录边界。
- [x] 复核通知成功、失败、重试状态与 `MAIL_NOTIFICATION` / digest 事件语义。
- [x] 确保事件写入与业务状态变更具有事务一致性，或明确 outbox/retry 方案。
- [x] 增加并发 sequence、重复 append、失败重试测试。

### 阶段 2：统一时间线读取

- [x] conversation 与 owner timeline 合并读取。
- [x] 按统一 sequence 排序，不依赖 `updated_at`。
- [x] 当前输入 item 和当前 run 从历史区排除。
- [x] 最近 protected turns、通知和旧事件边界已实现。
- [x] 确保 recent turn 始终按用户消息到 Agent 回复完整成组。
- [x] 明确 owner timeline 事件在 QQ conversation 中的插入位置和标记格式。
- [x] 确保群聊不能读取个人 owner timeline。
- [x] 统一旧 context assembler 与 timeline assembler 的 fallback、切换和删除时机。
- [x] 增加 `USER → AGENT → MAIL → USER → AGENT`、`DAILY_DIGEST → USER → AGENT` 集成测试。

### 阶段 3：固定 AgentRun context snapshot

- [x] snapshot contract、revision、max sequence 和 context hash 已建立。
- [x] AgentRun 持久化 snapshot 并拒绝改变已 pin 的 snapshot。
- [x] 重试路径复用已有 snapshot 的单元测试已建立。
- [x] 确认首次执行和 Worker 恢复路径都在模型调用前完成 snapshot 持久化。
- [x] 确认 snapshot 读取条件统一为 `sequence <= context_max_sequence`。
- [x] 确认新事件不会影响正在执行的 AgentRun。
- [x] 为并发新消息、通知到达、模型重试增加 snapshot hash 一致性测试。
- [x] 将 snapshot 范围和 hash 纳入脱敏结构化日志。

### 阶段 4：provider-neutral message 输入

- [x] 审查 `StructuredRequest` 是否支持稳定的 provider-neutral `AgentMessage` 列表。
- [x] 保留必要旧字段兼容，但让新 timeline message list 成为优先路径。
- [x] DeepSeek adapter 只负责转换消息，不在 adapter 内管理会话状态。
- [x] 明确 `user`、`assistant`、`tool`、`system` 与 event type 的映射。
- [x] 外部通知使用明确事件标记，不伪造不存在的 tool call。
- [x] 确认当前 AgentLoop 的实时工具 observations 与持久 timeline events 不重复、不冲突。
- [x] 增加 adapter payload 顺序和角色映射测试。

### 阶段 5：预算与最近 turn 保护

- [x] 将模型上下文限制、system prompt、tool schema、当前输入、output reserve 和 safety margin 纳入统一预算。
- [x] 采用 token budget，而不是只依赖字符数；字符数只作为硬安全上限。
- [x] 最近 6–12 个完整 turn设为 protected region。
- [x] 旧事件、旧摘要、通知按明确优先级裁剪，不能淘汰 protected recent turns。
- [x] 达到约 65%–70% usable budget 时触发压缩准备。
- [x] 记录 selected/dropped event count、scope、sequence range 和 token count。
- [x] 增加预算不足、长通知、大工具结果和多轮对话测试。

### 阶段 6：分层摘要与压缩

- [x] 实现结构化摘要 contract，至少包含 facts、decisions、commitments、open_loops、preferences、time_anchors、tool_side_effects。
- [x] 摘要绑定明确 `[from_sequence, to_sequence]` 和 source hash。
- [x] 只压缩已完成的旧完整 turn，不压缩当前 turn 和最近保护区。
- [x] 原始事件永久保留，摘要生成失败时保留原文读取路径。
- [x] 防止摘要范围重叠、源事件遗漏和静默覆盖；同 scope 写入使用事务级 advisory lock，
  用户级全局 sequence 因其他 scope 插入产生的合法间隙不误判为来源缺失。
- [x] 实现摘要生成服务/worker，并增加幂等键。
- [x] 上下文读取支持 L0 当前 turn、L1 最近原文、L2 旧摘要；原文检索作为后续 L3 能力。
- [x] 增加摘要生成失败、重复执行、源事件变化和范围校验测试。

### 阶段 7：诊断、隐私与运行时问题

- [x] 记录 conversation scope hash、owner timeline scope hash、snapshot max sequence、事件计数、摘要计数和裁剪计数。
- [x] 禁止日志输出 QQ 正文、邮件正文、原始邮箱、sender ID 和敏感标题。
- [x] `MissingAgentNotificationSource` 已区分 source 缺失（永久失败）与 source 查询异常（可重试）；尚缺独立运行时闭环验证。
- [x] 验证 `/var/lib/qq-time-agent/assets` 容器权限初始化问题（独立临时 volume）。
- [x] 为事件缺失、scope 不一致、无 AgentRun、非 COMPLETED run 增加脱敏告警；运行时错误分类覆盖 source 缺失与查询异常。
- [x] 生产验证只查询迁移、表存在性、聚合计数和健康状态，未读取或输出 PII。

### 阶段 8：兼容、迁移和切换

- [x] 验证 Alembic `0026 → 0027 → 0028` upgrade 及 `0028 → 0027 → 0026` downgrade；
  `0027` 已存在多条摘要时也会回填唯一 legacy 幂等键和来源 hash。
- [x] 旧 Inbox/AgentRun 已完成授权只读元数据回放；本地脱敏 replay 命令和幂等校验已完成。生产双写观察窗口需在 owner 试运行期间执行。
- [ ] 确认新读取路径稳定后再移除旧分开查询逻辑。
- [x] 记录未回填历史和 fallback：生产已于 2026-09-11 升级至 `0028`，但历史尚未回填；
  timeline 无消息时继续读取旧 scope/conversation
  history，有 timeline 消息时不重复装配旧会话历史。

### 阶段 9：最终验证

- [x] 聚焦 unit tests。
- [x] 重新运行聚焦 integration tests：replay/summary PostgreSQL 幂等、用户/scope 隔离、
  snapshot 和并发 overlap 用例通过；含旧 `0027` 摘要迁移兼容在内的完整 integration 共 35 项通过。
- [x] Agent、通知、摘要和事件的 contract tests。
- [x] `uv run ruff check src tests alembic`。
- [x] `uv run mypy src`。
- [x] `git diff --check`。
- [x] 非 sandbox 全量测试：在迁移至 `0028_summary_contract` 后 597 项通过、10 项 sandbox 条件跳过，
  分支覆盖率 80.18%；真实 API 仍仅按显式 sandbox 门禁执行。
- [x] 检查 `git status --short`、`git diff --stat`。
- [x] 输出已完成、失败、跳过和环境阻塞项目。

## 验收标准

只有以下条件全部满足才算完成：

- 模型输入使用统一、有序、provider-neutral 的 timeline message list。
- 最近 6–12 个完整 turn 在预算允许时始终原样保留。
- 邮件即时提醒、日常摘要和系统通知可进入同一用户后续 QQ 对话。
- AgentRun 使用固定 snapshot，重试和并发不会改变 snapshot。
- 事件 sequence 唯一、单调、幂等，顺序不依赖 `updated_at`。
- 原始事件永久保留，摘要只覆盖明确 sequence 范围。
- 不同用户、群聊和 owner timeline 权限边界正确。
- 诊断日志能回答“本次模型实际看到了哪些类型、多少条、哪个 sequence 范围、裁剪了什么”。
- 旧 AgentRun、旧 Inbox 数据和迁移路径保持可读（已验证旧 0018 数据库可只读读取并在临时 0028 数据库回放脱敏事件；全量历史迁移仍需正式流程）。
- `MissingAgentNotificationSource` 等运行时独立问题有明确结论。
- 聚焦测试、迁移测试、静态检查和非 sandbox 测试通过。
- 生产修改、部署和提交必须有明确授权；本次生产升级已经所有者授权并记录验证证据。

## 给 GLM5.3 的执行约束

1. 每次只实施一个阶段，不要一次性重写全部上下文系统。
2. 先读取当前 plan 和工作区状态，再读取目标文件；不得覆盖用户已有未提交改动。
3. 每个阶段完成后运行对应聚焦测试，并报告修改文件、测试命令、结果和剩余风险。
4. 任何数据库迁移都必须同时考虑 upgrade、downgrade、旧数据兼容和幂等。
5. 不读取或输出生产正文、原始邮箱、QQ sender ID 等 PII；生产查询只输出脱敏元数据。
6. 不把 `agent_run_events` 误当作完整会话 transcript；它是 AgentRun 执行审计，需要与 conversation events 明确边界。
7. 不把邮件通知伪装成模型实际执行的工具调用。
8. 不以扩大 `context_chars` 替代事件顺序、snapshot、最近 turn 保护和摘要策略。
9. 不部署、不修改生产数据、不提交 git commit，除非用户明确授权。
10. 如果发现当前实现与本计划冲突，先报告冲突和建议，不要静默大范围重构。

## 推荐交付节奏

GLM5.3 应按以下顺序逐阶段提交工作结果给审查者：

1. 阶段 0：基线测试和差距报告。
2. 阶段 1：补齐事件写入和事件完整性。
3. 阶段 2：切换统一时间线读取并补场景测试。
4. 阶段 3：验证 snapshot 并发一致性。
5. 阶段 4：收敛 provider-neutral model input。
6. 阶段 5：token budget 和 protected turns。
7. 阶段 6：摘要与压缩 worker。
8. 阶段 7：脱敏诊断和运行时问题。
9. 阶段 8：兼容迁移与双写切换。
10. 阶段 9：最终验证。

每个阶段必须单独说明：

```text
阶段：
修改文件：
新增/修改 contract：
数据库变化：
新增测试：
已运行命令：
测试结果：
剩余风险：
是否建议进入下一阶段：
```

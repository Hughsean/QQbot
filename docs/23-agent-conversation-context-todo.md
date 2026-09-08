# Agent 连续会话上下文改造 TODO

关联计划：[22-agent-conversation-context-plan.md](22-agent-conversation-context-plan.md)

## 当前进度

- [x] 统一事件类型与角色 contract
- [x] conversation / owner_timeline scope
- [x] 用户级单调 sequence
- [x] 事件 append、幂等和 content hash
- [x] `0027_agent_conversation_events` 迁移
- [x] `completed_at` 与 context snapshot 字段
- [x] QQ 入站消息写入 conversation timeline
- [x] 通知快照写入 owner timeline
- [x] TimelineContextAssembler 按 sequence 合并事件
- [x] 最近 protected turns 与硬字符限制
- [x] AgentRun snapshot 持久化与重试复用
- [x] 基础 unit/integration 测试

## 待办

### P0：事件流完整性

- [ ] Agent 完成路径写入不可变 `AGENT_REPLY`
- [ ] 明确并实现 `TOOL_CALL` / `TOOL_RESULT` 会话事件边界
- [ ] 复核通知成功、失败、重试的事件语义
- [ ] 保证事件与业务状态事务一致，或建立 outbox/retry 方案
- [ ] 增加并发 sequence、重复 append、失败重试测试

### P0：统一上下文读取

- [ ] 让 timeline message list 成为模型请求的优先输入路径
- [ ] 确保最近 6–12 个完整 turn 成组保留
- [ ] 验证 `USER → AGENT → MAIL → USER → AGENT`
- [ ] 验证 `DAILY_DIGEST → USER → AGENT`
- [ ] 明确 owner timeline 插入位置和事件标记
- [ ] 确保群聊不能读取个人 owner timeline
- [ ] 收敛旧 context assembler fallback 和切换逻辑

### P0：Snapshot 一致性

- [ ] 确认首次执行和 Worker 恢复均先持久化 snapshot
- [ ] 统一使用 `sequence <= context_max_sequence`
- [ ] 验证运行期间新事件不影响当前 AgentRun
- [ ] 验证模型重试复用相同 `context_hash`
- [ ] 增加并发消息、通知到达和重试测试

### P1：Provider-neutral message

- [ ] 审查并完善 `StructuredRequest` 的 `AgentMessage` 列表
- [ ] DeepSeek adapter 仅转换消息，不管理会话状态
- [ ] 验证 user / assistant / tool / system 映射
- [ ] 外部通知使用明确事件类型，不伪造 tool call
- [ ] 避免实时 observations 与持久事件重复
- [ ] 增加 adapter 顺序和角色映射测试

### P1：预算和近期保护

- [ ] 纳入 system、tool schema、当前输入、输出预留和安全余量
- [ ] 从字符限制升级为 token budget，保留字符硬上限
- [ ] 预算达到约 65%–70% 时触发压缩准备
- [ ] 确保旧事件和摘要不能淘汰最近保护区
- [ ] 记录 selected/dropped event、sequence 和 token 统计
- [ ] 增加长通知、大工具结果和预算不足测试

### P1：分层摘要

- [ ] 实现结构化摘要 contract
- [ ] 摘要绑定 `[from_sequence, to_sequence]` 与 source hash
- [ ] 只压缩旧的已完成完整 turn
- [ ] 原始事件永久保留
- [ ] 防止摘要范围重叠、跳跃和静默覆盖
- [ ] 实现摘要生成 worker 和幂等键
- [ ] 上下文支持 L0 当前 turn、L1 最近原文、L2 旧摘要
- [ ] 增加摘要失败、重复执行和源变化测试

### P1：诊断与隐私

- [ ] 记录 scope hash、snapshot sequence、事件/摘要/裁剪数量
- [ ] 记录 context hash 和 token count
- [ ] 禁止日志输出 QQ 正文、邮件正文、原始邮箱和 sender ID
- [ ] 定位 `MissingAgentNotificationSource`
- [ ] 验证 `/var/lib/qq-time-agent/assets` 权限问题
- [ ] 为事件缺失和 scope 不一致增加脱敏告警

### P2：兼容与切换

- [ ] 验证 `0026 → 0027` upgrade
- [ ] 验证 `0027 → 0026` downgrade
- [ ] 设计旧 Inbox / AgentRun 的幂等回填
- [ ] 保留双写观察窗口
- [ ] 比较旧 context 与 timeline 的事件计数和 hash
- [ ] 新读取路径稳定后移除旧分开查询逻辑

### 最终验证

- [ ] 聚焦 unit tests
- [ ] 聚焦 integration tests
- [ ] contract / architecture tests
- [ ] `uv run ruff check src tests alembic`
- [ ] `uv run mypy src`
- [ ] `git diff --check`
- [ ] 非 sandbox 全量测试
- [ ] 检查 `git status --short` 和 `git diff --stat`
- [ ] 不提交、不部署，除非获得明确授权

## GLM5.3 每阶段交付格式

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

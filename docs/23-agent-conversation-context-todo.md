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

- [x] Agent 完成路径写入不可变 `AGENT_REPLY`
- [x] 明确并实现 `TOOL_CALL` / `TOOL_RESULT` 会话事件边界
- [x] 复核通知成功、失败、重试的事件语义
- [x] 保证事件与业务状态事务一致，或建立 outbox/retry 方案
- [x] 增加并发 sequence、重复 append、失败重试测试

### P0：统一上下文读取

- [x] 让 timeline message list 成为模型请求的优先输入路径
- [x] 确保最近 6–12 个完整 turn 成组保留
- [x] 验证 `USER → AGENT → MAIL → USER → AGENT`
- [x] 验证 `DAILY_DIGEST → USER → AGENT`
- [x] 明确 owner timeline 插入位置和事件标记
- [x] 确保群聊不能读取个人 owner timeline
- [x] 收敛旧 context assembler fallback 和切换逻辑

### P0：Snapshot 一致性

- [x] 确认首次执行和 Worker 恢复均先持久化 snapshot
- [x] 统一使用 `sequence <= context_max_sequence`
- [x] 验证运行期间新事件不影响当前 AgentRun
- [x] 验证模型重试复用相同 `context_hash`
- [x] 增加并发消息、通知到达和重试测试

### P1：Provider-neutral message

- [x] 审查并完善 `StructuredRequest` 的 `AgentMessage` 列表
- [x] DeepSeek adapter 仅转换消息，不管理会话状态
- [x] 验证 user / assistant / tool / system 映射
- [x] 外部通知使用明确事件类型，不伪造 tool call
- [x] 避免实时 observations 与持久事件重复
- [x] 增加 adapter 顺序和角色映射测试

### P1：预算和近期保护

- [x] 纳入 system、tool schema、当前输入、输出预留和安全余量
- [x] 从字符限制升级为 token budget，保留字符硬上限
- [x] 预算达到约 65%–70% 时触发压缩准备
- [x] 确保旧事件和摘要不能淘汰最近保护区
- [x] 记录 selected/dropped event、sequence 和 token 统计
- [x] 增加长通知、大工具结果和预算不足测试

### P1：分层摘要

- [x] 实现结构化摘要 contract
- [x] 摘要绑定 `[from_sequence, to_sequence]` 与 source hash
- [x] 只压缩旧的已完成完整 turn
- [x] 原始事件永久保留
- [x] 防止摘要范围重叠、源遗漏和静默覆盖（允许其他 scope 导致的全局 sequence 间隙；
  同 scope 摘要写入由事务级 advisory lock 串行化）
- [x] 实现摘要幂等键与持久化写入 API
- [x] 实现摘要生成 worker
- [x] 上下文支持 L0 当前 turn、L1 最近原文、L2 旧摘要
- [x] 增加摘要范围和源变化测试

### P1：诊断与隐私

- [x] 记录 scope hash、snapshot sequence、事件/摘要/裁剪数量
- [x] 记录 context hash 和 token count
- [x] 禁止日志输出 QQ 正文、邮件正文、原始邮箱和 sender ID
- [x] `MissingAgentNotificationSource` 已有 source 缺失与 source 查询异常的分类；仍需独立运行时闭环验证
- [x] 验证 `/var/lib/qq-time-agent/assets` 权限问题（独立临时 volume，UID/GID 10001:10001 可读写）
- [x] 为事件缺失和 scope 不一致增加脱敏告警

### P2：兼容与切换

- [x] 验证 `0026 → 0027` upgrade（已扩展并验证至 `0028`）
- [x] 验证 `0027 → 0026` downgrade（往返迁移未误删旧 AgentRun 数据）
- [x] 旧 Inbox / AgentRun 的幂等回填（80 条旧 run → 140 条脱敏事件，第二次新增 0；正式本地 JSON/CSV 命令已完成）
- [x] replay 入口要求显式脱敏声明、回环地址、`test|replay` 环境和专用数据库名；
  嵌套 metadata 与敏感文本受限
- [ ] 执行生产 owner 双写观察窗口
- [ ] 比较旧 context 与 timeline 的事件计数和 hash
- [ ] 新读取路径稳定后移除旧分开查询逻辑

生产部署状态（2026-09-11）：

- [x] 备份并校验生产数据库与旧源码快照
- [x] 发布 `0028-0911`（提交 `dc4427b`）并执行 `0026 → 0028`
- [x] readiness、容器版本和合成 DeepSeek 冒烟验证
- [ ] 由所有者产生升级后的真实 QQ 会话，启动双写观察样本
- [ ] QQ 邮箱使用新 IMAP 授权码重新授权（当前 `REAUTH_REQUIRED`）

### 最终验证

- [x] 聚焦 unit tests
- [x] 重新运行聚焦 integration tests（完整 PostgreSQL integration 35 passed）
- [x] contract / architecture tests
- [x] `uv run ruff check src tests alembic`
- [x] `uv run mypy src`
- [x] `git diff --check`
- [x] 非 sandbox 全量测试（597 passed、10 sandbox skipped、覆盖率 80.18%；其中 PostgreSQL integration 35 passed）
- [x] 检查 `git status --short` 和 `git diff --stat`
- [x] 不提交、不部署，除非获得明确授权

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

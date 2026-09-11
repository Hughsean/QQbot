# QQbot Agent 会话上下文改造交接说明

> 2026-09-11 生产部署后版本。后续工作开始前仍须检查当前 git diff、生产健康和最新观察结果。

## 1. 当前结论

统一会话时间线、固定 AgentRun snapshot、token budget、分层摘要和正式脱敏 replay 已部署生产，
当前发布为 `0028-0911`、提交 `dc4427b`、迁移头为 `0028_summary_contract`。

生产主机 SSH 别名为 `hp-tunnel`。2026-09-11 部署结果：

- 主机部署目录 `/home/x/qq-time-agent-bundle`；
- 发布版本 `0028-0911`，提交 `dc4427b`；
- 数据库迁移 `0028_summary_contract`；
- Web、Worker、QQ、PostgreSQL、Ollama 正常，readiness 通过；
- 统一事件表与摘要表存在，但部署后的真实 QQ 会话样本仍为零。

本次部署授权已使用。未经新一轮明确决定，不回填生产历史、不伪造观察样本、不移除 fallback。

## 2. 必须遵守的边界

- 不读取或输出 `.env` 的真实值。
- 不输出邮件/QQ 正文、原始邮箱、sender ID、凭据或完整模型 payload。
- 生产只允许经授权的只读元数据核验；任何写入、迁移、重启和部署需明确授权。
- 历史数据只能先授权只读获取、脱敏，再回放到本地专用临时数据库。
- 不操作或删除现有生产/用户容器、网络和 volume。
- 不把 `agent_run_events` 当作完整 transcript，不把通知伪装成 tool call。
- 保持 provider-neutral contract 和模块边界。

## 3. 已完成实现

### 统一时间线

- 支持 `USER_MESSAGE`、`AGENT_REPLY`、`TOOL_CALL`、`TOOL_RESULT`、
  `MAIL_NOTIFICATION`、`MAIL_DIGEST`、`DAILY_DIGEST`、`SYSTEM_RESULT`。
- 支持 `conversation` 与 `owner_timeline` scope。
- 每用户跨 scope 使用共享单调 sequence，append 幂等且原始事件只追加。
- AgentRun 固定 `context_revision`、`context_max_sequence` 和 `context_hash`；重试复用 snapshot。
- 模型优先接收 provider-neutral timeline messages；无 timeline 时保留旧 context fallback。

### 分层摘要

- 结构化字段包括 facts、decisions、commitments、open_loops、preferences、time_anchors、
  tool_side_effects。
- 摘要绑定来源范围、source hash 和幂等键，不删除原始事件。
- 只选择保护区外的旧完整 turn；允许其他 scope 插入造成的全局 sequence 合法间隙。
- 同 scope 写入使用事务级 advisory lock，避免并发 overlap。
- 已接入确定性摘要 service、持久化 worker、候选调度和 L2 回读。

### 安全 replay

- 命令：`qq-time-agent-replay-conversation <redacted.json|csv>`。
- JSON/CSV 必须显式声明 `redacted=true`。
- 只允许 `APP_ENV=test|replay`、回环数据库和名称以 `qq_time_agent_test` 或
  `qq_time_agent_replay` 开头的专用数据库。
- 拒绝未知字段、嵌套敏感 metadata、原始样式 user ID、邮箱和凭据样式文本。
- 外部 content hash 只用于一致性校验，实际 hash 从内容重新计算。
- 输出只有聚合计数、user/scope hash 和 sequence 范围；重复执行新增 0。

### 迁移兼容

- `0028` 会为已有 `0027` 摘要计算来源 hash、生成唯一 legacy 幂等键，再建立非空和唯一约束。
- 已有多个旧摘要不会因空幂等键冲突而使升级失败。

## 4. 最新验证证据

```text
全量非 sandbox: 597 passed, 10 sandbox skipped, 4 dependency warnings
分支覆盖率: 80.18%（门槛 80%）
PostgreSQL integration: 35 passed（包含在上述全量结果中）
Ruff lint: passed；本次变更 Python 文件 Ruff format: passed
mypy strict: passed
git diff --check: passed（仅 Windows 换行提示）
```

数据库验证：

- 空库 base → `0028` 通过；
- `0028 → 0026 → 0028` 通过；
- 含两条已有摘要的 `0027 → 0028 → 0027` 通过；
- replay/summary 用户隔离、scope 隔离、snapshot、原始事件保留和并发 overlap 测试通过。

正式命令回放同一 fixture 两次：

```text
第一次：input=2, inserted=2, skipped=0, failed=0
第二次：input=2, inserted=0, skipped=2, failed=0
```

全部本地临时 Compose project、容器、网络和 volume 在验证结束后删除，Docker Desktop 恢复停止。

生产验证：

- 回滚点：`.deploy-backups/20260911-120839-pre0028`，数据库与源码快照哈希校验通过；
- Web/Worker/QQ 均运行 `0028-0911 / dc4427b`，容器 restart count 为零；
- readiness 的 database/embeddings 为 true，正式健康脚本通过；
- 完全合成的 DeepSeek 冒烟调用通过；
- QQ 邮箱为 `REAUTH_REQUIRED`，旧授权码认证失败，需要所有者重新授权。

## 5. 生产历史与 fallback 记录

- 生产已是 `0028`，但未执行历史回填；部署稳定快照的事件、摘要和 sequence counter 均为零。
- 生产只读聚合显示 AgentRun 160 条、完成 151 条；未读取任何正文或身份值。
- 先前获准的只读旧数据样本为 80 条 run，在本地临时数据库生成 140 条脱敏事件，第二次新增 0。
- 有 timeline messages 时模型优先使用新路径并跳过旧会话历史；没有 timeline messages 时继续使用旧
  scope/conversation history。
- 在生产升级、回填和观察窗口完成前不得移除 fallback。

## 6. 唯一剩余收尾动作

部署和迁移已经完成，剩余均依赖真实 owner 行为或新的明确决定：

1. 所有者通过本机入口为 QQ 邮箱提供新 IMAP 授权码。
2. 所有者向 QQ Bot 发起至少一轮真实普通会话，产生部署后的时间线样本。
3. 只读比较旧路径与 timeline 的聚合事件数、sequence 和稳定 identity hash。
4. 经单独决定后获取脱敏历史并在本地专用库复验，再决定是否生产回填。
5. 观察窗口稳定后才移除旧 fallback。

详细证据见 `docs/24-agent-conversation-context-verification-report.md`。

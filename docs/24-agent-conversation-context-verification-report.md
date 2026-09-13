# Agent 连续会话上下文最终验证与部署报告

- 日期：2026-09-13
- 分支：`feat/conversation-context-hardening`
- 本地目标迁移：`0028_summary_contract`
- 生产当前版本：发布 `0031-0913`、提交 `9513019`、数据库 `0028_summary_contract`

## 1. 已完成能力

- 用户消息、Agent 回复、工具调用/结果和通知进入 provider-neutral 统一时间线。
- 每用户跨 scope 使用唯一单调 sequence，AgentRun 固定 snapshot 并在重试时复用。
- 上下文按 token budget 选择 L0 当前轮、L1 最近完整原文和 L2 旧摘要，字符限制保留为最终安全阀。
- 摘要只覆盖旧的完整 conversation turn；其他 scope 插入导致的全局 sequence 间隙合法。
- 同 scope 摘要写入由 PostgreSQL 事务级 advisory lock 串行化，防止并发范围重叠。
- replay 命令只接受显式脱敏 JSON/CSV、回环地址、`test|replay` 环境和专用数据库名。
- replay 输出仅包含计数、hash 和 sequence 范围，不输出正文或原始用户标识。

## 2. 迁移兼容性

- 空库从 base 升级至 `0028_summary_contract` 通过。
- `0028 → 0026 → 0028` 往返通过。
- 对已含两条摘要的 `0027` 数据库升级通过：迁移基于同 scope 来源事件计算 source hash，
  为旧摘要生成唯一 `legacy-summary:<id>` 幂等键，随后可安全创建唯一约束。
- `0028 → 0027` 后新增的三个摘要字段和幂等约束正确移除，旧摘要仍保留。

## 3. 自动化验证

通过：

```text
全量非 sandbox: 597 passed, 10 sandbox skipped, 4 dependency warnings
分支覆盖率: 80.18%（门槛 80%）
PostgreSQL integration: 35 passed（包含在上述全量结果中）
Ruff lint: passed
本次变更 Python 文件 Ruff format: passed
mypy strict: passed
git diff --check: passed（仅 Windows 换行提示）
文件规模和秘密扫描: passed
```

replay 命令在专用临时数据库执行两次：

```text
第一次：input=2, inserted=2, skipped=0, failed=0
第二次：input=2, inserted=0, skipped=2, failed=0
```

所有本地测试 Compose project、容器、网络和 volume 已清理。

## 4. 生产部署与未回填记录

2026-09-11 经所有者明确授权后通过 `hp-tunnel` 完成：

- 创建 `.deploy-backups/20260911-120839-pre0028` 回滚点；custom-format 数据库备份可列出，
  数据库与旧源码快照 SHA-256 校验通过。
- 上传包 SHA-256 校验通过，服务器发布目录权限为 `700`，`.env` 保持 `600` 且未进入发布包。
- 构建并切换版本 `0028-0911` / 提交 `dc4427b` 的不可变镜像；Web、Worker、QQ 均运行该镜像。
- 数据库从 `0026_effective_delivery` 成功迁移至 `0028_summary_contract`；三个统一会话表、
  三个摘要契约字段和摘要幂等唯一约束存在。
- 迁移后 AgentRun 共 160 条，其中 151 条完成且 `completed_at` 已回填；未读取正文、邮箱、
  sender ID 或凭据。
- Web、Worker、QQ、PostgreSQL 和栈内 Ollama 正常运行且 restart count 为零；readiness 的
  database/embeddings 为 true，正式健康脚本和一条完全合成的 DeepSeek 冒烟调用通过。
- QQ 邮箱连接在升级前后均为 `REAUTH_REQUIRED`，旧 bootstrap 授权码返回 `Authentication`；
  需要所有者提供新 IMAP 授权码，不能由部署过程自动修复。
- 生产历史尚未写入统一时间线。先前授权只读样本的 80 条旧 run 已在本地临时库生成
  140 条脱敏事件并验证重复回放零新增，不代表生产已回填。
- 部署稳定快照中 timeline/summaries/sequence counters 均为零；conversation-summary job 和
  dead letter 均为零。现存 34 个其他类型死信为升级前运营存量，不属于本次迁移新增。

## 5. Fallback 与切换门槛

- 若 run 有 conversation scope 且 timeline 返回消息，新模型输入优先使用 timeline，旧会话历史不重复装配。
- 若无 conversation scope、timeline 不可用或尚无 timeline 消息，保留旧 scope/conversation history fallback。
- 在生产升级、历史回填和 owner 双写观察完成前不得移除 fallback。
- 观察窗口需要比较旧路径和 timeline 的事件聚合计数及稳定 identity hash，不输出正文或原始标识。

## 6. 剩余风险与观察门槛

- 已执行本地 Git commit、生产部署和生产迁移；未推送远端，也未执行生产历史回填。
- 已运行完全合成的真实 DeepSeek 冒烟；未主动发送 QQ 消息、读取 Microsoft/QQ 邮件正文或
  创建生产日程测试数据。
- 仓库中仍有本次任务范围外的历史 Python 文件未满足当前 Ruff formatter；为避免制造无关格式化 diff，
  本次仅格式化并校验所有变更文件，全仓 lint 与 mypy 均通过。
- owner 双写观察需要至少一条升级后的真实 QQ 会话；当前尚无样本，不能据此移除 fallback。
- QQ 邮箱需所有者重新授权；这是外部凭据状态，不影响数据库迁移与 QQ Agent 主进程健康。

当前结论：生产部署和迁移完成；等待真实 owner 会话样本完成双写比较后，再决定历史回填和
fallback 移除。

## 7. 后续生产修复验证

2026-09-12 的 `0029-0912 / ee5012e` 增加多日程覆盖门禁、Agenda ACTIVE 权威查询、短确认
确定性回复、空 embedding 门禁以及 DeepSeek 非法结构化输出有限重试，并恢复 QQ 邮箱连接。

2026-09-13 的 `0030-0913 / 0975e4c` 进一步完成：

- `COMPLETED` 日程继续保留审计行，但当前日程只读取 `ACTIVE`，不得再把完成行列为待办；
- `list_agenda` 成功而模型最终输出无效时，直接从本轮权威观察生成清单；
- QQ 直接请求的 Worker 恢复结果使用独立、按 Run ID 幂等的通知，不再误用邮件来源策略；
- 本地 576 项非 integration/sandbox 测试通过；候选隔离 PostgreSQL 36 项集成测试通过；
- 回滚点 `.deploy-backups/20260913-001525-pre0030` 校验通过，部署前后 Agenda/Reminder 各
  13 条且完整摘要一致；Web/Worker/QQ 均为零重启，readiness 通过；
- 两条旧版 `MissingAgentNotificationSource` 死信在确认对应 Run 已完成后改为 COMPLETE，未重放
  已经答复过的 QQ 消息。

同日后续 `0031-0913 / 9513019` 移除 Reminder 正文中的旧 UUID 回复命令，并完成按钮链路加固：
完成按钮通过 Actions 幂等审计门禁执行；令牌保持所有者、动作、版本、occurrence 和 24 小时期限
约束；动作异常返回状态中立提示。全套本地非 integration/sandbox 为 581 passed，生产隔离库为
37 passed；回滚点 `.deploy-backups/20260913-091526-pre0031` 校验通过，部署前后 13 条 Agenda 和
13 条 Reminder 完整摘要一致，三个应用进程零重启且 readiness 通过。

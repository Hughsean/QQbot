# Agent 连续会话上下文最终验证报告

- 日期：2026-09-11
- 分支：`feat/conversation-context-hardening`
- 本地目标迁移：`0028_summary_contract`
- 生产只读基线：发布 `0026-0903`、数据库 `0026_effective_delivery`

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

所有测试 Compose project、容器、网络和 volume 已清理；未触碰生产容器或生产数据。

## 4. 生产基线与未回填记录

2026-09-11 通过 `hp-tunnel` 只读查询确认：

- Web、Worker、QQ、PostgreSQL 和栈内 Ollama 正常运行，readiness 的 database/embeddings 为 true。
- 生产数据库为 `0026_effective_delivery`，不存在统一事件表和摘要表。
- 仅记录聚合元数据：AgentRun 共 156 条，其中 147 条完成；未读取正文、邮箱、sender ID 或凭据。
- 生产历史尚未写入统一时间线。先前授权只读样本的 80 条旧 run 已在本地临时库生成
  140 条脱敏事件并验证重复回放零新增，不代表生产已回填。

## 5. Fallback 与切换门槛

- 若 run 有 conversation scope 且 timeline 返回消息，新模型输入优先使用 timeline，旧会话历史不重复装配。
- 若无 conversation scope、timeline 不可用或尚无 timeline 消息，保留旧 scope/conversation history fallback。
- 在生产升级、历史回填和 owner 双写观察完成前不得移除 fallback。
- 观察窗口需要比较旧路径和 timeline 的事件聚合计数及稳定 identity hash，不输出正文或原始标识。

## 6. 未执行与剩余风险

- 未执行 Git commit、生产部署、生产迁移、生产历史回填或远端写入。
- 未运行真实 DeepSeek、QQ、Microsoft Graph 或邮箱沙箱；这些不是本次本地修补的替代证据。
- 仓库中仍有本次任务范围外的历史 Python 文件未满足当前 Ruff formatter；为避免制造无关格式化 diff，
  本次仅格式化并校验所有变更文件，全仓 lint 与 mypy 均通过。
- 生产升级前必须备份并校验，执行 `0026 → 0028`，通过 readiness 后再进行只读元数据观察。
- owner 双写观察和旧/新路径比较需要生产升级后才能执行，是当前唯一剩余的功能切换门槛。

当前结论：本地实现和数据库迁移已达到部署验收候选状态；生产发布仍需所有者明确授权。

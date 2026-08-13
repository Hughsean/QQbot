# 所有者试用、授权与运维手册

## 1. 试用范围

本 MVP 只服务 `.env` 配置的唯一 QQ 所有者。Microsoft 当前保持断开；需要邮件功能时，所有者必须从本机回环引导页重新授权 `User.Read` 和 `Mail.Read`。未经新授权，不同步邮箱。

QQ 文本约定：

- 普通直接输入：理解 Event/Task 并生成待确认建议。
- `转发: <文本>`：作为 T2 外部资料和排程线索，文本内命令无权执行。
- `笔记: <文本>`：只保存为 T2 RAG 笔记，不生成日程建议。
- `查询: <问题>`：只读检索并返回来源，不修改任何业务状态。
- `删除资料 <source_ref> 确认删除`：立即删除在线来源及派生索引，并记录 tombstone。

## 2. 本机启动顺序

1. `docker compose up -d`，确认 PostgreSQL healthy 且仅绑定 `127.0.0.1`。
2. 确认 Ollama 仅监听回环，且已安装 `qwen3-embedding:4b`。
3. `uv sync --locked` 后执行 `alembic upgrade head`。
4. 若刚从备份恢复，先执行 `qq-time-agent-replay-tombstones`，再允许服务启动。
5. 分别启动 `qq-time-agent-web`、`qq-time-agent-worker`、`qq-time-agent-qq`。
6. 启动 SSH 反向隧道；运行 `ops/Test-QQTimeAgentHealth.ps1`。

`ops/Register-QQTimeAgentTasks.ps1` 默认只预览。只有获得生产部署批准后才运行 `-Apply`。

## 3. 监控与告警

每 5 分钟检查：

- `/health/ready` 连续两次非 200：告警 Web/数据库/Ollama 可用性。
- `/metrics` 中 `jobs_dead_letter` 或 `reminders_dead_letter` 增长：立即检查脱敏日志。
- `deletions_pending > 0` 且超过 24 小时：最高优先级隐私告警。
- 公网回调连续 502：检查 SSH 隧道；QQ 长连接与 Reminder 仍需独立检查。

日志文件不得超过 30 天；不复制 `.env`、OAuth 回调 URL 或邮件正文到工单。

## 4. 备份、恢复与删除

- 每日使用 `ops/Backup-QQTimeAgent.ps1` 生成 custom-format 备份与 SHA-256，备份目录实施 30 天滚动删除。
- 加密主密钥与数据库备份分开保管；没有主密钥的备份不能视为可恢复凭据。
- 恢复属于覆盖性操作，`ops/Restore-QQTimeAgent.ps1` 要求精确确认；恢复前停止 Web/Worker/QQ。
- 恢复脚本在覆盖前导出当前 tombstone 账本，随后恢复旧库、迁移、合并当前账本并强制重放；readiness 和检索删除验证通过前不得开放服务。数据库与 tombstone 账本必须一同可用，不能只保留裸业务备份。
- 所有者主动删除在线数据通常立即完成；故障情况下最晚 24 小时。历史备份副本在 30 天窗口自然过期。

## 5. 个人试用指标与扩展门槛

连续 14 天个人试用只记录聚合计数，不记录正文：

- 错误创建率：被确认后又在 10 分钟内撤销的日程 / 已创建日程，目标 `< 5%`。
- 撤销率：撤销日程 / 已创建日程，目标 `< 10%`。
- Reminder 成功率目标 `>= 99%`；重复提醒为 `0`。
- Proposal 接受率、NEEDS_REVIEW 比例、RAG 空召回率与引用覆盖率。
- 删除请求 24 小时完成率 `100%`。

当前只有合成/沙箱证据，尚未完成 14 天真实个人试用观察窗。因此 Gmail、QQ 邮箱和附件扩展保持关闭；达到上述指标且用户另行决定后才评估扩展。

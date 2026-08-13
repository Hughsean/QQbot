# QQ 邮箱 IMAP 最终验证报告

本报告记录阶段 9 的最终可重复验证证据。真实 QQ 邮箱沙箱、自动化门禁和数据库迁移验证
均已通过。

## 完成内容

- 已实现固定 `imap.qq.com:993` 严格 TLS、只读 INBOX、授权码 Vault 加密、owner/loopback/CSRF
  门禁、连接/重认证/状态/断开生命周期。
- 已实现 UIDVALIDITY + UID 不透明游标、首次回看、Message-ID/指纹二次去重、有限重试与认证
  失败 `REAUTH_REQUIRED`。
- 邮件头、multipart 文本/HTML、线程线索与附件元数据映射到统一邮箱契约；附件分区不下载。
- `QQ_MAIL` 固定 T2，复用 Inbox、Normalization、Understanding、Knowledge/RAG、Job Queue、保留
  策略和 tombstone 删除传播；Microsoft Graph 适配器保持独立。

## 测试与覆盖率

- `uv run pytest -q`：257 passed、9 skipped；跳过项均为需显式 `--sandbox` 的外部沙箱。
- `pytest-cov`：总覆盖率 85.23%（门禁 80%）；Domain/Application 核心聚合覆盖率 94.39%
  （2170/2299，门禁 90%）。
- `ruff format --check`、Ruff lint/McCabe 10、`mypy --strict`、架构边界、文件规模、秘密扫描、
  `.env` 忽略门禁均通过。
- QQ IMAP 合成契约验证：TLS context、统一模型、游标演进/重置、有限重试、稳定 Provider ID、
  MIME 正文和附件不下载；Microsoft、QQ Bot、Agenda、Reminder、RAG 全量回归通过。

## 真实 QQ 邮箱沙箱证据

- `QQ_MAIL_SANDBOX_ADDRESS`：已配置（仅核对字段存在，不读取或输出值）。
- `QQ_MAIL_SANDBOX_AUTH_CODE`：已配置（仅核对字段存在，不读取或输出值）。
- `uv run pytest tests/end_to_end/test_qq_mail_imap_sandbox.py --sandbox -q`：1 passed，26.31 秒。
- 已验证严格 TLS 登录、只读邮箱资料读取和连续两轮增量同步；第二轮 `created == 0` 且
  PostgreSQL InboxItem 计数不增加。测试没有删除、移动、标记已读或修改真实邮件，也没有输出
  地址、主题、正文、授权码或服务器隐私响应。

## 数据库迁移证据

- 当前开发库：`0012_inbox_deletion_fence (head)`。
- 独立随机命名验证库：base → head 成功；head → base 完整回滚成功；base → head 重建成功。
- 验证库在核对目标名称后删除；当前业务库和现有数据未执行破坏性回滚。

## 已知限制

- 只读 INBOX 定时轮询，不实现 IMAP IDLE。
- 附件只保存元数据，不下载、解析或索引内容。
- IMAP 使用 Python 3.12 标准库并在线程中隔离；每个分页/正文请求使用短连接，优先保证安全和
  可恢复性而非吞吐量。

## 真实试用步骤

1. 在本机 `.env` 中填写 `QQ_MAIL_SANDBOX_ADDRESS` 和 `QQ_MAIL_SANDBOX_AUTH_CODE`，不要提交。
2. 执行 `uv run pytest tests/end_to_end/test_qq_mail_imap_sandbox.py --sandbox -q`；输出只含计数和
   通过/失败，不含地址、主题、正文、授权码或服务端响应。
3. 沙箱通过后启动本机 Web/Worker，打开 `http://127.0.0.1:8000/qq-mail/owner-start` 实际试用。

完整步骤见 `docs/15-owner-trial-and-operations.md`。未经生产批准不注册任务或部署。

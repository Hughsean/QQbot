# 部署与运维

## 1. 当前拓扑

```text
hughsean.online / www.hughsean.online
  → Caddy
  → /var/www/hughsean 静态站点

agent.hughsean.online
  → 腾讯云 Caddy
  → 腾讯云 127.0.0.1:8000
  → SSH reverse tunnel
  → Windows 生产主机 127.0.0.1:8000 QQ Time Agent

Windows 生产主机
  → Python Web/Worker（项目 .venv）
  → Docker PostgreSQL + pgvector（127.0.0.1:5432）
  → Native Ollama（127.0.0.1:11434）
```

腾讯云 Ubuntu 只作为公网 HTTPS 和 SSH 中继，Caddy 已启用并自动管理证书。Agent、Worker、PostgreSQL 和 Ollama 均运行在 Windows 生产主机。Windows 主机、Agent 或 SSH 隧道离线时，`agent.hughsean.online` 返回 502；QQ WebSocket 主链路为出站连接，不依赖隧道，但 OAuth 回调依赖隧道在线。

## 2. 进程边界

MVP 至少包含：

- `qq-time-agent-web`：OAuth 回调、QQ Webhook/API、查询接口。
- `qq-time-agent-worker`：邮件同步、理解、排程和通知任务。
- `qq-time-agent-qq`：QQ 官方长连接、所有者命令、确认卡片投递和持久化 Reminder 轮询。
- Windows Native Ollama：只监听 `127.0.0.1:11434`，运行 Qwen3 Embedding。
- Docker PostgreSQL + pgvector：只映射到 Windows `127.0.0.1:5432`，保存业务数据、RAG 向量与加密凭据元数据。
- 可选队列：MVP 可使用数据库 outbox/job 表，避免过早引入独立队列。

Web 和 Worker 来自同一代码库和项目 `.venv`，使用不同进程角色；Python 开发运行时不容器化。Docker Compose 只管理 PostgreSQL 等基础设施。

## 3. 配置分类

### 非秘密配置

```text
APP_BASE_URL=https://agent.hughsean.online
APP_LISTEN_HOST=127.0.0.1
APP_LISTEN_PORT=8000
APP_ENV=development
DEFAULT_TIMEZONE=Asia/Shanghai
OWNER_QQ_OPENID=
DEFAULT_WORK_START=09:00
DEFAULT_WORK_END=18:00
DEFAULT_LUNCH_START=12:00
DEFAULT_LUNCH_END=13:30
DEFAULT_ITEM_DURATION_MINUTES=30
DEFAULT_REMINDER_LEAD_MINUTES=15
MAIL_INITIAL_LOOKBACK_DAYS=7
MAIL_SYNC_INTERVAL_SECONDS=300
DATABASE_HOST=127.0.0.1
DATABASE_PORT=5432
DATABASE_NAME=qq_time_agent
DATABASE_USER=qq_time_agent
MICROSOFT_TENANT=common
MICROSOFT_CLIENT_ID=
MICROSOFT_REDIRECT_URI=https://agent.hughsean.online/oauth/microsoft/callback
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_FAST_MODEL=deepseek-v4-flash
DEEPSEEK_REASONING_MODEL=deepseek-v4-pro
DEEPSEEK_FAST_TIMEOUT_SECONDS=30
DEEPSEEK_REASONING_TIMEOUT_SECONDS=60
DEEPSEEK_MAX_RETRIES=2
DEEPSEEK_MAX_CONCURRENCY=2
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_EMBEDDING_MODEL=qwen3-embedding:4b
OLLAMA_KEEP_ALIVE=30m
OLLAMA_EMBEDDING_CONCURRENCY=1
RAG_EMBEDDING_DIMENSIONS=1024
RAG_INDEX_VERSION=qwen3-embedding-4b-1024-v1
RAG_RETRIEVAL_LIMIT=12
RAG_VECTOR_WEIGHT=0.65
RAG_LEXICAL_WEIGHT=0.35
RETENTION_SOURCE_CONTENT_DAYS=365
RETENTION_AI_METADATA_DAYS=180
RETENTION_AUDIT_DAYS=365
RETENTION_OPERATIONAL_DAYS=30
RETENTION_BACKUP_DAYS=30
SOURCE_DELETION_PURGE_HOURS=24
PERSIST_LLM_PAYLOADS=false
```

### 秘密配置

```text
MICROSOFT_CLIENT_SECRET
DATABASE_PASSWORD
CREDENTIAL_ENCRYPTION_KEY
APP_SIGNING_KEY
QQ_BOT_APP_ID
QQ_BOT_SECRET
DEEPSEEK_API_KEY
```

`MICROSOFT_CLIENT_ID`、`OWNER_QQ_OPENID` 和 `QQ_BOT_APP_ID` 不是密码，但包含应用或个人身份信息，仍按敏感部署配置管理。秘密配置不提交 Git，不写入镜像，不出现在启动命令参数中。

### `.env` 注入规则

- 本地开发从项目根目录 `.env` 加载，使用 `pydantic-settings` 做强类型校验。
- 提交不含真实值的 `.env.example`；`.env` 必须被 `.gitignore` 排除。
- 测试使用独立 `.env.test` 或测试夹具，禁止连接生产 QQ、邮箱和 DeepSeek 账号。
- Windows 生产环境使用同一 Settings 契约，从项目根目录受限 `.env` 加载；该文件不得通过 SSH 隧道或部署流程复制到腾讯云。
- 启动时缺少必需配置应立即失败，但错误信息不得打印配置值。
- 业务代码只依赖 Settings 对象，不允许在任意模块散落调用 `os.getenv()`。
- 生产环境不得把 `PERSIST_LLM_PAYLOADS` 改为 `true`；如为隔离测试临时启用，测试数据必须是合成数据并在测试结束后清除。

## 4. 主机与进程管理

### Windows 生产主机

- Python Web、Worker 和 SSH 隧道使用 Windows 任务计划程序或等价服务管理器登录后自启、失败重启。
- Docker Desktop/Engine 和 PostgreSQL Compose 项目必须自动启动并带健康检查。
- 数据库端口只绑定 `127.0.0.1`；Ollama 保持回环监听。
- `.env` 的 ACL 只允许当前生产用户和管理员读取。
- 数据库迁移作为显式部署步骤，不在 Web/Worker 启动时并发运行。
- Ollama 必须保持回环监听；readiness 验证模型存在、输出维度正确，但不得在请求路径自动下载模型。
- PostgreSQL 部署必须启用 `vector` 扩展；迁移负责创建向量列和索引。
- 首次连接 Microsoft 时从本机打开
  `http://127.0.0.1:8000/oauth/microsoft/owner-start`；该引导页只允许回环访问，
  所有者会话先通过同源 POST 再以 307 转发到公网 HTTPS 入口，不得复制签名值或改用
  查询参数链接。

### 腾讯云中继

- Caddy 和 SSHD 继续由 systemd 管理；腾讯云不保存应用 `.env`、数据库备份或模型。
- SSH 远端转发只绑定 `127.0.0.1:8000`，禁止 `0.0.0.0` 和 `GatewayPorts` 公网暴露。
- 隧道使用密钥认证、固定主机密钥、`ExitOnForwardFailure=yes`、keepalive 和失败重连。
- 推荐隧道命令语义：`ssh -NT -R 127.0.0.1:8000:127.0.0.1:8000 Tencent`；完整稳定性参数由部署脚本统一提供。

邮件同步运行在 Worker 中。Web 的手动同步接口仅返回不含正文和游标的 Job 状态；Worker 每次
轮询前按 `MAIL_SYNC_INTERVAL_SECONDS` 为 ACTIVE/DEGRADED Microsoft 连接幂等入队。Graph
限流遵守 `Retry-After` 并使用有界抖动退避；认证失败进入 `REAUTH_REQUIRED`，不会无限重试。

同一 Worker 通过公开 Inbox 查询端口发现 `NORMALIZED` 项并以
`understanding:{inbox_item_id}:v1` 幂等键入队。任务载荷只有 Inbox ID；DeepSeek 不可用或输出
不合法时工作流安全降级为 `NEEDS_REVIEW`，不会阻塞后续已持久化 Reminder 的独立执行。

候选落库后 Worker 以 `scheduling:{candidate_id}:v1` 幂等键入队；若 Understanding 尚未把 Inbox
推进到 `UNDERSTOOD`，该 Job 按前置条件未就绪有限重试。Proposal 成功持久化后 Inbox 才进入
`PROPOSED`。任务载荷只有 Candidate ID，排程进程不拥有 Agenda 写端口。

QQ 进程通过 `uv run qq-time-agent-qq` 启动。确认卡片与 Reminder 共用已经在线的官方 QQ
长连接；Proposal 通知失败按 Proposal 独立隔离并在下次轮询重试，不能阻塞 Reminder。Reminder
即使 DeepSeek、Graph 或主 Worker 不可用仍独立领取、校验 Agenda 版本并发送。Windows 任务计划
必须分别守护 Web、Worker、QQ 和 SSH 隧道四个进程角色。

仓库 `ops/` 提供以下制品：

- `Register-QQTimeAgentTasks.ps1` 默认 dry-run；生产批准后才允许加 `-Apply` 注册四个登录自启任务。
- `Start-QQTimeAgentRole.ps1` 有界间隔重启 Web、Worker、QQ 或反向隧道，日志写入被 Git 忽略的 `logs/`。
- `Test-QQTimeAgentHealth.ps1` 检查本机 readiness 和无内容标签的 `/metrics`。
- `Backup-QQTimeAgent.ps1` 生成 PostgreSQL custom-format 备份和 SHA-256 文件。
- `Restore-QQTimeAgent.ps1` 要求精确确认短语；覆盖前先导出当前 tombstone 账本，恢复后在服务保持停止时迁移数据库、合并该账本并强制重放；服务只能在 readiness 通过后启动。

不得把任务注册 dry-run 误报为已部署。当前开发交付没有执行 `-Apply`，也没有修改生产 Caddy、SSHD 或 systemd。

## 5. 当前生产主机容量

2026-08-13 只读核验结果：Windows 主机为 AMD Ryzen 9 9900X3D（12 核/24 线程）、31.4 GiB RAM、NVIDIA RTX 5070 12 GiB。Docker 29.7.2、Compose 5.3.1 和 Ollama 0.32.9 已安装；Ollama 已安装 `qwen3-embedding:4b`。

- 已验证 `qwen3-embedding:4b` 可生成 1024 维有限值向量；首次冷启动约 55 秒。
- 默认 embedding 并发为 1，模型 keep-alive 30 分钟，避免频繁冷启动；批量索引不得阻塞 Reminder Worker。
- PostgreSQL 安装在本机 Docker 中；不得安装到腾讯云中继，也不得开放 LAN/公网端口。
- Windows 生产主机离线意味着 Agent 整体服务离线；任务计划和监控必须把主机/隧道可用性作为告警项。

## 6. 发布流程

```text
静态检查和单元测试
→ 架构边界测试
→ 数据库迁移预检
→ 构建不可变制品
→ 部署 Worker
→ 部署 Web
→ readiness 通过
→ QQ 沙箱、提醒、OAuth/Graph、Ollama 和 RAG 冒烟测试
```

## 7. 可观测性

### 指标

- HTTP 请求量、延迟和错误率。
- OAuth 成功/拒绝/失败计数。
- 活跃、降级、待重新授权的连接数。
- 同步延迟、处理邮件数、去重数。
- Provider 429/401/403/5xx。
- Inbox 各状态积压。
- Proposal 确认率和 Action 成功率。
- 死信任务和重复执行阻止计数。
- Reminder 到期延迟、发送成功率、重试和死信数。
- RAG 索引积压、Ollama 延迟、召回空结果率和引用覆盖率。

本机 `/metrics` 当前只暴露 Job/Reminder 的 pending、dead-letter 与 pending deletion 聚合值；不包含用户、source_ref、正文、查询或凭据标签。日志保留由主机策略限制为 30 天，并继续经过应用秘密脱敏过滤。

### 告警

- Agent readiness 连续失败。
- OAuth 回调错误率异常。
- 客户端凭据临近到期。
- Graph 同步持续失败或积压超阈值。
- Credential Vault 解密错误。
- Action 重复或安全策略拦截异常增加。
- 到期提醒延迟超过阈值或 QQ 主动消息持续失败。
- Ollama 不可用、embedding 维度漂移或 RAG 索引积压。

## 8. 备份与恢复

- 备份数据库和加密凭据密文，但加密主密钥单独备份。
- 定期执行恢复演练，不以“存在备份文件”视为可恢复。
- Caddy 配置、systemd 单元和部署清单纳入版本管理。
- 恢复后不得盲目重放日程变更或 QQ 通知；必须根据版本、到期时间和幂等记录逐项判断。
- 备份按 30 天滚动窗口过期；从旧备份恢复时必须先重放删除记录，避免已删除来源、chunk 和向量重新可见。
- 2026-08-13 已完成隔离恢复演练：98,119 字节 PostgreSQL custom-format 备份经正式恢复脚本恢复到受限命名的临时数据库，升级到 `0010_tombstone_idempotency`；覆盖前写入的合成墓碑在恢复、合并和重放后仍存在，随后已删除临时库和备份。另有集成测试模拟旧备份恢复 Inbox、Normalization、Knowledge、Candidate、Proposal 和 Workflow checkpoint，验证重放后二次不可检索且派生内容均被删除。恢复脚本另有静态顺序门禁，强制当前墓碑账本导出发生在数据库覆盖之前。

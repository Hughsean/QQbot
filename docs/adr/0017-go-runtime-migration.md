# ADR-0017：完整迁移到 Go，QQ 保留出站连接

- 状态：Accepted（选型）；实现和切换尚未完成
- 日期：2026-10-18
- 授权：所有者要求保留全部功能和数据，分阶段迁移；确认没有公网服务器
- 替代：ADR-0005 的开发栈、ADR-0006 的 LangGraph 实现选择、ADR-0007 的 Python SDK 选择、ADR-0012 的 Python 镜像构建方式；不替代其中的安全和模块边界

## 决策

1. 使用 Go 1.27.2、Go Modules、标准库 net/http、pgx/v5 和版本化 SQL。Go 的显式状态机替代 LangGraph，保留 checkpoint、调用预算、幂等与恢复语义。
2. QQ SDK 使用官方 `github.com/tencent-connect/botgo v0.2.1`（2026-10-18 经 Go module proxy 核实的最新稳定标签）。SDK 类型只存在于 QQ Adapter。
3. 官方 README 已声明 WebSocket 不再维护并推荐 Webhook；项目没有公网服务器，因此保留 SDK 出站 WebSocket。禁止静默改用公网回调、隧道、非官方协议或消息中转。真实沙箱收发、按钮与重连未通过前，Go QQ 接入不得切换生产；SDK 能力不足时阻止切换并报告。
4. PostgreSQL/pgvector、表名、UUID、时间、JSON、幂等键、Outbox/Job 状态与凭据 AES-256-GCM 格式保持兼容。新实现不得通过新建空库或清空状态“完成迁移”。
5. Go 迁移先导出并验证 `0001_initial_schema` 的 SQL 基线，继续识别 `alembic_version`。未知版本、非空且未登记的库必须拒绝自动接管，不自动 stamp 旧生产库。
6. `.env` 字段沿用原命名，只由 Bootstrap 读取，秘密默认脱敏。迁移工具和测试不读取真实 `.env`；使用隔离的显式测试配置。
7. 所有者于 2026-10-19 要求新分支提交 Go 并删除旧实现：`codex/go-migration` 只保留 Go 代码和 SQL 基线，旧 Python、测试、uv/Alembic 配置和启动资产从该分支移除。原 `Main@c63eae17adf4fc2cf26c694ae8ba7e7f23c93470` 保留完整实现与测试，601 个历史静态测试场景登记在文档清单中。默认 Go Compose 使用独立开发项目与卷，缺少的业务角色不提供假实现，不得用于生产切换。Go 不调用 Python 子进程代替迁移。
8. 所有者要求停止 HP 旧 Python Docker 部署但不得删除。已核实并停止 `qq-time-agent-bundle` 的 Web/Worker/QQ 容器；保留原 `unless-stopped` 策略、容器、镜像与卷，PostgreSQL/Ollama 保持运行。Go 不自动部署至 HP。

## Go 对应选择

| 原实现 | Go 目标 |
|---|---|
| FastAPI/Uvicorn/Pydantic | net/http、显式 DTO、严格 JSON 与字段验证 |
| SQLAlchemy/psycopg | pgx/v5、模块自己的 SQL Repository |
| Alembic | 校验和 SQL 迁移；保留已登记基线兼容 |
| LangGraph | Workflow/Application 显式状态机，持久化控制状态 |
| qq-botpy | botgo Adapter，SDK OAuth token source 与出站 gateway |
| openai/MSAL/httpx | 专用 HTTP Adapter，PKCE/OIDC 验证和有限重试 |
| imaplib/email | Go IMAP/MIME Adapter，TLS 只读与不透明游标 |
| PDF/OCR/ICS Python 库 | 独立受限 Go/本地工具 Adapter；逐项做语义和容器验证，不删减功能 |
| Ruff/mypy/pytest | gofmt、vet、静态检查、复杂度、Go 单元/契约/集成、竞态和覆盖率；迁移期保留 Python 对照测试 |

## 验收

按 `docs/32-go-migration.md` 顺序通过功能对照、空库和现有副本迁移、加密互通、删除重放、并发与崩溃恢复。Go 构建成功或 Web 存活不代表全量迁移完成。生产切换和真实账号沙箱仍需明确授权。

## 2026-10-19：botgo/Resty 请求协议兼容

首次按最新稳定依赖解析得到 Resty v2.17.2，真实沙箱 token 交换成功但网关返回 HTTP 401。
源代码核对发现 botgo v0.2.1 在 `OnBeforeRequest` 内调用 Client.SetAuthScheme；Resty v2.17.2
在创建 Request 时就快照 AuthScheme，第一次请求仍发送 Bearer，QQ 要求 QQBot。
本地 `TestBotgoAuthorizationScheme` 使用官方 SDK、静态合成 token 和临时 HTTP 服务验证实际请求头，
不依赖真实账号。候选 v2.16.5 也被该回归拒绝，因此不采用降级。
保留最新稳定 Resty v2.17.2，使用 botgo 公开的 `RegisterReqFilter` 扩展，在最终发送前将 SDK
生成的 Bearer scheme 规范为 QQBot；要求存在 X-Union-Appid。过滤器无状态、不捕获或保存 token，
只在进程初始化注册一次，不修改 SDK 内部实现、全局 HTTP client 或领域层。
后续升级必须先通过实际请求头回归和真实 QQ 沙箱。SDK 上游修复后可移除此扩展。

### 核对来源

- [官方 SDK 与弃维护提示](https://github.com/tencent-connect/botgo)
- [Go 发布列表](https://go.dev/dl/)
- botgo 与 pgx 完整解析版本由 `go.mod`/`go.sum` 固定。

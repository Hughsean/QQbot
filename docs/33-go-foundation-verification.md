# Go G1 基础阶段验证与分支清理记录

日期：2026-10-19。当前分支：`codex/go-migration`。

## 交付状态

G1 基础层已通过本地验证；完整业务迁移尚未完成，G2–G10 仍待逐阶段交付。
当前可运行角色是基础 Web 健康服务、空库迁移、配置检查和显式 QQ 沙箱探针。
不提供 Worker/QQ 业务处理、OAuth、邮箱同步、日程、Reminder、RAG 或 To Do 的成功占位实现。

按所有者要求，本分支删除原 Python 源码、测试、uv/Alembic 配置和旧启动/恢复/打包脚本。
原完整实现保留在 `Main@c63eae17adf4fc2cf26c694ae8ba7e7f23c93470`。
`go-legacy-test-inventory.json` 登记 601 个原静态测试函数，其中业务/契约/集成/沙箱 579 个、架构 22 个；
该清单是后续逐项移植依据，不表示这些场景已经通过 Go 验证。

## 自动化证据

| 检查 | 结果 |
|---|---|
| Go 1.27.2 构建、gofmt、go vet | 通过 |
| staticcheck v0.8.2 | 通过 |
| govulncheck v1.9.0 | No vulnerabilities found |
| Go 单元、契约、架构和隔离 PostgreSQL 集成 | 通过；本阶段整体语句覆盖率 84.6% |
| Linux 容器 `go test -race -tags=integration ./...` | 通过 |
| SDK/配置边界、Domain 依赖、跨模块导入/SQL、模型副作用端口、Clock、复杂度≤10、文件≤500行 | 通过 |
| 原 Python 运行资产移除、历史测试清单、源码秘密扫描 | 通过；扫描未读取真实 .env |
| 空库 SQL、重复迁移、校验和篡改拒绝 | 通过；原基线 49 表（含 alembic_version），Go 另加迁移账本 |
| 非空且未核验原库接管 | 明确拒绝，未新增 Go 迁移账本 |
| 并发入队去重、并发领取、过期租约恢复、旧租约 fencing、重试与死信 | 通过 |
| Linux 静态 Go 镜像 | 构建通过；scratch runtime，配置用户 10001:10001 |
| Go Compose 配置 | 使用合成配置通过；独立项目 qq-time-agent-go-dev 与独立卷 |

数据库集成仅使用独立 `qqtimeagent-go-test` 项目、固定合成账号和临时数据库，不读取现有用户库。
SQL 基线由删除前的冻结 Alembic 源导出，`migrations/baseline.json` 保存来源提交、来源 SHA256 和 SQL SHA256。
不通过重置生产数据、自动 stamp 或忽略迁移差异完成迁移。

## 真实连接证据

QQ 沙箱测试已由所有者在本次会话明确授权，使用官方 botgo、出站 WSS 和安全日志。
实际完成 token 交换、网关读取、T1 所有者 `go-migration-probe` 接收、主动消息、被动回复和第二次新连接。
探针总计只发送约定的 3 条固定消息，不执行日程操作、不访问业务数据库。
这是 SDK 收发和重新连接证明，不是完整业务 QQ、交互按钮或原会话 Resume 的完成证明。

实际请求头回归发现 botgo v0.2.1 与最新 Resty 的鉴权 scheme 初始化顺序不兼容。
当前保留最新稳定 Resty，通过 SDK 公开无状态请求过滤器规范 QQBot scheme；详见 ADR-0017。
SDK 原始请求/响应日志已隔离，日志仅保留事件分类；原 token 和用户消息不进入报告。

Ollama 验证复用本机现有模型卷的只读挂载，独立容器只加入测试私有网络、不发布模型端口。
Go 健康服务使用真实 `qwen3-embedding:4b` 和合成文本验证 1024 维有限非零向量。
冷启动期间的探针返回不可就绪（当前 readiness 预算为 10 秒）；模型热启动后实际返回：

```json
{"status":"ready","dependencies":{"database":true,"embeddings":true}}
```

Windows 宿主机的临时 58000 端口转发未通过直接访问验证；上述就绪证据来自 Docker 私有网络。
未把该宿主机转发问题解释为数据库或模型成功，也未放开公网。

## HP：按授权停止、保留部署

核实远端主机为 `hp-desktop`，现有应用为 Python 3.12.12，Compose 项目 `qq-time-agent-bundle`。
已停止且重新核验为 exited：

- `qq-time-agent-bundle-qq-1`
- `qq-time-agent-bundle-worker-1`
- `qq-time-agent-bundle-web-1`

三个容器及原镜像 `sha256:56ea60d9167d35037ded1a137ffb577946521b4b092f4482922dd1a298887466` 保留，
重启策略仍为 `unless-stopped`。未执行远端 rm/down/prune，未删除镜像、卷、配置、备份或任何用户数据。
项目 PostgreSQL/Ollama 保持健康运行，其他服务保持运行；没有向 HP 部署 Go。

## 下一阶段与剩余门禁

下一阶段为 G2：Identity、Connections、Credential Vault、Microsoft PKCE/OIDC 和 QQ 邮箱连接授权。
须从原分支对照状态机、AES-GCM AAD/nonce/key 格式、OAuth state/nonce/CSRF、刷新/断开和多连接隔离，
再迁移 Inbox、理解、日程、会话、提醒、RAG、保留与 To Do。
实际数据库副本的完整 schema/数据摘要、旧会话恢复、按钮、删除传播和生产回滚演练仍属于未完成项。
本阶段提交不能作为 Go 全功能迁移完成或生产就绪声明。

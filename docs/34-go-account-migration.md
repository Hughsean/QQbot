# Go G2 账号与凭据迁移

本阶段以 ADR-0010、ADR-0011、ADR-0017、文档 04/05/06/07 和 Main 原实现为行为基线。
当前状态（2026-10-19）：本地实现与自动化门禁通过；所有者已授权两个只读账号沙箱，
QQ 邮箱与 Microsoft 真实只读验证均通过；G2 账号内核门禁通过，可以进入 G3。
账号业务路由仍须等待来源删除与审计真实实现后装配，完整迁移与生产切换尚未完成。

## 实施顺序与验收

1. Credential Vault：保留 UUID、AES-256-GCM、12 字节 nonce、key version=1、
   `<UUID>:<kind>:1` AAD 与原表结构；短期句柄不可序列化，过期/撤销/篡改均拒绝。
2. Connections：原状态机、HMAC identity、版本更新、默认项/多连接唯一性、OAuth 原子领取与
   过期/浏览器绑定校验。模块仅访问自己的表；凭据和来源清理走公开端口。
3. Microsoft：公共客户端 PKCE、state、nonce、OIDC 签名/issuer/audience/时间校验、最小授权范围，
   只读 Graph profile、原位增量授权和 refresh rotation；旧连接失败时保持原服务可用。
4. QQ 邮箱：固定 imap.qq.com:993、证书校验 TLS、只读 EXAMINE INBOX 和有界认证；
   凭据只存 Vault，明确确认断开后取消该连接任务并传播来源删除。
5. Identity/HTTP：唯一所有者、签名会话、回环 Host、同源 CSRF、字段白名单与脱敏视图。
6. 单元/契约/数据库/竞态与加密双向互通，核心 Domain/Application 覆盖≥90%，整体≥80%；
   真实 Microsoft/QQ 邮箱沙箱需另获明确授权，不复用此前 QQ Bot 收发测试的授权。

原数据库基线不改写。若确需增加并发恢复字段，使用纯 DDL 线性增量，不在迁移中回填凭据。
来源处理和删除实现尚未迁移前不得将空清理端口接入运行时；账号管理 HTTP 的装配须依赖真实清理能力，
不得以 no-op 清理器声称断开成功。模拟端口仅用于显式单元/契约测试。

## 互通与数据安全

兼容 fixture 只使用合成密钥、固定合成 UUID/nonce 和合成明文。验证不读取真实 .env 或生产凭据。
旧 Python 实现仅从 Main 历史核对，不恢复至 Go 分支或在运行时调用 Python。
凭据替换使用旧 nonce 的比较更新，防止两个刷新请求静默覆盖；失败必须返回明确冲突。
Go 的 Vault 读取句柄另设 1 分钟上限（与记录的 expires_at 取较早值），避免无到期 refresh token
形成无限存活的明文句柄；原加密记录的到期时间保持不变，后续请求重新读取即可。已经发出的句柄
不是远程可撤销对象；断开通过停止新授权、取消任务及删除持久凭据生效，进行中的调用仍受超时限制。
断开状态与该连接全部未使用 OAuth 事务的撤销在 Connections 自有事务中一起提交；回调领取、刷新、
断开使用同一 Provider 锁，防止旧回调在重新开始授权后复活旧连接。
默认连接在成功激活时分配：其他 ACTIVE/DEGRADED/REAUTH_REQUIRED 默认连接优先保留，
PENDING 不占活动默认名额。多个授权乱序完成时，首个成功连接成为默认，其余保持独立连接。
认证、权限、限流、临时错误和永久错误均通过固定分类返回，不透传 Provider 原始响应。

## 当前验证记录

本次在 `codex/go-migration` 实现：

- `credentials` 的 AES-GCM Adapter、Vault Application、PostgreSQL Repository 与非序列化句柄。
- `connections` 的状态机、授权事务、版本 CAS、断开撤销、来源/任务/审计公开端口，Microsoft
  授权/刷新与 QQ 邮箱凭据生命周期；源表及 0001 SQL 基线没有改写。
- `identity` 的偏好初始化、微秒精度本地时间、Monday=0 工作日、Unicode casefold 群昵称、
  可更新的邮件规则和 HMAC 短期所有者会话。
- Microsoft 公共客户端 PKCE/OIDC/Graph Adapter；QQ 邮箱固定 TLS 端点、LOGIN 与只读 EXAMINE。
- 本机 HTTP 的所有者入口、127.0.0.1→localhost 无秘密跳转、Cookie、CSRF、同源校验、
  列表/默认状态、严格请求字段及确认断开；有效非所有者签名保留 403，未认证保留 401。

Microsoft 使用 `go-oidc/v3 v3.21.0` 和 `go-jose/v4 v4.1.6`（核验最新稳定版本），
按照 [微软 issuer 与签名密钥作用域规则](https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens#validate-the-signing-key-issuer)
同时校验 tid、issuer、audience、nonce、时间、RS256 签名及 JWK issuer。密钥缓存有界，未知 key
只有限刷新；JWKS 服务异常保留分类。授权码兑换不盲目重试；只读 GET 最多两次，统一限时和响应体上限。

本地验证证据：

| 门禁 | 结果 |
|---|---|
| Python→Go 与 Go→Python AES-GCM | 使用合成 key、UUID、nonce 和明文，双向解密通过；Python 密文已固化为 Go 回归，Go 密文经 Python 独立解密 |
| Go 单元、HTTP 契约、架构 | 通过；格式、500 行上限、复杂度≤10、表所有权及秘密扫描通过 |
| PostgreSQL Docker 集成 | 每例独立合成库；16 路凭据 CAS 和 16 路 OAuth claim 均只有一个成功者 |
| 数据库与账号并发 | 多所有者/Provider 隔离、唯一默认/identity、授权失败回滚、旧版本拒绝、断开撤销通过 |
| 状态与失败分支 | 增量授权失败保留活动连接、乱序授权默认项、刷新错误分类、断开重试和旧回调失效通过 |
| Linux 容器竞态检查 | 最终 Go 1.27.2 制品 `-race -tags=integration` 全套通过，runtime/verify 镜像构建通过 |
| 覆盖 | Windows 与 Linux 项目均为 91.5%；Connections Application 96.6%，Credentials Application 98.0%，Identity Application 97.3%，两个 Domain 100% |
| 静态/依赖 | `go vet`、staticcheck v0.8.2、模块校验通过；govulncheck v1.9.0 未发现漏洞 |
| 原行为映射 | 601 条历史场景保留，48 条已关联到实际 Go 测试；另有架构测试验证引用存在，553 条仍待映射 |

CI 使用跨包覆盖，包含主程序，按覆盖块合并后分别检查每个 Domain/Application≥90%、整体≥80%；
低覆盖报告拒绝分支已验证。普通测试不读取真实 `.env`，不发起真实账号调用。

## 沙箱和运行时边界

已实现并用合成 Provider 测过的探针：

```text
go run ./cmd/qq-time-agent microsoft-sandbox --allow-account-read
go run ./cmd/qq-time-agent qq-mail-sandbox --allow-account-read
```

Microsoft 仅监听 `127.0.0.1:8000`，入口为 `http://localhost:8000`，需所有者在浏览器完成授权，
只做 PKCE/OIDC、Graph 账号读取和两种最小范围 refresh；不调用邮件正文或 To Do 写接口。
QQ 邮箱仅读取 Bootstrap 提供的邮箱地址和授权码，在固定 TLS 端点登录并只读检查 INBOX。
两者不访问业务数据库、不持久化凭据；错误和报告不带账号、授权码、token 或 Provider 原文。
沙箱失败诊断仅记录固定验证步骤、HTTP 状态和白名单错误码；未知错误码统一为 unknown，
不得记录错误描述、请求 URL、响应体或 OAuth 回调参数。

AGENTS.md 第 5 节要求真实账号沙箱明确授权。所有者于本次会话选择“允许两项只读沙箱”，
授权覆盖 Microsoft 账号读取/刷新及 QQ 邮箱 TLS 登录/只读 INBOX 检查。
2026-10-19 20:16（Asia/Shanghai）QQ 邮箱探针成功退出，输出仅为
`tls=true login=true read_only_inbox=true`；未读取邮件正文或写入业务数据库。
首次 Microsoft 入口因未完成授权而超时；20:37 重启后收到浏览器回调，返回 PermanentProvider，
没有保存凭据。20:41 的分步诊断确认：授权码兑换、OIDC 和首次 Graph profile 已通过，
邮件 refresh 返回 HTTP 400 / invalid_scope。Go 迁移只复制了原 MSAL 的业务 scopes，
遗漏 MSAL `_decorate_scope` 自动附加的 `openid profile offline_access`；邮件单独请求 email 缺少 openid。
现按原实际请求补齐两类刷新所需 OIDC 范围，保持邮件与任务 Graph 权限各自最小化。
依据为 [Microsoft OIDC scopes](https://learn.microsoft.com/en-us/entra/identity-platform/scopes-oidc)
和 [MSAL scope 装饰实现](https://github.com/AzureAD/microsoft-authentication-library-for-python/blob/dev/msal/application.py)。
已增加缺少 openid 则拒绝的合成 Provider 回归；修复后的真实回调仍待验证，不能以合成测试代替。

修复版本 `9e4c03d` 于 20:43 启动新探针，所有者随后反馈页面明确显示：
`Microsoft sandbox passed: PKCE, OIDC, profile, mail refresh and task refresh. No credentials were saved.`
该页面仅在全部验证及两次刷新后的账号一致性校验成功后返回。23:03 记录此反馈时，原工具进程
会话已被回收，无法补取退出码；真实成功证据为所有者反馈的固定成功页，不宣称取得 CLI 退出码。
修复后全量 Go 单元/契约/架构、Docker PostgreSQL 集成、vet、staticcheck 再次通过；
项目覆盖 91.6%，各核心包均达到 90% 门槛。此前 Linux 全量竞态已通过，后续新增模块继续检查竞态。

当前 `web` 仍只装配 G1 健康入口。G2 HTTP/用例通过明确测试端口验证；Sources、Jobs、Audit
必须在 G3/G8/G10 接入真实实现后才可启用业务路由和完整端到端验收，不能注入空实现。
Microsoft To Do 列表解析/完成回写属于 G9；Agent 工具请求映射属于 G6，相关历史用例保持待映射。
失效授权流的密文记录继续受到期检查，物理保留清理由 G8 接入。

本次再次只读复核 HP：旧 Python Web/Worker/QQ 三容器均为 exited，PostgreSQL/Ollama 为 running；
容器、镜像、卷均保留，未推送、未在 HP 部署 Go。下一步为 G3 来源、规范化与受限解析迁移。

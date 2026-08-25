# 邮箱连接器需求

## 1. 统一能力

邮箱 Provider 必须实现统一端口，不允许上层感知 Microsoft Graph、Gmail API 或 IMAP 细节。

```text
connectOrAuthorize()
getAccountProfile()
acquireMailCredential()
syncChanges(accountId, credentialHandle, opaqueCursor, since)
disconnect()
```

统一消息模型至少包含：

- Provider 消息 ID、跨游标重置去重键和线程 ID。
- 发件人、收件人、主题和原始时间。
- 文本正文和 HTML 正文引用。
- 附件文件名、Content-Type 和声明大小元数据；不包含附件字节。
- 会议邀请和 MIME 类型。
- 同步版本或变更标识。

## 2. Microsoft Graph（P0）

### 已确定配置

- 应用名称：Hughsean QQ Time Agent。
- 账户范围：组织目录账号和个人 Microsoft 账号。
- OAuth 租户段：`common`。
- 应用类型：移动和桌面公共客户端，允许 public client flow。
- 回调地址：`http://localhost:8000/oauth/microsoft/callback`。
- 权限类型：委托权限。
- Graph 权限：`User.Read`、`Mail.Read`。
- OAuth scopes：`openid profile email offline_access User.Read Mail.Read`。

### 授权流程

1. 所有者从 Ubuntu 生产主机浏览器打开 `http://127.0.0.1:8000/oauth/microsoft/owner-start`；
   短期签名会话由隐藏同源 POST 换取 `HttpOnly` 所有者 Cookie，不把会话放入 URL。
2. `/oauth/microsoft/start` 验证所有者 Cookie，生成 `state`、`nonce` 和 PKCE verifier。
3. 临时授权事务绑定用户、浏览器会话和过期时间。
4. 用户在 Microsoft 页面登录并同意权限。
5. 回调验证 `state`、错误参数和一次性使用状态。
6. 本机公共客户端使用授权码和 PKCE verifier 换取 token，不发送客户端密码。
7. 验证 ID token 的签名、issuer、audience、nonce 和时间声明。
8. Credential Vault 加密保存 refresh token。
9. Connections 保存 Provider 账号标识和 ACTIVE 状态。

Microsoft 应用不得创建或配置客户端密码；历史密码必须在 Entra 中撤销。

### 邮件同步

- 首次连接默认读取最近 7 天，最大范围由配置限制。
- 默认每 5 分钟触发一次增量同步；手动同步仍受去重、并发和限流约束。
- 同步只读取用户自己的邮箱，不读取组织内其他邮箱。
- Microsoft MVP 使用 Inbox 文件夹的 Graph delta；列表阶段只取标识、参与者、主题、时间和
  变更标识，写入前再按消息 ID 单独读取正文，不在 delta 列表中批量读取正文。
- 每一页完整落库、规范化后才原样保存 Provider 返回的 `nextLink`/`deltaLink`；任务中断后从
  已提交页继续，不记录或返回游标内容。
- 以 `(connection_id, provider_message_id)` 作为业务唯一键。同一 Provider 的多个邮箱使用
  HMAC 账号 fingerprint 去重连接，但完整账号标识不得进入日志、Job key 或跨模块引用。
- 429、5xx 和网络错误使用带抖动的指数退避。
- 401 在刷新一次后仍失败则标记 `REAUTH_REQUIRED`。
- 403 视为权限或组织策略问题，不进行无限重试。
- Graph 删除/移出 Inbox 的增量事件把 InboxItem 标记删除，正文查询立即不可用；来源追溯
  只保留脱敏发件人、Provider ID、主题、时间、状态和删除标志。

同步由 Web 端只负责幂等入队，Worker 独占执行；周期调度也写入同一数据库 Job Queue，使用
连接 ID 与时间桶作为幂等键。`FAILED_RETRYABLE` 的 InboxItem 会在同一 Provider 消息再次出现
时重新规范化，不创建第二个 InboxItem。

## 3. QQ 邮箱 IMAP（P1）

- 只允许本机回环页面中已认证的唯一所有者管理连接；同一所有者可连接多个 QQ 邮箱，每个
  Connection 独立查询状态、同步、重新认证和明确确认断开。
- 固定使用 `imap.qq.com:993`、TLS、系统受信 CA、主机名和证书校验；禁止明文、STARTTLS
  降级、跳过证书验证或切换任意 Host/Port。
- 用户提交完整 QQ 邮箱地址和邮箱设置中生成的 IMAP 授权码；不接收、不要求、不保存 QQ
  登录密码。授权码只进入 Credential Vault，Connections 仅保存 `credential_ref`。
- 连接时立即执行只读 TLS 登录和 `INBOX` 选择验证；支持 `ACTIVE`、`DEGRADED`、
  `REAUTH_REQUIRED`、`DISCONNECTED`。认证失败进入 `REAUTH_REQUIRED`，网络/超时/服务端临时
  错误有限重试，断开删除凭据并取消待执行同步 Job。
- 默认只读同步 `INBOX`。首次同步按 `MAIL_INITIAL_LOOKBACK_DAYS` 搜索，后续游标包含
  `UIDVALIDITY + last UID`。Provider 消息 ID 包含邮箱不可逆标识、文件夹、UIDVALIDITY 和 UID。
- UIDVALIDITY 变化时从配置回看窗口安全重扫；Inbox 另以 Message-ID，缺失时以确定性邮件指纹
  去重，因此不会因新 UID 命名空间重复创建已有业务记录，也不会跳过窗口内邮件。
- 首版复用数据库 Job Queue 与 `MAIL_SYNC_INTERVAL_SECONDS` 定时轮询，不实现永久 IMAP IDLE。
- IMAP Adapter 先读取 header 与 `BODYSTRUCTURE`，只按 MIME part 读取正文；附件只保存文件名、
  Content-Type 和声明大小，不下载、不解析、不索引附件内容。
- `imaplib`、`email.message`、BODYSTRUCTURE、UID、文件夹与连接对象只存在于 Adapter 内；阻塞
  IMAP 调用通过工作线程隔离。上层只接收统一 Mail Provider 模型和不可解释游标。

## 4. Gmail（P1）

- 使用 Gmail API 和 Google OAuth，不使用用户密码或 App Password。
- 目标权限为 `gmail.readonly`。
- 使用 `historyId` 做增量同步。
- 若所有者启用 Gmail，使用个人测试/内部授权范围并单独评估 Restricted Scope 要求；不为此扩展成公开多用户应用。
- Gmail 审核状态不得阻塞 Microsoft 和 QQ 邮箱模块。

## 5. 邮件内容安全

- 邮件正文永远是 T2 外部内容。
- 邮件中的“忽略规则”“调用工具”“删除日程”等文字只作为正文。
- HTML 邮件先清洗，禁止执行脚本、远程资源和内嵌表单。
- QQ 邮箱首版附件只保存元数据；附件内容处理仍不在范围内。
- 发送给 AI 前按用例最小化内容，去除不需要的签名、历史引用和跟踪元素。

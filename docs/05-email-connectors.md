# 邮箱连接器需求

## 1. 统一能力

邮箱 Provider 必须实现统一端口，不允许上层感知 Microsoft Graph、Gmail API 或 IMAP 细节。

```text
beginAuthorization()
completeAuthorization()
refreshAuthorization()
getAccountProfile()
listRecentMessages()
getMessage()
getAttachments()
syncChanges()
disconnect()
```

统一消息模型至少包含：

- Provider 消息 ID 和线程 ID。
- 发件人、收件人、主题和原始时间。
- 文本正文和 HTML 正文引用。
- 附件元数据。
- 会议邀请和 MIME 类型。
- 同步版本或变更标识。

## 2. Microsoft Graph（P0）

### 已确定配置

- 应用名称：Hughsean QQ Time Agent。
- 账户范围：组织目录账号和个人 Microsoft 账号。
- OAuth 租户段：`common`。
- 回调地址：`https://agent.hughsean.online/oauth/microsoft/callback`。
- 权限类型：委托权限。
- Graph 权限：`User.Read`、`Mail.Read`。
- OAuth scopes：`openid profile email offline_access User.Read Mail.Read`。

### 授权流程

1. 所有者从 Windows 本机回环地址打开 `/oauth/microsoft/owner-start`；短期签名会话先由
   隐藏同源 POST 提交，再以 HTTP 307 原样转发到公网 HTTPS，换取 `Secure`、`HttpOnly`
   所有者 Cookie；页面使用 CSP nonce 受控脚本自动提交并保留按钮回退，不把会话放入 URL。
2. `/oauth/microsoft/start` 验证所有者 Cookie，生成 `state`、`nonce` 和 PKCE verifier。
3. 临时授权事务绑定用户、浏览器会话和过期时间。
4. 用户在 Microsoft 页面登录并同意权限。
5. 回调验证 `state`、错误参数和一次性使用状态。
6. 后端使用授权码、PKCE verifier 和客户端凭据换取 token。
7. 验证 ID token 的签名、issuer、audience、nonce 和时间声明。
8. Credential Vault 加密保存 refresh token。
9. Connections 保存 Provider 账号标识和 ACTIVE 状态。

客户端密码只存在于服务器凭据存储，不进入数据库普通配置表和源代码。

### 邮件同步

- 首次连接默认读取最近 7 天，最大范围由配置限制。
- 默认每 5 分钟触发一次增量同步；手动同步仍受去重、并发和限流约束。
- 同步只读取用户自己的邮箱，不读取组织内其他邮箱。
- Microsoft MVP 使用 Inbox 文件夹的 Graph delta；列表阶段只取标识、参与者、主题、时间和
  变更标识，写入前再按消息 ID 单独读取正文，不在 delta 列表中批量读取正文。
- 每一页完整落库、规范化后才原样保存 Provider 返回的 `nextLink`/`deltaLink`；任务中断后从
  已提交页继续，不记录或返回游标内容。
- 以 `(connection_id, provider_message_id)` 作为业务唯一键。
- 429、5xx 和网络错误使用带抖动的指数退避。
- 401 在刷新一次后仍失败则标记 `REAUTH_REQUIRED`。
- 403 视为权限或组织策略问题，不进行无限重试。
- Graph 删除/移出 Inbox 的增量事件把 InboxItem 标记删除，正文查询立即不可用；来源追溯
  只保留脱敏发件人、Provider ID、主题、时间、状态和删除标志。

同步由 Web 端只负责幂等入队，Worker 独占执行；周期调度也写入同一数据库 Job Queue，使用
连接 ID 与时间桶作为幂等键。`FAILED_RETRYABLE` 的 InboxItem 会在同一 Provider 消息再次出现
时重新规范化，不创建第二个 InboxItem。

## 3. QQ 邮箱 IMAP（P1）

- 使用 `imap.qq.com:993` 和 TLS。
- 用户只提交 QQ 邮箱授权码，不提交 QQ 登录密码。
- 授权码由 Credential Vault 加密保存。
- 使用 IMAP UID/UIDVALIDITY 作为同步依据。
- 首版采用定时轮询，不依赖永久 IDLE 长连接。
- IMAP Adapter 不得向上暴露文件夹命名、MIME 库类型或连接对象。

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
- 附件在独立隔离流程中解析，并限制大小、类型和资源消耗。
- 发送给 AI 前按用例最小化内容，去除不需要的签名、历史引用和跟踪元素。

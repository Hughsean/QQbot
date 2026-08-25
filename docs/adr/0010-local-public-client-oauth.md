# ADR-0010：Microsoft OAuth 使用本机公共客户端回环回调

- 状态：Accepted
- 日期：2026-08-13
- 取代：ADR-0004 中未明确的客户端类型，以及 OD-10 的 Agent 公网入口部分

## 背景

QQ Time Agent 只供所有者本人使用，Web、Worker 和浏览器均运行在同一台生产主机。
Microsoft Graph 只需要用户委托的只读邮件权限。原方案把应用注册为机密 Web 客户端，使用
`agent.hughsean.online` 接收回调，并依赖腾讯云 Caddy、SSH 反向隧道和客户端密码。这增加了
公网攻击面、证书与隧道运维，但没有带来单用户本机场景所需的能力。

## 决策

- Microsoft 应用注册为“移动和桌面应用”公共客户端。
- 使用 Authorization Code Flow + PKCE、OIDC `nonce` 和一次性 `state`。
- 回调 URI 固定为 `http://localhost:8000/oauth/microsoft/callback`，仅由绑定
  `127.0.0.1:8000` 的本机 Web 进程接收。
- 公共客户端不配置、不读取也不发送客户端密码或证书。
- OAuth start、callback、所有者会话和连接管理 HTTP 路由全部拒绝非回环 Host。
- refresh token 继续由 Credential Vault 加密保存；离线邮件同步方式不变。
- 腾讯云不再提供 Agent 反向代理，Windows 不再运行 SSH 反向隧道守护角色。

## 结果

- `agent.hughsean.online` 不再是系统依赖，可删除其 DNS 记录和 Caddy 站点。
- Microsoft 仍要求注册一个重定向 URI，但它是本机回环 URI，不是公网地址。
- 授权必须在运行 Agent 的生产主机浏览器中完成；不能从手机或另一台电脑完成回调。
- 固定端口与 Web 进程生命周期绑定，避免额外临时 HTTP Server；端口被占用时 readiness 失败，
  不会回退到公网回调。
- Azure 中遗留的 Web 重定向 URI和客户端密码应删除；已生成的客户端密码应撤销。

## 验收

- Settings 根据本机监听端口生成固定 HTTP localhost callback，不接受 `.env` 覆盖。
- MSAL 使用 `PublicClientApplication`，授权 URL 仍包含 S256 PKCE、state、nonce 和最小权限。
- 本机授权、callback、状态和断开路由的非回环请求返回 404。
- 仓库、任务守护和腾讯云 Caddy 中不再存在 Agent 公网反代或反向隧道依赖。

# Microsoft 本机 OAuth 与腾讯云清理报告

变更日期：2026-08-13。决策来源：ADR-0010。

## 1. 已完成

- Microsoft Adapter 从 MSAL `ConfidentialClientApplication` 改为
  `PublicClientApplication`，不再加载或发送客户端密码。
- callback 由监听端口确定性生成：
  `http://localhost:8000/oauth/microsoft/callback`。
- owner session、OAuth start/callback、连接状态和断开路由全部增加回环 Host 门禁。
- 本机 HTTP Cookie 不再错误依赖公网 HTTPS；会话仍为 `HttpOnly`、`SameSite=Lax`、短期有效。
- Windows 进程守护制品移除 Tunnel 角色，只保留 Web、Worker、QQ。
- 腾讯云 Caddy 已移除 `agent.hughsean.online` 反向代理；旧配置备份为
  `/etc/caddy/Caddyfile.pre-local-oauth-20260813`。
- 唯一匹配 `127.0.0.1:8000:127.0.0.1:8000` 的本机 SSH 反向隧道已停止；腾讯云
  8000 端口不再监听。
- 主站 `https://hughsean.online/` 在切换后保持 HTTP 200。

## 2. 验证证据

- 全量测试：231 passed、8 个显式外部沙箱用例默认跳过。
- 总覆盖率：85.53%，高于 80% 门禁。
- Ruff format、Ruff lint/McCabe、mypy strict 和架构/运维门禁通过。
- Microsoft 显式授权元数据沙箱通过，授权 URL 保留 `state`、OIDC `nonce`、S256 PKCE
  和 `openid profile offline_access email User.Read Mail.Read` 范围。
- 重启后的本机 Web readiness 为 `ready`；8000 仅绑定 `127.0.0.1`；本机 OAuth 页面返回
  200，伪造 `Host: agent.hughsean.online` 返回 404。
- 腾讯云活动 Caddy 配置验证通过，Caddy 为 active，8000 无监听；主站返回 200。

## 3. Microsoft Entra 控制台验证

所有者确认后已完成应用注册迁移：

- Authentication 显示 0 个 Web 回调、0 个 SPA、1 个公共客户端。
- 唯一回调是移动和桌面应用平台的
  `http://localhost:8000/oauth/microsoft/callback`。
- Allow public client flows 已启用；隐式授权的 Access Token 和 ID Token 保持关闭。
- 原 `https://agent.hughsean.online/oauth/microsoft/callback` 已删除。
- 客户端凭据显示 0 个证书、0 个客户端密码；原 `QQ Time Agent MVP` 密码已成功撤销。

未执行真实 Microsoft 重连或读取邮件，连接继续保持 `DISCONNECTED`。本地 `.env` 中如仍有历史
`MICROSOFT_CLIENT_SECRET` 字段，新代码会忽略它；所有者可以只删除该字段，不需要提供替代值。

## 4. 可选 DNS 清理

`agent.hughsean.online` 已不再被 Caddy 接受，也不再是项目依赖。DNSPod 中的 `agent` 记录可
删除，以减少误导；即使暂时保留，也不会恢复 Agent 反向代理。

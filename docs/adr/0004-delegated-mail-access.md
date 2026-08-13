# ADR-0004：邮箱首版使用用户委托的只读权限

- 状态：Accepted
- 日期：2026-08-12

## 背景

Agent 需要在用户离线时同步自己的邮件，但不需要读取组织内其他人的邮箱，也不需要修改或发送邮件。

## 决策

Microsoft Graph 使用 OAuth 委托权限 `Mail.Read` 和 `offline_access`。不申请 Application `Mail.Read`、`Mail.ReadWrite` 或 `Mail.Send`。

## 结果

- 每位用户独立授权，权限范围限制在该用户可访问的数据。
- refresh token 必须加密保存，并支持撤销和重新授权。
- 如果未来出现共享邮箱或组织级场景，必须新建 ADR，不得直接扩大权限。

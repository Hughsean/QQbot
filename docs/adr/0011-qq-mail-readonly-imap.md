# ADR-0011：QQ 邮箱使用只读 TLS IMAP 与统一邮件流水线

- 状态：Accepted
- 日期：2026-08-13

## 背景

阶段 8 后，所有者明确决定扩展 QQ 邮箱。QQ 邮箱面向个人账号提供 IMAP 授权码，没有本项目
可用的只读 OAuth API。现有 Microsoft Graph 流水线已具备 Credential Vault、数据库 Job Queue、
Inbox 幂等、T2 信任、Understanding、RAG、保留和 tombstone，但统一契约仍隐含 access token 与
Graph URL 游标，不能直接承载 IMAP。

## 决策

- 固定连接 `imap.qq.com:993`，使用系统受信 CA、主机名/证书验证和只读 `INBOX`；不允许配置
  明文 IMAP、任意服务器、跳过验证、STARTTLS 降级或永久 IDLE。
- 所有者只提交完整 QQ 邮箱地址和邮箱生成的 IMAP 授权码。授权码作为
  `IMAP_AUTH_CODE` 进入 Credential Vault；Connections 只保存 `credential_ref`。
- 统一 Mail Port 使用账号标识、不可序列化凭据句柄和不透明 cursor。IMAP UID、UIDVALIDITY、
  BODYSTRUCTURE、MIME/连接对象只存在于 `qq_mail_imap` Adapter。
- 游标记录 UIDVALIDITY 与最后提交 UID。UIDVALIDITY 变化后按初始回看窗口重扫；Inbox 以
  Message-ID 或确定性邮件指纹作为第二幂等键，Provider ID 则包含邮箱不可逆标识、INBOX、
  UIDVALIDITY 和 UID，兼顾追溯与不重复创建。
- 使用 header 与 BODYSTRUCTURE 确定正文部件，只读取 text/plain、text/html；附件仅保存文件名、
  Content-Type 和声明大小，不下载内容。
- 标准库阻塞 IMAP 调用放入工作线程；网络/超时/认证/临时服务端错误分类并有限重试。
- QQ 邮件固定为 `QQ_MAIL`/T2，复用现有 Normalization、Understanding、RAG 和 365 天保留。
  断开取消待执行 Job、删除凭据，并通过模块清理端口为该连接每个来源记录/重放 tombstone。

## 结果

- 不新增第三方 IMAP/MIME 依赖，Microsoft Graph Adapter 保持独立并继续满足同一邮箱端口。
- 对 UIDVALIDITY 重置会发生有界回扫和额外只读流量，但不会把已存在邮件重复创建为业务记录。
- 缺少 Message-ID 的邮件使用确定性 header/正文指纹；极端情况下内容完全相同的重复投递会被
  合并，这是比重复创建日程更安全的单用户取舍，并通过审计可见。
- QQ 邮箱真实沙箱是完成门槛；缺少地址/授权码时只能等待所有者配置，不能宣布完成。

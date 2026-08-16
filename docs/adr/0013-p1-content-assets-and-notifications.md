# ADR-0013：统一内容资产、多邮箱与主动通知扩展

- 状态：Accepted
- 日期：2026-08-14

## 背景

阶段 9 已交付 QQ 邮箱只读 IMAP，但附件只保存元数据；QQ 入站只接收直接/转发文本；每个所有者
每个 Provider 只能有一个 Connection。P1 需要增加 QQ 图片、截图和合并转发、PDF/邮件附件、
多邮箱、每日摘要、冲突提醒、授权失效提醒和标准 ICS 确定性解析。

这些能力共享来源版本、去重、信任分层、有限重试、删除传播和 RAG 引用。如果分别在 QQ/IMAP
Adapter 内实现解析，会让 Provider DTO、文件正文和副作用绕过 Inbox、Normalization、Actions 与
Data Lifecycle 边界。

## 决策

### 统一来源资产

- Inbox 拥有 `SourceAsset` 元数据；二进制只经 `BlobStorePort` 写入受限本机 volume，不进入
  PostgreSQL 正文列、LangGraph State、日志或审计 payload。
- 每个资产归属于一个 InboxItem，记录 Provider 资产 ID、类型、声明/检测 MIME、大小、SHA-256、
  storage key、抓取/解析状态、解析器版本、信任等级和清理期限。
- 原始二进制在成功解析或终态失败后最多保留 24 小时；规范化文本沿用来源 365 天策略。主动删除
  立即阻断抓取/解析/检索，并通过模块清理端口删除 blob、规范化结果、chunk 和向量。
- Provider Adapter 只产生描述符和执行受限抓取；Normalization 负责确定性解析；Understanding/Knowledge
  只消费规范化文本和来源引用。

### 信任与解析

- 所有 OCR、附件、PDF、ICS 和合并转发节点内容固定为 T2；所有者 QQ caption 可以作为 T1 意图，
  但嵌入资产中的指令无权执行。
- 首批允许类型为 PDF、text/plain、text/calendar、PNG、JPEG 和 WebP；其他类型只保留元数据。
  禁止可执行文件、宏、压缩归档和递归嵌套。
- ICS 使用 RFC 5545 解析器确定性提取 UID、SEQUENCE、METHOD、时间、TZID、参与人和重复信息。
  REQUEST/更新只形成 EventCandidate，CANCEL 只形成待确认取消建议，不能直接修改 Agenda。
- PDF 文本提取和本地 OCR 经独立 Port，必须有文件大小、页数、像素、执行时间和输出长度上限。

### 多邮箱

- Connection 从 `UNIQUE(user_id, provider)` 迁移为一个用户可拥有同 Provider 多连接；账号身份以
  Provider 返回的稳定账号 ID 计算 HMAC fingerprint，不把完整邮箱地址写入日志或幂等键。
- 所有同步游标、Job、Inbox 去重、凭据、限流和删除传播继续以 `connection_id` 隔离；每个连接
  具有所有者可见 label、默认标记、同步开关和 capabilities。
- Microsoft 与 QQ Mail 均复用该模型。现有单连接数据原地回填，迁移不得断开连接或复制凭据。

### 主动通知

- Notifications 拥有持久化 `NotificationIntent`、模板版本、幂等键和 cooldown，不直接查询其他
  模块表。Agenda/Scheduling、Connections 和定时 Briefing 用公开契约或 Outbox 产生通知意图。
- 每日摘要首版使用确定性模板；冲突按 Agenda ID/版本对去重；Connection 首次转为
  `REAUTH_REQUIRED` 时提醒一次，24 小时未恢复才允许再次提醒。
- 所有通知受所有者时区、开关和静默时段约束；模型无权决定是否发送或修改业务状态。
- Worker 只幂等生成持久化意图；QQ 进程使用 `FOR UPDATE SKIP LOCKED` 租约领取并在发送前重新校验
  Agenda、Connection 和偏好事实。来源已删除、冲突已解决、授权已恢复或开关关闭时取消待发意图。
- QQ 主动消息没有请求级幂等 token。租约过期、超时或 provider 结果未知时记为 `AMBIGUOUS` 且不自动
  重发；仅明确发生在发送前的失败才允许有限重试，避免把至少一次执行误宣称为 provider exactly-once。

### QQ 官方能力边界

- 只使用 QQ 开放平台和官方 `qq-botpy` 提供的资源描述与下载能力。若 C2C 图片或合并转发 API
  权限不足，该子能力保持不可用并报告明确状态，不引入 OneBot、NapCat 或其他非官方协议。
- QQ CDN 抓取只接受 Adapter 从官方事件得到的受限 URL/资源 ID，禁止抓取用户文本或模型输出中的
  任意 URL，防止 SSRF。
- 当前官方 `qq-botpy` 事件模型公开图片 `attachments`，但未公开合并转发节点模型。实现保留有界、
  稳定顺序的 Provider-neutral 节点规范化契约；在官方事件/权限缺失时明确报告不可用，不猜测私有
  payload，也不接入非官方协议。

## 结果

- P1 保持模块化单体；只增加明确的数据所有权和 Port，不建立 Provider 专属业务管线。
- 引入二进制解析攻击面和本机 volume 备份/清理责任；必须以资源上限、MIME sniff、超时、T2 信任、
  终态失败和删除传播测试约束。
- 多连接会扩大同步和通知数量；必须按 connection 限流并在 UI/QQ 命令中要求显式连接标识。
- Gmail 仍保持关闭，不属于本 ADR 的实现范围。

## 验收

- migration 从 0013 升级/降级/重建通过，现有 Microsoft/QQ Mail 连接和凭据引用不变。
- 同一 Provider 可建立两个隔离连接；同步、断开和删除不影响另一连接。
- ICS 时区、更新、取消、重复实例和恶意字段 fixture 通过；任何解析结果都不能绕过确认门禁。
- PDF/OCR/QQ 媒体满足大小、超时、T2、去重和删除传播门禁；日志不含正文、文件名或 URL。
- Daily Digest、冲突和重新授权提醒具备确定性内容、幂等、cooldown、静默时段与重启恢复测试。
- Ruff、mypy strict、架构、单元、契约、PostgreSQL 集成与显式 QQ/邮箱沙箱全部通过。

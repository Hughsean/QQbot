# Go 全功能迁移与验收

## 范围和当前状态

所有者于 2026-10-18 选择完整迁移现有功能和数据，按阶段验证；没有公网服务器。
ADR-0017 是当前开发栈决策。原阶段 1–18 是功能验收基线，不因换语言重新解释需求。
本文件的 G 阶段是迁移顺序，不能把尚未移植的功能默认为不需要。

仓库起点有 525 个受 Git 管理的 Python 文件、601 个静态测试函数（579 个业务/集成/契约/沙箱测试和 22 个架构测试，不含参数化展开）。
所有者于 2026-10-19 要求新分支删除旧实现：Go 分支只保留 Go，原实现和完整测试保存在
`Main@c63eae17adf4fc2cf26c694ae8ba7e7f23c93470`；[历史测试清单](go-legacy-test-inventory.json) 保留逐项移植依据。
默认 Compose 已改为独立 Go 开发环境，不含尚未迁移的 Worker/QQ 业务角色，不能视为生产替代。
HP 旧应用容器已按所有者授权停止但未删除。以下“待验收”不是完成声明。

## 阶段顺序

| 阶段 | 对应功能和数据 | 必须通过的门禁 | 状态 |
|---|---|---|---|
| G0 决策 | 开发栈、模块、SDK、无公网约束 | ADR、依赖版本、迁移清单一致 | 已冻结 |
| G1 基础 | Bootstrap、配置、脱敏、Clock、健康、SQL 基线、Job、botgo 边界 | 构建、静态分析、单元/架构、空库建表与拒绝未核验接管、Ollama 契约、QQ 沙箱收发/重连 | 已通过；证据见文档 33 |
| G2 账号 | Identity、Connections、Credential Vault、Microsoft PKCE/OIDC、QQ IMAP 授权 | AES-GCM 双向互通、OAuth state/nonce/CSRF、刷新/断开、多连接隔离 | 本地实现与自动化门禁已通过；真实账号沙箱待授权，见文档 34 |
| G3 来源 | Inbox、Normalization、邮件 delta/UID、资产、ICS/PDF/图片/OCR/转发 | 幂等、只读、解析资源上限、TLS、DST、删除传播、容器解析 | 待迁移 |
| G4 理解 | AI Gateway、DeepSeek、Understanding、Workflow | 结构化输出拒绝未知字段、注入隔离、预算、checkpoint 恢复与固定评估 | 待迁移 |
| G5 日程 | Agenda、Scheduling、Calendar System、Actions、确认/撤销 | 版本冲突、硬约束、并发幂等、审计、Outbox、部分成功恢复 | 待迁移 |
| G6 交互 | Agent 会话、快照/分层摘要、turn 合并、QQ 文本/按钮、Reminder、Notifications | 同会话串行、T1/T2 分离、到期租约、推迟/完成、静默窗、未知投递不重发 | 待迁移 |
| G7 检索 | Knowledge、Embeddings、Retrieval、RAG 工具 | 1024 维、混合检索 Recall@10≥0.85、来源引用、空查询、删除不可召回 | 待迁移 |
| G8 运维 | Data Lifecycle、Audit、保留、备份/恢复、每日摘要、指标 | tombstone 重放先于服务、追加式审计、备份恢复与秘密扫描 | 待迁移 |
| G9 投影 | Task Projection、Graph 列表/delta/对账、发送前完成门禁 | 外部只回流完成、3 秒预算、失败继续 QQ、完成竞态与不确定创建恢复 | 待迁移 |
| G10 切换 | Go Web/Worker/QQ 镜像、原运维入口和完整数据副本 | 原 1–18 功能验收、全量测试、核心覆盖≥90%/总体≥80%、竞态、实际副本摘要一致、回滚演练 | 待迁移 |

每阶段自动化验收完成才进入下一阶段；未通过的外部门禁必须明确记录，不以 skip 冒充通过。
G1 的 QQ 发送只可用于显式授权的沙箱，不能在普通单元测试中读取真实 `.env` 或连接生产账号。

## 数据与行为对照

- 每个模块保留自己的数据所有权，Go 使用 `internal/modules/<module>/{contracts,domain,application,infrastructure}`，只创建实际使用的层。
- 跨模块仅 contracts/明确公开 port；通过 Bootstrap 装配，禁止全局可变容器。SDK 全局 handler 和无状态协议 filter 只可在进程初始化安装，业务用例不访问它。
- 源 UUID、版本、幂等键、Job/Outbox 状态、delta/UID 游标、通知回执、Reminder occurrence、Agent checkpoint 和 tombstone 不丢弃、不重置。
- 时间沿用 timestamptz 与 IANA 时区；当前时间通过 Clock 注入，测试使用固定时间。
- 原 AES-GCM 使用 12 字节 nonce、32 字节 key、`<credential UUID>:<kind>:1` AAD；Go 必须能解密 Python fixture，Python 必须能解密 Go fixture。
- 原 HTTP 路由、状态码、所有者会话、CSRF、回环 Host 和脱敏行为作为契约。G10 在实际数据库副本上核对全部表/列/约束/默认值/索引与向量索引；此前迁移工具拒绝接管未核验的原库。
- G2 提供账号内核与 HTTP Adapter；G3 来源删除、G8 审计/恢复等端口先做契约验证，实际 Bootstrap 装配必须等待对应真实模块，禁止生产 no-op。G2 真实 Provider 探针独立且不持久化凭据。
- PDF、OCR、图片和 ICS 的依赖选型在 G3 记录；不可临时降为“仅文本”后声称完整迁移。
- 所有原 unit、contract、integration、end_to_end 场景必须在迁移报告中映射到 Go 测试或明确的外部验收，不能只按文件数计完成率。

## 开发和验证

```text
go test ./...
go vet ./...
go build ./cmd/qq-time-agent
```

Go 工程独立存在于根目录 go.mod 与 cmd/internal。开发命令不会自动读取 `.env`，只有运行应用 Bootstrap 才会读取。
隔离数据库集成通过专用测试 Compose 和显式合成配置运行，不沿用当前开发者的数据库密码或账号。
生产 `.env` 不变更、不输出；未完成 G10 前不运行生产迁移，不同时启动两个消费者处理同一数据库。
真实 QQ 沙箱已获本次会话明确授权；探针命令 `go run ./cmd/qq-time-agent qq-sandbox --allow-send`，
最多向所有者发送 3 条固定消息、只接受 T1 的 `go-migration-probe`，不访问业务数据库。

## 迁移报告

每次报告必须列出实际完成模块、运行过的检查、未通过的门禁与下一阶段；“选型已改为 Go”“Go 基础已运行”和“全功能已迁移”是不同状态。

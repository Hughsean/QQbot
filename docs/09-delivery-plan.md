# 交付计划

## 阶段 0：需求和边界冻结

交付物：

- 产品范围和不做清单。
- 模块边界和数据所有权。
- 安全模型、领域模型和接口契约。
- 单用户范围、内部日程、RAG 边界、Microsoft 应用注册和 HTTPS 基础设施。

完成标准：文档无冲突，所有后续实现都能归属到唯一模块。

## 阶段 1：基础骨架

交付物：

- 项目结构、配置加载、日志脱敏。
- `pyproject.toml`、`.python-version`、`uv.lock` 和项目内 `.venv`。
- Python 3.12 与 QQ 官方 SDK 的沙箱网关、C2C 收发和重连测试；已记录 Python 3.14 Client 初始化不兼容。
- Web/Worker 进程和健康检查。
- PostgreSQL + pgvector、数据库迁移、Outbox/Job 基础设施。
- Windows 本机 Ollama `qwen3-embedding:4b` 健康检查、冷/热启动和 1024 维契约测试。
- Data Lifecycle、Tombstone、模块级清理端口和保留策略配置骨架。
- 架构边界测试。

完成标准：部署到服务器后 `agent.hughsean.online/health/ready` 正常，未接入任何真实用户数据。

## 阶段 2：Microsoft 账号连接

交付物：

- OAuth start/callback/disconnect。
- Credential Vault。
- Connections 状态机。
- Graph 账号信息读取。

完成标准：自己的 Outlook 账号可以连接、刷新、断开；数据库和日志中找不到明文 token。

## 阶段 3：邮件收件箱

交付物：

- 最近邮件读取和增量同步。
- MIME/正文规范化。
- Inbox 去重、重试和状态机。
- 邮件来源追溯视图。

完成标准：重复同步不产生重复 InboxItem，授权失效能正确进入 `REAUTH_REQUIRED`。

## 阶段 4：理解能力

交付物：

- Event/Task/无关信息分类。
- 时间解析、结构化提取和 schema 校验。
- 提示注入隔离和低置信度处理。

完成标准：去敏固定测试集的分类准确率不低于 90%、Event/Task 结构化提取准确率不低于
85%、提示注入隔离样例通过率为 100%；任何模型输出都不能直接形成 Action。

## 阶段 5：内部日程与排程

交付物：

- Agenda 内部日程、忙闲查询、用户偏好和 Scheduling Proposal。
- 冲突解释和备选时间。

完成标准：Proposal 遵守硬约束，Task 与 Event 语义保持分离。

## 阶段 6：QQ 确认闭环

交付物：

- QQ 直接输入和转发文本。
- Proposal 确认、修改、拒绝。
- Actions 幂等写内部日程、结果通知和撤销。
- Reminder 持久化调度、主动提醒、完成和推迟。

完成标准：三个核心场景端到端通过，重复确认不会创建重复事件。

## 阶段 7：RAG

交付物：

- Knowledge 来源版本、确定性清洗和切块。
- Ollama Embedding Adapter 和 pgvector 索引。
- 向量、关键词、元数据过滤的混合检索和来源引用。
- 删除同步、索引重建和固定检索评估集。

完成标准：检索结果可追溯；删除来源后不可再召回；RAG 不能修改日程或绕过确认；去敏固定评估集的混合检索 Recall@10 不低于 0.85。

## 阶段 8：个人试用与加固

交付物：

- 隐私政策、数据删除说明和用户授权说明。
- 监控、告警、备份恢复演练。
- 项目所有者本人真实使用和指标收集。

完成标准：安全检查通过，错误创建和撤销率处于可接受范围，再决定是否扩展 Gmail、QQ 邮箱和附件。

## 实施顺序约束

- 不得在 Credential Vault 完成前保存真实 refresh token。
- 不得在 Inbox 去重完成前启用周期性邮件同步。
- 不得在确认和 Actions 门禁完成前启用内部日程写入。
- 不得在来源版本、删除传播和引用契约完成前把 RAG 用于正式回答。
- 不得通过统一清理任务跨模块直接删表；所有删除必须调用数据所有模块的清理端口。
- 不得为赶进度让 Provider DTO 或 SDK 穿透模块边界。
- 所有环境都不得关闭所有者 QQ 身份白名单；测试其他身份必须使用隔离的假 Provider。

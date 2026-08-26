# 模块边界

## 1. 架构形态

MVP 采用模块化单体，而不是微服务。所有模块可以在同一进程和仓库中部署，但必须保持独立命名空间、独立数据所有权和显式契约，使未来拆分不需要重写领域逻辑。

每个业务模块内部采用：

```text
domain        纯业务规则
application   用例编排和端口定义
infrastructure 数据库、SDK、HTTP 等适配器
api           对外控制器和 DTO 映射
```

## 2. 模块清单

| 模块 | 唯一职责 | 拥有的数据 | 不负责 |
|---|---|---|---|
| Identity | 唯一所有者身份、QQ 白名单、偏好 | 单用户、身份映射、偏好 | OAuth token、邮件、排程 |
| Connections | 外部连接生命周期和能力 | 多连接元数据、账号 fingerprint、授权状态 | 保存明文凭据、同步邮件 |
| Credential Vault | 加密保存和读取凭据 | 密文、密钥版本、凭据引用 | 业务状态、OAuth 页面 |
| Inbox | 原始信息信封、资产、去重、处理状态 | InboxItem、原始内容引用、SourceAsset 元数据 | AI 理解、执行操作、解析文件 |
| Normalization | MIME、文本、ICS、PDF/OCR、转发记录的确定性统一化 | 规范化结果、解析版本 | 判断用户意图、排程、抓取 Provider 资产 |
| Understanding | 分类和结构化候选提取 | Event/Task 候选、提取依据 | 直接访问 Provider、执行操作 |
| Workflow | 使用 LangGraph 推进用例、追问和确认 | Graph checkpoint 引用、等待状态 | 充当业务事实源、Provider SDK |
| AI Gateway | 统一模型调用、结构化输出、限流和用量 | 调用元数据、Prompt 版本 | 保存业务聚合、执行工具副作用 |
| Knowledge | 来源切块、索引生命周期、可追溯知识 | KnowledgeSource、KnowledgeChunk、索引版本 | 保存日程事实、生成最终答案 |
| Retrieval | 混合召回、过滤、融合和引用 | 查询记录、检索评估数据 | 修改来源、决定业务状态 |
| Embeddings | 嵌入生成端口、模型/维度契约 | 嵌入调用元数据 | 自行切块、访问 DeepSeek、保存日程 |
| Scheduling | 约束求解和 Proposal 生成 | Proposal、约束快照 | 写内部日程、发 QQ 消息 |
| Agenda | 项目内权威日程和忙闲查询 | AgendaEntry、日程版本 | 理解自然语言、发送提醒 |
| Calendar System | 日程工具边界、目标解析、授权和策略校验 | 日程工具契约，不持有日程事实 | 模型推理、直接写 Agenda/Reminder、Provider SDK、凭据 |
| Reminders | 提醒计划、到期租约、重试和死信 | Reminder、执行租约 | 改写日程、直接依赖 QQ SDK |
| Actions | 所有日程副作用门禁、幂等执行、提醒一致性和撤销 | ActionRequest、执行结果 | 自行决定用户意图 |
| Notifications | 规划、渲染并发送 QQ 通知 | 通知意图、投递记录、模板版本、cooldown | 修改 Proposal、Connection 或 Agenda 状态 |
| Data Lifecycle | 计算保留期限、删除编排、删除记录重放 | Tombstone、PurgeRun、保留策略版本 | 直接跨模块删表、保存业务正文 |
| Audit | 追加式审计和可追溯视图 | 审计记录 | 业务决策、凭据 |
| Provider Adapters | Microsoft、QQ、DeepSeek、Ollama SDK/HTTP 适配 | Provider 特定游标可由所属模块托管 | 跨 Provider 业务编排 |

## 3. 数据所有权

模块只能通过自己的 Repository 访问自己拥有的数据表。即使部署在同一数据库中，也禁止跨模块直接查询或写表。

| 数据 | 所有者 | 其他模块访问方式 |
|---|---|---|
| 用户偏好 | Identity | `UserPreferencesPort` |
| 连接状态 | Connections | `ConnectionQueryPort` |
| token/授权码 | Credential Vault | 短生命周期 `CredentialHandle` |
| 原始邮件/消息 | Inbox | `InboxContentPort`，按授权读取 |
| 提取候选 | Understanding | 候选查询契约 |
| AI 调用元数据 | AI Gateway | `ModelInvocationQueryPort` |
| 知识来源和片段 | Knowledge | `KnowledgeQueryPort`、来源事件 |
| 向量生成契约 | Embeddings | `EmbeddingPort` |
| Proposal | Scheduling | Proposal 命令/查询契约 |
| 内部日程 | Agenda | Busy/Free 和 Agenda 命令/查询契约 |
| 提醒计划 | Reminders | Reminder 命令/查询契约 |
| 副作用执行记录 | Actions | Action 查询契约 |
| 删除标记和清理运行 | Data Lifecycle | `RetentionPort`、模块级 `PurgePort` |
| 审计记录 | Audit | 只追加接口 |

## 4. 允许的依赖方向

```text
API / Worker
     ↓
Application Use Cases
     ↓
Domain

Infrastructure ──实现──► Application Ports
Provider SDK 只允许出现在 Infrastructure / Provider Adapters
```

业务模块之间不得导入对方的 `domain` 或 `infrastructure`。跨模块协作只能使用：

1. 对方公开的 application contract。
2. 稳定的领域事件。
3. 只读查询端口。

### 事务边界

- 一个数据库事务只能由一个模块拥有。
- Workflow 可以编排多个模块用例，但不能持有跨模块事务。
- 跨模块状态传播使用领域事件和 Transactional Outbox。
- 消费事件必须幂等，并记录已处理的事件 ID。
- 查询若需要组合多个模块的数据，应使用专用 Read Model，不得通过跨模块 JOIN 绕过所有权。
- Data Lifecycle 只能发布到期/删除命令并收集结果；实际删除由数据所有模块在自己的事务中完成。

### 可见性边界

- 每个模块只有 `api`/`contracts` 包可被外部模块导入。
- `domain`、`application/internal` 和 `infrastructure` 默认包级私有。
- 依赖装配只在 `bootstrap` 中进行，业务模块不得充当 Service Locator。
- 共享代码只允许是无业务语义的基础类型；一旦包含业务规则，就必须归属明确模块。

## 5. 端到端依赖图

```text
QQ Adapter ─┐
Mail Adapter ├─► Inbox ─► Normalization ─► Understanding ─► Workflow
File Adapter┘              │                                │
                           └─► Knowledge ─► Retrieval ───────┤
                                    │                       ▼
                             Embeddings/Ollama       Scheduling ◄── Agenda Busy/Free
                                                           │
User Confirmation ─────────────────────────────────────────┤
                                                           ▼
                                                     Actions ─► Agenda
                                                                  │
                                                            Reminders
                                                                  │
                                                            Notifications ─► QQ

Connections ─► Credential Vault  （供各 Provider Adapter 通过受控句柄使用）
Audit ◄── 接收所有关键领域事件
```

## 6. 严格禁止事项

- QQ Controller 不得直接调用 Microsoft Graph、Agenda Repository、DeepSeek 或 Ollama。
- 邮件 Connector 不得创建 Event、Task、Proposal 或内部日程。
- Understanding 不得读取 token、数据库其他模块表或调用外部写 API。
- LangGraph State 不得替代领域聚合或成为业务事实源，只保存工作流状态和领域对象引用。
- LangChain/LangGraph 的 Message、Tool、Runnable 等类型不得进入领域层或跨模块契约。
- Scheduling 不得发送 QQ 消息或写入内部日程。
- Agent 只能调用 Calendar System 的公开工具；Calendar System 只通过 Actions 写 Agenda/Reminder，并拒绝未授权、歧义、冲突或过期请求。
- QQ 与邮件入口只能创建幂等 AgentRun；不得在 Controller 中同步形成不可恢复的唯一执行路径。
- RAG/Retrieval 不得充当 Agenda、Task、Proposal、Confirmation 或 Reminder 的事实源。
- Knowledge 不得直接调用 DeepSeek；Embeddings 不得把 Ollama DTO 传给 Knowledge。
- 检索结果只能作为带来源的 T2 上下文，不能提升为命令或绕过确认。
- Data Lifecycle 不得直接执行跨模块 SQL 删除；任何备份恢复都必须在 Retrieval 启用前重放 Tombstone。
- Notifications 不得根据用户文本自行改变业务状态。
- Actions 和 Calendar System 不得在没有有效所有者授权、当前版本和明确自动化规则时执行。
- AI Adapter 不得接收客户端密码、refresh token、完整审计日志或不必要的个人数据。
- 任何模块不得通过共享 ORM Entity 形成隐式耦合。
- 不得用跨模块数据库事务或 JOIN 代替公开契约。
- 任何 Provider 的 DTO 不得越过适配器进入领域层。
- 任何异常日志不得输出请求头、授权码、token、邮件全文或附件内容。

## 7. 建议代码目录

```text
src/
  bootstrap/                 # 进程启动、依赖装配
  modules/
    identity/
    connections/
    credentials/
    inbox/
    normalization/
    understanding/
    workflow/
    ai_gateway/
    knowledge/
    retrieval/
    embeddings/
    scheduling/
    agenda/
    reminders/
    actions/
    notifications/
    data_lifecycle/
    audit/
  adapters/
    inbound/
      http/
      qq/
      workers/
    outbound/
      microsoft_graph/
      qq_mail_imap/
      gmail/
      ai/
      ollama/
      persistence/
  contracts/                 # 仅放跨模块稳定 DTO 和事件定义
tests/
  unit/
  contract/
  integration/
  end_to_end/
```

`contracts/` 不是公共杂物目录。只允许放已经明确版本化、确实跨模块使用的契约。

## 8. 边界测试

CI 必须包含架构测试，验证：

- domain 不依赖 Web、ORM、Provider SDK。
- 模块不能导入其他模块的 internal/domain/infrastructure。
- Provider DTO 不出现在 application contract 中。
- 凭据类型不能被序列化到日志或领域事件。
- 所有 Action handler 都声明确认策略和幂等策略。

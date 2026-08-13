# 技术栈与工程约束

## 1. 已接受技术选型

| 类别 | 选择 | 边界 |
|---|---|---|
| 语言 | Python 3.12 | 因 QQ 官方 SDK 的可复现 3.14 兼容问题降级 |
| 项目管理 | uv | 管理 Python、`.venv`、依赖和锁文件 |
| Agent 编排 | LangGraph | 只属于 Workflow/Application 层 |
| QQ | 官方 `qq-botpy` | 只存在于 QQ Adapter |
| AI | DeepSeek API | 只通过 AI Gateway/DeepSeek Adapter 调用 |
| Embedding | Windows 本机 Ollama + `qwen3-embedding:4b` | 只通过 Embedding Port 调用 |
| 数据库 | PostgreSQL + pgvector | 关系型事实与 RAG 索引共库、分模块所有权 |
| 本地基础设施 | Docker Compose | 只管理 PostgreSQL 等基础设施，不容器化开发 `.venv` |
| 配置 | `.env` + `pydantic-settings` | 强类型 Settings 注入 |
| 数据校验 | Pydantic 2 | API DTO、配置和 LLM 结构化输出 |

Web 使用 FastAPI + Uvicorn，持久化使用 PostgreSQL + SQLAlchemy 2 + Alembic，异步任务使用数据库 Outbox/Job Worker；第一版不引入 Redis/Celery。

## 2. Python 版本策略

- 开发基线为 CPython 3.12，`.python-version` 固定 `3.12`，uv 使用当前最新 3.12.x 补丁版本创建项目 `.venv`。
- 2026-08-13 的 Python 3.14.6 测试表明依赖可解析和导入，但 `qq-botpy 1.2.1` 在 `botpy.Client` 初始化时调用 `asyncio.get_event_loop()`，因 3.14 主线程没有当前事件循环而抛出 `RuntimeError`。
- 同一凭据在 Python 3.12 下已完成官方 token、机器人登录、gateway 元数据和沙箱 C2C 主动消息验证。
- 不使用设置全局事件循环等猴子补丁掩盖 SDK 兼容问题；恢复升级需等待上游修复，并通过完整 QQ 沙箱长连接、收发和重连测试。
- 其他依赖仍选择最新稳定且兼容 Python 3.12 的版本，具体完整版本由 `uv.lock` 固定。

## 3. uv 规范

项目使用标准 uv project 工作流：

```text
pyproject.toml      直接依赖和工具配置
.python-version     Python 主次版本
uv.lock             完整、可复现的依赖锁
.venv/              当前项目专用虚拟环境，不提交 Git
```

规则：

- 使用 `uv add`/`uv remove` 管理项目依赖，不直接运行 `pip install` 修改环境。
- 使用 `uv sync` 创建或同步 `.venv`。
- 使用 `uv run` 执行应用、测试、Lint 和迁移。
- `uv.lock` 必须提交版本控制。
- CI 使用 `uv sync --locked`，禁止静默改变锁文件。
- 一次性工具优先使用 `uvx`，避免污染项目依赖。

## 4. 依赖版本策略

- 新增依赖时选择当日最新稳定兼容版本，不主动选择旧版本。
- `pyproject.toml` 只添加必要的兼容范围；`uv.lock` 固定实际完整版本。
- 不使用无理由的 `==` 锁死直接依赖，也不使用完全无约束的生产部署。
- 更新通过显式的 uv upgrade/lock 操作，并运行单元、契约、集成和架构测试。
- 发生降级或排除版本时，在 `pyproject.toml` 注释不可用的情况下，必须在 ADR/兼容清单中记录原因。
- 定期检查过期依赖和安全公告；QQ SDK 因更新较慢需要单独关注上游仓库。

截至 2026-08-13 的核对快照：

| 包 | 当时最新版本 | 说明 |
|---|---:|---|
| `qq-botpy` | 1.2.1 | 官方 QQ Python SDK，声明 Python 3.8+ |
| `langgraph` | 1.2.11 | 要求 Python 3.10+ |
| `langchain-openai` | 1.4.3 | 用 OpenAI 兼容接口连接 DeepSeek |
| `pydantic` | 2.13.4 | 结构化校验 |
| `pydantic-settings` | 2.15.0 | `.env` 和 Settings |
| `pgvector` | 0.5.0 | pgvector 的 Python/SQLAlchemy 类型支持 |
| `psycopg` | 3.3.4 | PostgreSQL 驱动 |

该表只用于审计选型，不替代 `uv.lock`，实现时必须重新解析最新版本。

## 5. LangGraph 使用范式

本项目不采用“让一个 ReAct Agent 自由调用所有工具”的开放式架构。采用可审计的受限状态图：

```text
Ingest Reference
→ Deterministic Trust Gate
→ Router（结构化分类）
→ Event Extractor / Task Extractor
→ Deterministic Schema & Policy Validator
→ 必要时 Evaluator/Retry（有次数上限）
→ Scheduling Use Case
→ 可选 Retrieval（只读、带来源）
→ Human-in-the-loop Interrupt
→ Confirmation Gate
→ Actions（图外受控副作用）
```

使用的成熟范式：

- Routing：按 Event、Task、无关信息和需人工复核分流。
- Prompt Chaining：提取后进行独立验证，不让单次模型输出直接生效。
- Evaluator-Optimizer：仅在低置信度时进行有限次数复核。
- Human-in-the-loop：在内部日程写入前持久化并中断，等待用户确认。
- Durable Execution：使用 checkpointer 恢复等待或失败的工作流。
- Read-only Tools：模型最多访问经过裁剪的只读上下文，不获得写权限。

约束：

- Graph State 只保存领域对象 ID、短期结构化中间结果和控制状态。
- 业务事实仍由各领域模块数据库拥有，LangGraph checkpoint 不是事实源。
- 每个图配置最大步数、模型调用次数、超时和重试上限。
- 副作用工具不暴露给模型；写内部日程只能经过 Actions 模块。
- Graph 节点不得直接读取 `.env`、数据库其他模块表或 Provider token。

## 6. DeepSeek Adapter

DeepSeek 当前提供 OpenAI 兼容 API。实现通过 `langchain-openai` 或官方 OpenAI SDK 的兼容客户端接入，但只在 DeepSeek Adapter 中出现。

配置契约：

```text
DEEPSEEK_API_KEY=            # 必填、秘密
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_FAST_MODEL=deepseek-v4-flash
DEEPSEEK_REASONING_MODEL=deepseek-v4-pro
DEEPSEEK_FAST_TIMEOUT_SECONDS=30
DEEPSEEK_REASONING_TIMEOUT_SECONDS=60
DEEPSEEK_MAX_RETRIES=2
DEEPSEEK_MAX_CONCURRENCY=2
```

模型策略：

- Flash：路由、分类、常规 Event/Task 提取。
- Pro：复杂时间歧义、低置信度复核；不默认用于每条消息。
- 使用 JSON/structured output，并继续用 Pydantic 做本地验证。
- JSON Output 请求显式包含 `response_format={"type":"json_object"}` 和 JSON schema 示例；
  非正常 finish、空内容、未知/额外字段与非法时间都按不可信输出处理。
- Tool Call 参数不可信，必须校验名称、schema、权限和业务范围。
- 用户标识发送给 Provider 时使用不可逆的内部别名，不发送 QQ 号、邮箱或其他直接标识。
- 不设置 DeepSeek 月度预算硬上限；仍采集 token 用量、模型、延迟和错误分类，并对异常突增告警。

AI Gateway 只持久化 use case、Prompt 版本、路由、模型、token 数、延迟、状态与错误分类；完整
请求、响应、reasoning content 和外部正文不写数据库或日志。DeepSeek Adapter 使用有界超时、
有限重试和账号级并发限制，429/网络/5xx 与永久错误分类处理。

Understanding 工作流使用 LangGraph `StateGraph`，最大递归步数为 8、每条内容最多两次模型
调用。Workflow 自有持久化检查点只保存 Inbox ID、阶段、分类、Candidate ID、置信度、复核原因
和调用次数；不保存正文，也不替代 Understanding 候选事实。进程在候选落库后中断时，恢复只
补 Inbox 状态，不再次调用模型。

## 7. QQ 官方 SDK Adapter

- 依赖包为 `qq-botpy`，导入名为 `botpy`。
- AppID 和 AppSecret 通过 `.env` 注入。
- `botpy.Client`、Intents、Message 和 API DTO 只存在于 `adapters/inbound/qq` 与 `adapters/outbound/qq`。
- 收到事件后立即转换为 `SourceEnvelope`，不得把 SDK Message 对象传入 Inbox 或 Workflow。
- SDK 回调内只做校验、去重入队和快速响应，不执行 LLM、邮箱同步或排程。
- 主动消息必须通过 Notifications Port，并遵守 QQ 平台频率、消息场景和审核限制。

## 8. `.env` 配置规范

- 根目录提供 `.env.example`，只含变量名、安全默认值和注释。
- `.env`、`.env.*.local` 和任何真实秘密文件加入 `.gitignore`。
- Settings 按模块拆成嵌套配置，但只在 Bootstrap 统一实例化。
- 测试显式构造 Settings 或使用测试专用环境，不依赖开发者个人 `.env`。
- 配置日志只打印字段是否存在和非敏感枚举，不打印秘密值。
- `.env` 是注入媒介，不是领域层 API；模块通过构造参数接收所需配置。

## 9. RAG 技术约束

- 默认嵌入模型为 Windows 本机 Ollama `qwen3-embedding:4b`，调用 `/api/embed`，固定输出 1024 维。
- Ollama 只监听 `127.0.0.1:11434`；DeepSeek 与 Ollama 分属生成模型和嵌入模型两个适配器。
- PostgreSQL 启用 `vector` 扩展，使用 pgvector cosine 距离；数据量增长后使用 HNSW `vector_cosine_ops`。
- 第一版采用混合检索：向量召回、关键词/短语召回、来源和时间元数据过滤，再通过 RRF 或等价确定性算法融合。
- 每个向量记录 `model_id`、模型摘要、dimensions、chunker_version 和 index_version。
- 修改模型或维度时创建新索引版本并后台重建；新旧向量不得在同一相似度查询中混用。
- RAG 的检索结果是 T2 数据，不是命令；回答和建议必须保留 `source_ref`。
- LangGraph 只能通过 Retrieval Port 取得限定数量的片段，不直接访问向量表或 Ollama。

## 10. 2026-08-13 配置验证基线

在不记录或回显任何秘密值的前提下已完成：

- 所有必需敏感字段存在，Microsoft Client ID、32 字节凭据加密密钥、应用签名密钥和数据库密码格式检查通过。
- DeepSeek 最小 Chat Completions 请求返回成功，并包含模型和 usage 元数据。
- QQ 官方凭据换取 token、机器人登录、gateway 元数据和沙箱 C2C 主动消息成功。
- Microsoft confidential client 凭据验证成功；未读取邮箱数据。
- Ollama `qwen3-embedding:4b` 实际生成 1024 维有限值向量成功。
- Docker Engine 29.7.2 与 Docker Compose 5.3.1 可用。

该验证不替代实现后的集成测试；尤其 QQ 长连接事件接收和自动重连仍必须在正式 Adapter 中验证。

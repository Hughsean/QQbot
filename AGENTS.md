# QQ Time Agent 开发规则

本文件适用于整个仓库。任何实现、重构、测试和部署变更都必须遵守。

## 1. 事实来源与工作顺序

1. 开始工作前完整阅读 `docs/README.md`，再读取与当前阶段直接相关的需求、边界、契约和 ADR。
2. `docs/` 是产品和架构事实来源；代码与文档冲突时先停止并修正文档或请求用户决定，不能让实现暗自改写需求。
3. 按 `docs/09-delivery-plan.md` 的阶段顺序推进。每阶段必须满足完成标准和自动化验证后才能进入下一阶段。
4. 不读取、输出、提交或记录 `.env` 的真实值。测试只报告字段是否存在和脱敏结果。

## 2. 技术基线

- CPython 3.12，使用 uv 管理 Python、项目内 `.venv`、依赖和 `uv.lock`。
- 新依赖使用最新稳定且兼容 Python 3.12 的版本；降级必须记录可复现原因。
- Python 应用开发在项目 `.venv` 中运行；部署采用容器模式（ADR-0012），Docker Compose 承载 PostgreSQL + pgvector 与 Web/Worker/QQ 应用容器。
- FastAPI + Uvicorn、SQLAlchemy 2、Alembic、LangGraph、官方 `qq-botpy`、DeepSeek Adapter、本机 Ollama。
- 配置只由 Bootstrap 使用 `pydantic-settings` 从 `.env` 构造；业务模块禁止散落 `os.getenv()`。

## 3. 模块与依赖边界

- 采用模块化单体和 Ports/Adapters。模块清单、数据所有权和依赖规则以 `docs/04-module-boundaries.md` 为准。
- 每个业务模块内部按需使用 `domain/`、`application/`、`contracts/`、`infrastructure/`、`api/`；不得为了形式创建空层。
- 其他模块只能导入目标模块的 `contracts` 或明确公开的 application port。禁止导入其他模块的 `domain`、`infrastructure`、内部 application 实现或 ORM Entity。
- Domain 不得依赖 FastAPI、SQLAlchemy、LangGraph/LangChain、botpy、HTTP 客户端、Provider SDK 或 Settings。
- Provider DTO 必须在 Adapter 边界转换，不能进入领域层或跨模块契约。
- 每个模块只访问自己拥有的数据表；禁止跨模块 ORM Relationship、JOIN、Repository 和共享事务。
- 跨模块写入使用公开命令端口或领域事件 + Transactional Outbox；组合查询使用专用 Read Model。
- LangGraph 只属于 Workflow/Application 层，Graph State 只保存控制状态、领域 ID 和有界中间结果，不能成为业务事实源。
- Agenda 是日程事实源；RAG、LLM 输出和 LangGraph checkpoint 不能覆盖 Agenda、Task、Confirmation 或 Reminder 状态。
- 副作用只经 Actions/Reminders 门禁执行；模型无权直接写日程、发送 QQ、访问数据库或读取凭据。
- 依赖装配只在 `bootstrap/`；禁止 Service Locator 和全局可变容器。

## 4. 文件与代码规模

- 手写生产 Python 文件目标不超过 300 个逻辑代码行，硬上限 500 行。
- 文件接近 300 行时先按职责拆分；超过 500 行视为架构测试失败，不得以区域注释或长类继续堆叠。
- 例外仅限自动生成文件、Alembic 迁移和不可拆分的声明式数据；例外必须在架构测试白名单中逐文件写明理由。
- 单个函数目标不超过 40 行，复杂分支应拆成有名称的用例、策略或纯函数。
- 单个类只承担一个明确职责；Controller、Worker handler、LangGraph node 和 Adapter 方法保持薄层，不承载跨模块业务编排。
- 禁止 `utils.py`、`helpers.py`、`common.py` 演变成公共杂物箱。共享代码必须无业务语义且有明确主题名称。
- `__init__.py` 只定义稳定公开面，不放业务实现。

## 5. 自动化质量门禁

在项目骨架阶段建立并持续运行：

- Ruff 格式、Lint 和 McCabe 复杂度检查，复杂度上限 10。
- mypy 严格模式；边界处不得使用未说明的 `Any` 绕过类型系统。
- 架构测试：模块导入方向、Domain 依赖、Provider DTO 泄漏、跨模块 ORM 和文件 500 行硬上限。
- 单元测试、契约测试、Docker 集成测试和必要的 QQ/DeepSeek/Ollama 沙箱测试。
- Domain/Application 核心逻辑覆盖率目标不低于 90%，项目总体不低于 80%；安全门禁、幂等、时间和删除传播必须有分支测试。
- 所有时间使用带时区值；涉及当前时间的代码通过 Clock Port 注入，测试禁止依赖真实墙上时间。
- 外部调用必须有超时、有限重试、错误分类和可观测性；测试不得调用生产账号，明确授权的沙箱冒烟测试除外。

## 6. 变更完成条件

每次阶段性交付至少满足：

1. 代码属于唯一明确模块，依赖方向合法。
2. 数据库迁移、契约和文档同步更新。
3. 相关单元、架构、契约与集成测试通过。
4. Ruff、mypy、文件规模和秘密扫描通过。
5. 没有把 TODO、假实现或静默降级当成完成。
6. 向用户报告已完成内容、验证证据、剩余风险和下一阶段；未经请求不推送、不部署生产。

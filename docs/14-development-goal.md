# QQ Time Agent MVP 开发 Goal

## 1. Outcome

按照本仓库 `AGENTS.md`、`docs/README.md`、`docs/09-delivery-plan.md` 和全部已接受 ADR，完成 QQ Time Agent 的可运行、可测试 MVP：

- Windows 本机使用 Python 3.12、uv 和项目 `.venv` 运行 Web/Worker。
- Docker Compose 运行 PostgreSQL + pgvector，仅绑定回环地址。
- QQ 官方 `qq-botpy` 支持唯一所有者的沙箱 C2C 输入、确认、结果和主动提醒。
- Microsoft delegated OAuth 只读同步 Outlook 邮件。
- LangGraph 采用受限、可恢复、有界工作流。
- 项目内部 Agenda 完成日程编排，Reminder 持久化并幂等发送。
- DeepSeek 完成结构化理解；Ollama `qwen3-embedding:4b` + pgvector 完成带来源混合 RAG。
- 分层保留、删除传播、审计、日志脱敏和备份部署资料完整。

完成指“本地 MVP 全流程和沙箱集成有验证证据、部署制品准备完成”，不包含未经用户明确批准的生产部署或对真实邮箱执行破坏性操作。

## 2. Constraints

1. 严格遵守根目录 `AGENTS.md`；`docs/` 是需求和架构事实来源。
2. 按 `docs/09-delivery-plan.md` 阶段顺序推进，不跳过前置安全与幂等门禁。
3. 模块化单体、Ports/Adapters、模块数据所有权、公开契约和 Transactional Outbox 不得弱化。
4. 手写生产 Python 文件目标不超过 300 逻辑代码行、硬上限 500；函数复杂度不超过 10。
5. 不创建超级 Service、超级 Repository、超级 LangGraph、公共 ORM Entity 或杂物 `utils.py`。
6. Python 固定 3.12；依赖用 uv 添加最新稳定兼容版本，提交 `uv.lock`；开发测试只使用项目 `.venv`。
7. Docker 只用于 PostgreSQL + pgvector 等基础设施，不用容器替代开发 `.venv`。
8. 所有配置经强类型 Settings 注入；不输出、提交或记录 `.env` 值。
9. AI、RAG 和外部内容都没有副作用权限；日程变更经确认，已确认日程的提醒经有限授权自动发送。
10. 外部调用必须有超时、有限重试、错误分类、幂等和可观测性。
11. 遇到需要浏览器登录、用户同意、生产部署批准或不可逆外部操作时暂停并请求用户；其他常规实现决定按文档和成熟默认值继续。
12. 不为通过测试而删除范围、放宽架构规则、使用假实现或静默跳过失败集成。

## 3. Verification / Definition of Done

只有全部满足才可宣布 Goal 完成：

- Git 仓库和 `codex/` 开发分支建立，工作区没有意外敏感文件被跟踪。
- `pyproject.toml`、`.python-version`、`uv.lock`、项目 `.venv`、配置与 Bootstrap 完成。
- Docker PostgreSQL + pgvector 健康，Alembic 从空库升级和回滚/重建路径验证。
- 所有阶段的单元、架构、契约、集成和显式沙箱 E2E 测试通过。
- Ruff、格式化、mypy strict、秘密扫描、文件 500 行硬门禁和复杂度门禁通过。
- Domain/Application 核心覆盖率不低于 90%，总体覆盖率不低于 80%。
- QQ 长连接接收、沙箱 C2C 回复/主动消息和重连验证；Python 3.14 不兼容回归被测试或约束阻止。
- Microsoft OAuth、Mail.Read 同步、token 加密/刷新/断开和去重验证。
- Agenda 冲突检查、Proposal 版本确认、Reminder 重启恢复/租约/幂等/推迟/取消验证。
- DeepSeek schema 校验、超时降级和调用边界验证；模型不可用不影响已有提醒。
- RAG 来源版本、删除传播、1024 维约束、混合检索引用和 Recall@10 ≥ 0.85 的去敏评估通过。
- 分层保留和 Tombstone 重放测试通过，删除内容不会因备份恢复重新可检索。
- Web/Worker/QQ 本机启动、健康检查、Docker 启动和 Windows 三进程守护脚本/说明完成。
- `docs/`、`.env.example` 和运行手册与最终实现一致；最终报告列出验证证据、已知限制和生产部署步骤。

## 4. Execution cadence

- 开始时先检查仓库状态和全部约束，建立阶段计划。
- 每完成一个交付阶段，运行该阶段完整门禁并记录简短检查点，然后自动继续下一阶段。
- 发现架构违规或文件逼近软上限时立即重构，不把债务拖到最后。
- 仅当确实需要用户授权/输入、生产外部状态变化或文档没有安全默认值时暂停。

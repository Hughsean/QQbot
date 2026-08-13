# 开发分层与质量门禁

## 1. 目的

本文件把“模块清晰、分层明确、没有巨型单体文件”转换成可以由 CI 验证的完成条件。根目录 `AGENTS.md` 是执行规则，本文件记录设计依据和验收方式。

## 2. 代码结构门禁

建议初始结构：

```text
src/qq_time_agent/
  bootstrap/                 进程入口和依赖装配
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
    outbound/
  contracts/                 仅版本化跨模块 DTO/事件
tests/
  unit/
  architecture/
  contract/
  integration/
  end_to_end/
```

模块内部只创建实际需要的层。简单模块可以没有 HTTP API，但领域规则不能被塞进入口 Controller 或 ORM 模型。

## 3. 自动架构测试

阶段 1 必须建立以下测试，之后每次测试套件运行：

| 门禁 | 失败条件 |
|---|---|
| Import Boundary | 模块导入另一模块的 domain/infrastructure/internal application |
| Domain Purity | Domain 导入 Web、ORM、LangGraph、botpy、HTTP、Settings 或 Provider SDK |
| Data Ownership | 跨模块 ORM Relationship、Repository、直接表访问或写 JOIN |
| Adapter Containment | Provider DTO/SDK 类型出现在领域或公开契约 |
| Side-effect Gate | AI/Understanding/Scheduling 直接获得写日程、发送消息或凭据工具 |
| File Size | 普通手写生产 Python 文件超过 500 逻辑代码行 |
| Complexity | 函数 McCabe 复杂度超过 10 |
| Secret Safety | `.env`、token、密钥或凭据进入版本控制、日志夹具或快照 |

优先使用简单、透明的 pytest/import 检查；只有确有收益时才增加架构工具。不能只依赖代码评审肉眼发现违规。

## 4. 文件拆分准则

300 行是触发重构评估的软阈值，500 行是硬阈值。拆分按业务职责，不按机械行数：

- Controller：鉴权、DTO 转换、调用一个用例、映射结果。
- Application handler：一个用例的事务和端口编排。
- Domain service/policy：纯业务规则，可无基础设施运行。
- Repository：一个模块聚合的持久化。
- Adapter：一个 Provider 能力或协议边界。
- LangGraph：图定义、状态 schema、节点实现、路由策略分别放置；节点调用用例，不承载所有业务。
- Settings：按模块分组，Bootstrap 统一构造；不建立包含任意字典的超级配置对象。

以下拆分属于无效拆分：循环导入、只有转发的多层包装、公共 `utils.py`、跨模块共享 ORM、把一个巨型类拆成多个 partial/mixin 但仍共享可变状态。

## 5. 测试分层

- Unit：Domain 和 Application 纯逻辑，不连接网络或真实数据库。
- Architecture：静态导入、文件规模、类型泄漏和数据所有权。
- Contract：模块端口、领域事件、Provider Adapter 的请求/响应映射。
- Integration：Docker PostgreSQL + pgvector、Alembic、Outbox、租约和并发幂等。
- End-to-end：QQ 沙箱、Microsoft OAuth 测试路径、DeepSeek 最小调用、Ollama embedding；必须显式启用，默认测试不消费真实外部服务。

## 6. 进入下一阶段的规则

开发从 `docs/09-delivery-plan.md` 阶段 1 开始。每个阶段需要：

1. 对应实现和迁移完成。
2. 阶段完成标准有自动化证据。
3. 架构门禁、Ruff、mypy、单元和适用的集成测试通过。
4. 文档和 ADR 与实现一致。
5. 用户收到阶段报告；没有未说明的阻塞或高风险 TODO。

阶段 1 可以立即开始。PostgreSQL Compose、项目 `.venv`、Git 初始化、骨架、配置、架构测试和健康检查都属于阶段 1，不是开始前阻塞项。

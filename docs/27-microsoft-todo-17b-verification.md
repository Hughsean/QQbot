# Microsoft To Do 17B 本地验证报告

## 1. 范围与结论

本报告记录阶段 17B“授权接入、模块骨架与列表解析”的本地完成证据。内部 Agenda 仍是唯一
日程事实源；本阶段不创建、更新或读取 To Do task，也不改变 QQ 提醒决策。

结论：17B 本地开发门禁通过，可以进入 17C“Agenda 单向投影”。真实 Microsoft 账号的列表解析、
任务投影和 QQ 沙箱联动必须在 17E 单独验证，不能由本报告替代。

## 2. 已交付能力

- 新增独立 `task_projection` 模块，拥有 target、mapping 和 cursor 三类数据。
- 新增 `0029_task_projection` 迁移；Task Projection 表不跨模块建立外键或 ORM Relationship。
- Connections 通过公开端口签发所有者绑定的短期 task access grant；业务模块不读取 refresh token。
- Microsoft Graph adapter 只在边界内解析 Provider DTO，并对网络、超时、认证、授权、限流、
  永久错误和不安全分页链接进行分类。
- 固定解析名称为“小智建议”，仅接受规范化后唯一、私有且由当前账号所有的列表；零个、多个、
  共享或非所有者列表均明确失败，不猜测列表。
- OAuth 成功后尝试解析受管列表；解析失败不回滚已成功的 Microsoft Connection。所有者可通过
  受回环地址、会话鉴权和 CSRF 保护的显式接口重试。
- 公开返回只包含内部 target、connection、显示名、状态和版本，不暴露 Provider list ID。

## 3. 自动化证据

在 Python 3.12 项目环境和本地 Docker PostgreSQL 上完成：

| 门禁 | 结果 |
|---|---|
| Ruff lint（`src`、`tests`、`alembic`） | 通过 |
| Ruff format（本次变更文件） | 通过 |
| strict mypy（`src`） | 通过，383 个源码文件 |
| 全量非集成、非沙箱测试 | 通过，595 passed、48 deselected |
| 17B PostgreSQL 持久化与迁移 head | 通过，2 passed |
| Alembic 本地升级 | 从 `0023` 成功升级到 `0029_task_projection` |
| `git diff --check` | 通过 |

仓库中有 25 个与本阶段无关的历史文件不符合当前 Ruff format 输出；本阶段未机械改写这些既有文件，
本次新增和修改的 Python 文件均通过定向格式检查。

## 4. 失败安全性

- 授权或列表解析失败只返回安全提示和失败分类，不记录 token、Provider list ID 或 Graph 响应正文。
- 分页仅允许 `https://graph.microsoft.com/v1.0/me/todo/lists`，外部 origin 或其他路径被拒绝。
- 受管列表未验证时没有 target 可供后续投影使用；后续提醒逻辑仍按“无法核验则发送 QQ”执行。
- 本阶段没有启用任务投影 Worker、delta 同步或提醒抑制，因此不会提前改变生产提醒行为。

## 5. 后续门禁

17C 必须实现 Agenda 事件经 Transactional Outbox 驱动的幂等单向投影、重试、死信、历史补投影和
对账；外部写失败不得回滚 Agenda。完成 17C 本地与 PostgreSQL 门禁后，才能进入 17D 的完成回写
与发送前强核验。生产部署、真实账号和真实 QQ 验证统一留在 17E。

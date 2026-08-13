# ADR-0006：LangGraph 采用受限工作流而非开放式 Agent

- 状态：Accepted
- 日期：2026-08-13

## 背景

项目需要 AI 理解和长流程恢复，但邮件、转发内容和 RAG 片段不可信，日程写入和 QQ 主动消息又属于副作用。开放式 ReAct Agent 获得全部工具会破坏既定模块和安全边界。

## 决策

使用 LangGraph StateGraph 编排确定性节点、受限 LLM 节点和持久化 checkpoint。当前
Understanding 图显式拆分为 `classify`、`extract_candidate`、`validate_candidate`、
`persist_decision` 和 `apply_disposition`；模型只参与前两个节点，副作用始终由确认后的 Actions
模块在图外执行。当前 human-in-the-loop 由版本化 Proposal 与 QQ 确认用例实现，不声明尚未使用的
LangGraph interrupt。

## 结果

- LangGraph 位于 Workflow/Application 层，不进入领域层。
- Graph State 不是业务事实源。
- 不向模型暴露写日程、发送 QQ、凭据或数据库工具。
- 每个图有步数、调用、超时和重试上限。
- checkpoint 只保存 `CLASSIFIED`、`DECIDED`、`COMPLETE` 控制状态和领域引用；正文、Provider
  DTO 与未验证模型 JSON 不进入 checkpoint。
- Scheduling 和 Actions 分别承担确定性规划与受控执行职责，但不作为可由模型自由调用的
  Planner/Executor 节点。

# ADR-0008：单用户内部日程与本地嵌入 RAG

- 状态：Accepted
- 日期：2026-08-13

## 背景

项目明确只供所有者本人使用，不需要外部日历 Provider 或多租户能力；同时需要项目内部编排、QQ 主动提醒，以及从历史内容找回背景的 RAG。

## 决策

- Agenda 模块以 PostgreSQL 作为权威日程事实源，不接入 Microsoft、Google 或 CalDAV 日历。
- Identity 只允许 `.env` 配置的所有者 QQ 身份，不设计租户、注册和公开发布。
- Reminder 使用持久化数据库任务和幂等 QQ 主动消息。
- RAG 使用 Docker Ollama `qwen3-embedding:4b` 生成 1024 维向量，Docker PostgreSQL `pgvector` 保存并进行 cosine/混合检索。
- DeepSeek 只负责生成式理解与回答，不负责 embedding；RAG 只提供带来源的只读背景。

## 结果

- 省去外部日历同步、冲突合并和多租户隔离成本。
- 服务器必须运行 PostgreSQL pgvector 和仅回环监听的 Ollama。
- 更换嵌入模型或维度必须重建独立索引版本。
- RAG、LangGraph checkpoint 和 LLM 输出均不能替代 Agenda、Task、Confirmation 或 Reminder 的领域状态。

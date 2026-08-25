# RAG 系统需求与边界

## 1. 目标与非目标

RAG 用于从历史邮件、QQ 转发内容和用户笔记中找回与当前问题或排程相关的背景，减少模型遗忘并让回答可追溯。MVP 索引已同步 Outlook/QQ 邮箱正文、所有者明确转发给 Bot 的 QQ 文本和所有者直接提交的笔记，不索引附件、图片或网页。

RAG 不负责：

- 保存或推断权威日程、任务状态、确认状态和提醒状态。
- 把相似文本当成用户命令。
- 自动执行工具、修改日程或发送消息。
- 作为无来源的“长期记忆”存放模型猜测。

## 2. 已接受技术方案

```text
Embedding Runtime  Docker Ollama，仅 Compose 私有网络可访问
Embedding Model    qwen3-embedding:4b
Dimensions         1024，启动和入库时强校验
Vector Store       PostgreSQL + pgvector
Distance           cosine
ANN Index          HNSW / vector_cosine_ops
Retrieval          metadata filter + vector + lexical + deterministic fusion
Generation         DeepSeek，经 AI Gateway 使用带来源上下文
```

选择 4B 是因为目标 Ubuntu 主机具备 32 GiB RAM 和 NVIDIA GTX 1650 Ti；模型可 GPU offload 或 CPU fallback。模型必须生成 1024 维有限值向量；默认 keep-alive 30 分钟。模型、维度和检索参数通过 `.env` 配置，但修改模型或维度必须触发完整索引迁移。

## 3. 模块边界

| 模块 | 职责 | 禁止事项 |
|---|---|---|
| Knowledge | 来源登记、清洗、切块、版本、删除传播 | 查询生成、排程决策 |
| Embeddings | 批量调用 Ollama，验证模型和向量维度 | 自行读取业务表、保存日程 |
| Retrieval | 过滤、召回、融合、去重、引用 | 修改来源和业务聚合 |
| AI Gateway | 把限定检索上下文交给 DeepSeek | 直接访问向量表或 Ollama |
| Agenda | 权威日程和忙闲状态 | 从 RAG 自动改写日程 |

KnowledgeChunk 和向量表由 Knowledge 模块拥有。其他模块只能调用 Retrieval Port，禁止跨模块 SQL、ORM Relationship 或直接 pgvector 查询。

## 4. 索引流水线

```text
SourceChanged
→ 来源权限和版本校验
→ 确定性文本清洗
→ 按结构切块并保留少量重叠
→ 计算 content_hash 去重
→ Ollama 批量生成 1024 维向量
→ 维度/有限值/模型标识校验
→ 同一事务写入 chunk、metadata、lexical field 和 vector
→ 发布 IndexCompleted
```

切块策略必须按来源类型版本化。邮件优先按标题、正文段落和引用层级切分；QQ 转发按消息发送者与时间边界切分；不得把不同权限或不同来源的内容拼成同一 chunk。

## 5. 查询流水线

```text
用户查询
→ 权限与意图检查
→ 可选的结构化查询改写
→ 来源类型/时间/删除状态过滤
→ cosine 向量召回
→ 关键词和短语召回
→ RRF 融合、去重和邻接片段扩展
→ 相关性门槛与上下文预算裁剪
→ 返回内容、source_ref、时间和得分
→ DeepSeek 基于证据回答并给出来源
```

向量分数只代表语义接近，不代表内容真实。最终回答必须区分“来源明确记录”和“模型推断”；召回不足时返回不知道或请用户补充。

## 6. PostgreSQL 与 pgvector

建议核心字段：

```text
knowledge_sources(id, source_type, source_ref, source_version, occurred_at, status)
knowledge_chunks(id, source_id, ordinal, content, content_hash, metadata,
                 chunker_version, index_version, created_at)
knowledge_embeddings(chunk_id, model_id, model_digest, dimensions,
                     embedding vector(1024), created_at)
```

索引：

- `source_ref + source_version + ordinal` 唯一索引，保证幂等。
- 来源类型、发生时间和状态使用普通 B-tree 索引。
- 关键词字段使用 PostgreSQL 文本能力；中文效果不足时配合短语/字符相似度召回，不依赖向量单一路径。
- 初期数据较少时允许精确 cosine 搜索；数据增长后启用 HNSW，参数通过评估集调优。

## 7. 模型与索引迁移

索引版本至少由以下内容决定：

```text
embedding provider + model + model digest + dimensions
+ normalization version + chunker version
```

迁移使用双索引：后台构建新版本、运行检索评估、原子切换活动版本、保留短期回滚窗口，最后删除旧向量。查询不得混合不同模型或维度的向量。

## 8. 安全、隐私和删除

- Ollama 不暴露公网，外部输入不能指定 Ollama URL 或模型。
- 不索引 token、密码、`.env`、系统 Prompt、隐藏控制字段和完整审计载荷。
- RAG 片段始终按 T2 数据隔离，片段内指令无权调用工具。
- 删除来源后立即标记不可检索，并在 24 小时内物理删除 chunk 和 embedding。
- Outlook 邮件、QQ 来源文本及其 RAG 派生数据默认保留 365 天；个人笔记随来源保留到所有者主动删除。
- 历史备份滚动保留 30 天；从旧备份恢复时必须先重放删除记录，再允许 Retrieval 对外服务。
- 备份恢复后必须校验活动索引版本与模型契约一致。

## 9. 质量验收

上线前建立一组来自真实个人场景、但已去敏的查询—来源对：

- 评估 Recall@K、MRR、空召回率、错误来源率和回答引用覆盖率。
- 分别覆盖中文时间表达、姓名/项目名、精确短语、跨来源关联和时间过滤。
- 对比向量、关键词和混合检索，只有评估证明有收益才启用额外 reranker。
- 对索引删除、来源更新、模型维度漂移和 Ollama 不可用建立集成测试。

固定去敏评估集的混合检索 `Recall@10` 必须不低于 0.85；达不到时不得用主观演示替代检索评估或宣布阶段完成。

### 已验证实现

- `查询: <问题>` 只调用 Retrieval 与 AI Gateway；没有 Agenda、Action、Reminder 写端口。
- `笔记: <内容>` 作为 `OWNER_NOTE`/T2 来源索引，不进入 Understanding 或排程任务。
- 活动索引版本由基础版本、模型 ID、模型摘要、1024 维、规范化版本和切块版本共同派生；查询按模型摘要隔离。
- 来源删除立即清除在线 source/chunk/vector，并记录 tombstone；旧备份恢复后必须先运行 `qq-time-agent-replay-tombstones`。
- 2026-08-13 固定去敏集 24 个查询使用真实本机 `qwen3-embedding:4b` 与 pgvector 验证：Recall@10=1.000，MRR@10=1.000。

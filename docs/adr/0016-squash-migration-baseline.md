# ADR-0016：迁移链压缩为单基线

## 状态

已接受。

## 背景

代码库在迭代中累积了 `0001_stage1` 到 `0031_agent_turn_batches` 共 31 个迁移，其中包含只为
存量部署服务的过渡逻辑（如 `0028_summary_contract` 的逐行数据回填）。这带来三个问题：

- 数据回填类迁移在运行时读取并改写存量数据，导致"从零离线导出全链 SQL"（`alembic upgrade
  head --sql`）无法执行，全链离线基线不可得。
- 新环境从零建库必须重放全部 31 个中间状态，而其中大部分中间形态没有任何部署在运行。
- ORM 模型与迁移链由不同提交演进，容易再次出现元数据漂移（已在阶段 18 修复并对齐）。

## 决策

- 迁移链压缩为单个线性基线 `0001_initial_schema`（down_revision=None），内容为压缩前
  `0031_agent_turn_batches` 的最终 schema。已通过逐项清单比对（表/列/类型/默认值/约束/索引）
  证明新旧建库产物完全一致，`alembic check`（含 server_default 比较）归零。
- 迁移链必须保持单线（无 branch labels、无分叉、单 head）；`tests/architecture/
  test_migration_chain.py` 持续校验。
- 代码库不再保留"中间生产部署"的迁移与回填逻辑。存量数据库升级由一次性运维脚本完成：
  `ops/baseline-cutover-to-initial-schema.sql` 负责把停在任何旧版本的库对齐到基线并登记
  `0001_initial_schema`。该脚本执行一次后删除，不作为常规发布产物维护。
- 禁止再向迁移链引入运行时数据回填。确需迁移数据的变更走临时运维脚本，迁移链只承载纯 DDL。
- ORM 元数据必须与迁移产物保持一致：`tests/integration/test_schema_metadata_alignment.py`
  在每个测试轮次从零建库并执行 `alembic check` 门禁（含 `compare_server_default`）。
- 回滚策略由"降级到中间版本"改为"备份恢复 + 版本登记"：出现需要回滚的发布时，用
  `ops/Backup-QQTimeAgent.ps1` 的备份恢复数据，再把 `alembic_version` 登记到与代码匹配的
  迁移。压缩前的旧迁移链保留在 git 历史中，需要时可从历史提交取回。

## 影响

- 全新环境（含生产重建）`alembic upgrade head` 一步到位；全链离线 SQL 重新可用。
- 部署携带本基线的代码前，存量数据库必须先执行一次性切换脚本，否则 `migrate` 服务的
  `alembic upgrade head` 会因旧版本号无法识别而失败。
- `downgrade` 只支持回到 base；不再提供中间版本降级点。
- 压缩前为存量回填编写的兼容测试 `test_summary_migration_compatibility.py` 随场景一并移除。

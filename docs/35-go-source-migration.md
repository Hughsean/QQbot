# Go G3 来源与规范化迁移

G2 只读账号门禁通过后启动。需求与行为依据为文档 04/05/06/07、ADR-0013、ADR-0017，
以及 `Main@c63eae1` 的 Inbox、Normalization 和既有测试。G3 仍在实施，不能宣称来源迁移完成。

## 交付顺序

1. G3a：Inbox 状态机、确定性文本规范化、独立 Normalization Repository 和历史回归映射。
2. G3b：Inbox 原始信封持久化、连接级去重/删除围栏、游标与来源查询。
3. G3c：多连接同步编排、Graph delta、QQ Mail UID/MIME、只读抓取、重试和真实两轮增量门禁。
4. G3d：SourceAsset/BlobStore、ICS、PDF、本地 OCR、官方 QQ 媒体与合并转发，资源限制和删除传播。

子交付用于逐步核验，不替代文档 32 的完整 G3 门禁；G3 全部通过后才能进入 G4。
来源与解析属于 Inbox/Normalization，模型理解和日程修改继续禁止进入这两个模块。

## G3a 契约

- 保留 Inbox 的九种状态、合法转换、版本递增、重试计数和失败分类；邮件固定 SYNC/T2，
  QQ 转发/笔记固定 T2，不能由正文提升权限。Go time.Time 总有时区，拒绝零值时间。
- 规范化保留 `mail-text-v1`：优先非空纯文本，HTML 去除 script/style/svg/template/noscript，
  解码实体、折叠横向空白并去除空行。主题最多 2,000、正文最多 200,000 个 Unicode 字符。
- HTML tokenizer 位于 Infrastructure，Domain 只负责纯字符串规则，不能导入 net/html。
  HTML Adapter 不访问网络，不加载图片/样式。输入总量限制 8 MiB，防止解析前无界分配；
  此限制只用于拒绝超大输入，不静默截断原始来源。取消时不保存不完整结果。
- Normalization 只访问 normalization_contents，按 Inbox UUID upsert，保留 source_hash、
  normalizer_version、source_ref。SQL 基线不改写，不跨模块 JOIN/事务。
- 当前 web 仍仅健康入口。尚未迁移的来源清理、邮件同步和解析器不接入运行时，不使用 no-op。

## 验证记录

G3a 已完成：

- Inbox 合法/非法状态转换矩阵、终态失败、重试计数、版本和来源信任校验通过。
- 纯文本优先、HTML 隐藏/主动标记清理、实体、Unicode 换行与字符上限通过。
- 取消/超大/无效输入不写结果；日志与结构化日志不泄漏源文本。
- Docker PostgreSQL 12 路并发 upsert 只保留一条记录，元数据/来源引用与更新读取通过。
- 全量 Go 测试与数据库集成、Linux `-race -tags=integration` 全套通过；Linux 检查仅挂载
  源码/测试/合成清单到 Go 1.27.2 verify 镜像，不挂载真实 .env。新 verify 镜像构建通过。
- gofmt、vet、staticcheck、复杂度/模块与数据所有权/文件上限、秘密扫描、模块校验通过；
  govulncheck 未发现漏洞。总体覆盖 92.2%，新增 Inbox Domain、Normalization Domain/Application 均为 100%。
- 601 条历史测试场景中 55 条已映射 Go 回归、546 条仍待迁移，架构测试验证每个引用存在。

源表与 normalization_contents 基线没有改写。G3c–G3d 仍待完成，本轮没有真实邮件读取、
没有在 HP 部署服务，也未启用任何账号业务 HTTP 路由。

## G3b 实施边界

Inbox 自有事务按 connection UUID 获取与旧实现兼容的 advisory lock，串行去重、状态更新、
游标写入、来源删除与连接围栏；不同连接独立。两个唯一键仍为 (connection_id, external_id)
和 (connection_id, dedupe_key)，重复输入不覆盖原文或来源。只在新建记录时写原始正文。
标记删除立即使正文查询不可见，保留脱敏来源视图和删除身份，后续同外部 ID 或 dedupe key
不得复活；连接重新允许不清空来源删除记录。物理删除和跨模块传播仍属于 G3d/G8。
游标只用不可日志化的 opaque secret.Value，经连接围栏检查后保存，不进入公开 HTTP。
此阶段提供真实 Inbox 数据端口，但不会用仅删除 Inbox 的局部操作假装整个连接清理成功。

G3b 已完成上述 Inbox 内核：typed mail/metadata、事务内原文新建、外部键/Message-ID 次级键
去重、乐观版本更新、secret.Value 游标、删除身份围栏和脱敏来源视图。
验证包括 16 路并发去重只产生一组 Inbox/Raw、20 轮删除/摄入竞态、UID 改变后去重、
连接隔离、重复输入原文不变、删除前/后/重新允许连接的复活拒绝、迟到状态写入拒绝、
游标非法/围栏拒绝、原文插入失败后事务回滚无孤儿，以及 nullable 元数据 JSON 的历史兼容。
两个唯一键分别匹配不同旧记录时明确报 Conflict，不任选一条。

Go 全量单元/架构/数据库集成、Linux 全量竞态、gofmt/vet/staticcheck 与秘密扫描通过。
总体覆盖 92.5%，Inbox Application/Domain 和 Normalization Application/Domain 均为 100%。
现有依赖版本不变。历史映射为 56/601，545 条待迁移；包含物理清理的原测试仍保持 pending，
不以局部围栏测试代替完整删除传播。完整 G3 尚未验收。

# QQ Time Agent MVP 最终验证报告

验证日期：2026-08-13。唯一完成标准：`docs/14-development-goal.md` Verification。

> 历史说明：本报告记录 `9a42246` 的原始 MVP 验证。其后的 ADR-0010 已把 Microsoft OAuth
> 改为本机公共客户端回环回调，并移除 Agent 公网入口与 SSH 反向隧道；以下公网/隧道条目
> 仅是历史证据，不再是当前运行要求。

## 1. 结果

阶段 0 至阶段 8 已按 `docs/09-delivery-plan.md` 顺序完成，本地 MVP、真实沙箱集成和部署制品达到 Verification。未执行生产任务注册、生产部署或真实邮箱破坏性操作。Microsoft 已按所有者确认断开，数据库状态为 `DISCONNECTED`，连接凭据引用和 Vault 记录均为 0。

## 2. 自动化与质量证据

- CPython 3.12.13、项目 `.venv`、`uv sync --locked`、`uv.lock` 和四个项目入口验证通过。
- 全量测试：227 passed、8 skipped；跳过项全部是需要显式 `--sandbox` 的外部测试。
- 总体分支覆盖率 85.50%；Domain/Application 核心分支覆盖率 94%。
- Ruff format、Ruff lint/McCabe 10、mypy strict（319 个源文件）、26 项架构/契约门禁通过。
- 秘密扫描、`.env` 忽略、私钥扫描、Python 3.12 约束和手写生产文件 500 逻辑行硬门禁通过。
- PostgreSQL + pgvector 容器 healthy，端口只绑定 `127.0.0.1:5432`；随机空库完成 base → `0010_tombstone_idempotency` → base → head 全路径演练。

## 3. 核心与沙箱证据

- QQ 官方长连接登录、主动 C2C、所有者入站回复和断线重连通过；Python 3.14 被运行时约束和回归门禁阻止。
- Microsoft OAuth PKCE、nonce、范围、token 加密/刷新/断开、Graph Mail.Read 两轮同步与去重已通过；最终保持断开。最终沙箱只复验授权 URL 元数据，没有重连或读取邮箱。
- DeepSeek 固定去敏集通过分类 ≥ 0.90、结构提取 ≥ 0.85 和提示注入门禁；schema、超时、降级、调用边界及 Reminder 独立性测试通过。
- Agenda 冲突、Proposal 版本确认、Action 幂等/撤销、Reminder 恢复/租约/重试/推迟/取消通过。
- Ollama `qwen3-embedding:4b` 输出 1024 维；24 项去敏混合检索 Recall@10=1.000、MRR@10=1.000，引用、版本和 RAG 只读门禁通过。
- 删除传播覆盖 Inbox、Normalization、Knowledge、Candidate、Proposal 和 Workflow checkpoint；tombstone 重放后不可再检索。

## 4. 运行与恢复证据

- Web 本机与公网 readiness 均为 `ready`，SSH 反向隧道运行；`/metrics` 无正文或身份标签。
- Worker 真实本机进程启动通过；超长 Provider 来源标识使用固定长度 SHA-256 幂等键，回归测试覆盖。
- Windows Web/Worker/QQ/Tunnel 四角色守护脚本与任务注册 dry-run 通过，5 个 PowerShell 制品语法通过；未运行 `-Apply`。
- 98,119 字节 custom-format 备份经正式恢复脚本恢复到隔离临时库。覆盖前合成 tombstone 经旧备份覆盖、迁移、账本合并和重放后仍存在；临时库与验证备份已清理。
- OAuth 回调查询中的 `code`、`state`、`client_info` 等日志值已增加明确脱敏回归门禁。

## 5. 已知限制

- 尚未完成连续 14 天真实个人试用观察窗；当前聚合样本包含沙箱/合成数据，不能作为长期准确率结论。Gmail、QQ 邮箱和附件扩展继续关闭。
- Microsoft 当前断开，若恢复邮件能力必须由所有者重新完成浏览器授权。
- FastAPI 测试依赖链提示 `httpx`/TestClient 弃用警告，不影响当前功能，但后续依赖升级需迁移到兼容测试客户端。
- Windows 主机离线会使 Web/Worker/QQ/Ollama 和本机 OAuth 回调整体不可用；应按手册配置任务计划、备份轮转和告警。

## 6. 生产部署步骤（需要另行批准）

1. 复核 `.env` ACL、数据库/主密钥分离备份和全部本机回环绑定。
2. `docker compose up -d`、`uv sync --locked`、`alembic upgrade head`，运行健康与沙箱冒烟。
3. 获得生产批准后运行 `ops/Register-QQTimeAgentTasks.ps1 -Apply`，注册 Web、Worker、QQ 三角色。
4. 验证本机 readiness、QQ 主动提醒和备份作业；Microsoft 保持断开，除非所有者另行授权。
5. 按 `docs/15-owner-trial-and-operations.md` 收集 14 天聚合指标，再决定是否扩展范围。

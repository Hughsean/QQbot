# 19. 容器化部署验证报告

- 日期：2026-08-13
- 决策：ADR-0012（Python 应用容器化，保留回环安全边界）

## 1. 交付物

| 制品 | 说明 |
|---|---|
| `Dockerfile` | uv 构建 + 运行时同源基镜像（digest 固定）、非 root `app` 用户、tzdata、非 editable 安装、默认命令 `qq-time-agent-web` |
| `.dockerignore` | 排除 `.env` 等秘密、`.venv`、tests/ops，仅放行构建所需的 `docs/README.md` |
| `compose.yaml` | digest 固定的 postgres + web/worker/qq（`restart: unless-stopped`）+ `ops` profile 一次性 `migrate` / `replay-tombstones` / `requeue-knowledge-jobs`；容器内外端口契约和容器模式精确覆盖值经 Compose 注入 |
| `settings.py` | `APP_CONTAINER` 开关与容器/裸机双分支安全门禁；`CONTAINER_BIND_HOST` 常量 |
| `tests/unit/test_settings.py` | 容器模式精确值接受/拒绝与裸机回环拒绝测试 |
| `.env.example` | `APP_CONTAINER=false` 与容器覆盖说明 |

## 2. 验证证据

- 质量门禁：ruff（lint+format）、mypy strict、252 个非集成/非沙箱测试、21 个 PostgreSQL
  集成测试全部通过。
- `docker compose config` 校验通过；`docker compose build` 成功生成所有角色共用的
  `qq-time-agent:local`；PostgreSQL/pgvector tag 固定到已拉取验证的 manifest digest。
- `docker compose run --rm migrate` 在 postgres healthy 后执行成功（已处于 head）。
- 全栈启动后 `/health/live` 200；Ollama 启动后 `/health/ready` 返回
  `{"database": true, "embeddings": true}`；`ops/Test-QQTimeAgentHealth.ps1` 通过。
- 端口核查：默认 web 仅发布 `127.0.0.1:8000`、postgres 仅 `127.0.0.1:5432`；
  非默认配置实测 Web `8123 -> 8123`，应用仍访问 `postgres:5432`，宿主 PostgreSQL
  `55432 -> 5432`。
- 镜像安全：运行用户 `app`(10001)、镜像内无 `.env` 文件；秘密仅经 Compose env 注入。
- 容器内连通性：`host.docker.internal:5432/11434` 均可连；worker 经
  `http://host.docker.internal:11434/api/embed` 返回 200。
- 真实作业：容器 worker 完成 understanding-run ×27、knowledge-index ×27、
  microsoft-mail-sync、scheduling-propose 与 data-lifecycle-sweep；QQ 容器保持官方长连接无断线日志。
- 关键修复：uv 默认 editable 安装导致运行时 `ModuleNotFoundError`，改用 `--no-editable`
  后镜像自包含；uv 基镜像默认 CMD 为 `uv`，已用 `CMD ["qq-time-agent-web"]` 覆盖；
  移除 `extra_hosts: host-gateway`（Docker Desktop 原生 `host.docker.internal` 解析即可）。

## 3. 事件与恢复

验证初期先启动容器、后启动 Ollama，26 个历史待处理 `knowledge-index` 作业耗尽第 3 次
重试进入 DEAD_LETTER。因 idempotency_key 冲突调度器无法重新入队，当时执行运维恢复 SQL
将 26 个作业重置为 PENDING（attempt=0），worker 重新租约后全部 COMPLETE。

审查后已消除该人工 SQL 路径：Worker 在首次租约前循环执行 Ollama 强 health，通过前不消费
Job、不增加 attempt；运行期 dead letter 仍保留有限重试语义。隔离容器验证中，Worker 在主机
Ollama 不存在时输出首轮及每 30 秒一次的脱敏等待日志；临时启动 Ollama 后第 12 次 health
通过，随后才处理首个任务。Web readiness 与 metrics 在模型冷启动后通过。

Ollama 恢复后，显式 `docker compose run --rm requeue-knowledge-jobs` 只重置
`knowledge-index + DEAD_LETTER + TransientProvider`，永久错误和其他 kind 不变；隔离数据库
实测命令正常退出并输出聚合 `count=0`。`replay-tombstones` 同样实测输出 role、开始、完成和
聚合 count，不输出 subject_ref 或业务内容。

## 4. 剩余风险

- Docker Desktop 的 `host.docker.internal` 依赖 vpnkit 网关转发；转发异常时容器无法触达
  主机 Ollama（`/health/ready` 会以 `embeddings:false` 反映，Worker 启动日志会持续报告等待），
  不得把 Ollama 绑定 0.0.0.0。
- 尚未执行生产部署；容器镜像未推送到任何仓库。

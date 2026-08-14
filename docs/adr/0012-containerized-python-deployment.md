# ADR-0012：Python 应用容器化部署，保留回环安全边界

- 状态：Accepted
- 日期：2026-08-13

## 背景

MVP 交付时 Python 应用以项目 `.venv` 直接运行在 Windows 主机，三个进程角色由 Windows
任务计划程序守护；Docker Compose 只管理 PostgreSQL + pgvector。所有者决定容器化部署：
`docker compose` 统一编排 Web、Worker、QQ 与数据库，获得可复现的不可变镜像和自恢复进程，
不再依赖任务计划程序。

现有安全门禁与容器网络存在冲突：`settings.py` 强制 `APP_LISTEN_HOST`、`DATABASE_HOST`
和 `OLLAMA_BASE_URL` 必须是回环地址；而容器内必须绑定 `0.0.0.0` 才能被端口映射访问，
数据库要经 Compose 服务名 `postgres` 访问，Ollama 只能经 Docker Desktop 的
`host.docker.internal` 网关到达仍绑定主机回环的 Ollama。任何一处直接放开都会破坏 ADR-0010
确立的"无公网入口"不变量。

## 决策

- 引入显式 `APP_CONTAINER` 开关（默认 `false`）。容器模式只接受三组精确值：
  `APP_LISTEN_HOST=0.0.0.0`、`DATABASE_HOST=postgres`、
  `OLLAMA_BASE_URL=http://host.docker.internal:11434`；任何其他值启动失败。裸机模式保持
  原有回环强门禁不变。
- 一个镜像承载三个进程角色（web/worker/qq），由 Compose `command` 区分；镜像用 uv
  `--frozen --no-dev` 构建、非 root 用户运行、不包含任何秘密或 `.env`。应用基镜像和
  PostgreSQL/pgvector 镜像均按 digest 固定，`uv.lock` 保证 Python 依赖可复现；镜像升级必须
  显式更新 digest 并重新执行迁移、恢复和向量契约验证。
- Web 在容器内外使用同一 `APP_LISTEN_PORT`，只在主机
  `127.0.0.1:{APP_LISTEN_PORT}` 发布；应用容器强制通过 `postgres:5432` 访问数据库，宿主
  PostgreSQL 发布端口仍可由 `DATABASE_PORT` 配置。所有者路由的 Host 头回环校验
  （`_require_loopback_request`）不变；非默认 Web 端口必须同步 Entra 回调 URI。
- Ollama 继续只监听 Windows 主机 `127.0.0.1:11434`，容器经 Docker Desktop 网关
  `host.docker.internal` 访问；不把 Ollama 绑定到 0.0.0.0 或移入容器。
- 数据库迁移保持显式步骤：`docker compose run --rm migrate`；备份恢复后的 tombstone
  重放同样为 `ops` profile 一次性服务，不在应用容器启动时并发执行。恢复脚本的 Python
  步骤只调用这些容器，不依赖主机 `.venv`。
- 三个应用服务使用 `restart: unless-stopped`，替代 Windows 任务计划程序的登录自启与失败
  重启。Worker 在首次租约前等待 Ollama 强 readiness，避免主机服务滞后消耗有限重试；运行期
  瞬时故障仍进入 DEAD_LETTER，只有显式 `requeue-knowledge-jobs` 一次性容器可重置
  `knowledge-index + TransientProvider`，永久错误不自动复活。
- `ops/` 备份恢复脚本通过 `docker compose exec postgres` 和应用一次性容器工作。
- 容器日志使用 json-file 轮转（10 MB × 3）；应用日志输出 allowlist 关联字段，并对秘密、正文、
  prompt、payload 与响应内容纵深脱敏。

## 结果

- 裸机（开发）与容器（部署）两种运行模式并存；默认仍是最严格的回环门禁，容器模式是
  显式选择且每项取值被精确约束，不产生可配置的公网入口。
- 容器内 `0.0.0.0` 绑定只作用于 Compose 私有网络，主机侧可达性仍由 `127.0.0.1` 发布和
  Host 头校验双重限制。
- 依赖 Docker Desktop 持续运行；若 `host.docker.internal` 网关转发不可用，需重新评估
  Ollama 宿主方案，不得把 Ollama 暴露到局域网。
- 需要为容器模式新增 Settings 分支测试，并保持既有回环拒绝测试全部通过。

## 验收

- 裸机门禁测试与容器精确值门禁测试全部通过。
- `docker compose config` 校验通过；镜像构建成功。
- `postgres` 健康后 `migrate` 升级到 head，web 就绪探针返回 ready，worker/qq 启动无异常。
- 容器内可访问 `host.docker.internal:11434`，Ollama health 为 available。
- Ollama 晚于 Worker 启动时，Worker 在首次 Job 租约前等待且不增加 attempt；恢复命令只重置
  目标 transient knowledge dead letter。
- 正式恢复脚本在没有主机 `.venv` 时完成迁移、tombstone 合并与强制重放。

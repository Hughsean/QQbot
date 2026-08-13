# ADR-0005：使用 Python 3.12 和 uv

- 状态：Accepted
- 日期：2026-08-13

## 背景

项目确定使用 Python，并要求优先使用最新稳定包、项目内虚拟环境和可复现依赖。QQ 官方 Python SDK 发布较早，需要兼容性门禁。

## 决策

最初候选为 CPython 3.14。2026-08-13 真实测试发现 `qq-botpy 1.2.1` 在创建 Client 时调用 `asyncio.get_event_loop()`，在 Python 3.14 主线程抛出 `RuntimeError`；导入测试未能发现该问题。

因此项目使用 CPython 3.12、uv project、项目根目录 `.venv` 和提交的 `uv.lock`。新增依赖选择最新稳定且兼容 Python 3.12 的版本，不通过全局事件循环猴子补丁维持 3.14。

## 结果

- 本地、CI 和生产依赖由同一锁文件复现。
- 不使用 pip 手工维护项目环境。
- QQ SDK 必须有沙箱连接和消息收发兼容测试。
- 已验证 Python 3.12 下的 token、机器人登录、gateway 元数据和沙箱 C2C 主动消息。
- 恢复升级到 3.14+ 的条件是上游修复并通过完整长连接、收发和重连回归测试。

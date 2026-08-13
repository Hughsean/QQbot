# ADR-0007：使用 QQ 官方 SDK和 DeepSeek API 适配器

- 状态：Accepted
- 日期：2026-08-13

## 背景

QQ 接入需要避免非官方协议带来的账号和稳定性风险；AI 模型需要兼容结构化输出与工具调用，并保持供应商可替换。

## 决策

QQ 使用开放平台官方 `qq-botpy` SDK。模型首发使用 DeepSeek API，通过独立 AI Gateway/DeepSeek Adapter 接入，配置由 `.env` 注入。领域模块不依赖 SDK 类型、API Base URL 或模型名称。

## 结果

- QQ Message/Intent/API DTO 只能存在于 QQ Adapter。
- DeepSeek 默认按 fast/reasoning 两类模型路由，具体模型由环境配置。
- API key、AppID 和 AppSecret 不进入代码、日志或领域状态。
- QQ 主动消息权限与场景必须通过显式沙箱测试验证；DeepSeek 只接收清洗、最小化且不含凭据的用例数据，并由契约测试持续验证该边界。

# 系统上下文与信任边界

## 1. 参与者

| 参与者 | 角色 |
|---|---|
| 项目所有者 | 唯一用户，发出命令、授权数据源、确认建议和撤销操作 |
| QQ 平台 | 主要交互入口和通知出口 |
| 邮箱提供方 | 提供只读邮件数据，首发为 Microsoft Graph |
| AI 提供方 | 进行受限的分类和结构化提取，不拥有决策权 |
| 本机 Ollama | 为 RAG 生成嵌入向量，不承担生成式决策 |
| QQ Time Agent | 保存内部日程，编排理解、检索、排程、确认和提醒 |

## 2. 上下文关系

```text
                         ┌──────────────────┐
                         │   AI Provider    │
                         └────────▲─────────┘
                                  │ 最小化后的内容
┌────────┐  命令/确认   ┌─────────┴──────────┐  OAuth/邮件   ┌──────────────┐
│ Owner  ├─────────────►│   QQ Time Agent   ├──────────────►│ Mail Provider│
└───▲────┘◄─────────────┤                    │◄──────────────┤              │
    │   建议/主动提醒       └───────┬───────┘               └──────────────┘
    │                              │ embedding
┌───┴────┐                  ┌──────▼───────┐
│   QQ   │                  │ Local Ollama │
└────────┘                  └──────────────┘
```

## 3. 信任等级

| 等级 | 内容 | 能否形成命令 |
|---|---|---|
| T0 | 系统配置和已签名内部事件 | 可以，但仍受策略约束 |
| T1 | 已认证用户直接发给 Bot 的消息 | 可以 |
| T2 | 用户转发的聊天、邮箱和检索结果 | 不可以，只能作为事实 |
| T3 | 附件、网页、OCR、外部通知 | 不可以，且必须进行内容隔离 |

信任等级不得由 LLM 自行提升。只有入口鉴权和来源元数据可以确定消息是否为 Direct Command。

## 4. 数据流

### 4.1 输入流

```text
Connector 接收原始内容
→ 验证来源和去重键
→ Inbox 创建不可变原始记录
→ Normalization 生成统一内容
→ Understanding 生成候选 Event/Task
→ Workflow 决定追问、忽略或进入排程
```

### 4.2 排程流

```text
候选 Event/Task
→ Scheduling 请求 Agenda 的忙闲快照
→ Retrieval 按需返回带来源的背景
→ 应用用户偏好和硬约束
→ 生成带版本的 Proposal
→ Notification 发送确认卡片
```

### 4.3 执行流

```text
用户确认具体 Proposal 版本
→ Confirmation 验证身份、状态和有效期
→ Action 创建幂等执行请求
→ Agenda 写入内部日程并建立 Reminder
→ Audit 保存结果
→ Notification 返回成功或失败
```

### 4.4 提醒流

```text
Reminder Worker 租约领取到期提醒
→ 校验日程版本、取消状态和幂等键
→ QQ Notification 主动发送
→ 保存投递结果
→ 失败时有限退避重试或进入死信
```

### 4.5 RAG 索引与查询流

```text
已授权内容变更 → 清洗/切块 → Ollama 生成 embedding
→ PostgreSQL + pgvector 保存向量、关键词字段和来源元数据

用户问题 → 查询改写 → 元数据过滤 + 向量/关键词召回
→ 融合与去重 → 返回带来源上下文 → DeepSeek 生成有依据回答
```

## 5. 网络边界

```text
Internet
  → Caddy :80/:443
    → 腾讯云 127.0.0.1:8000
      → 加密 SSH 反向隧道
        → Windows App 127.0.0.1:8000
          → Docker PostgreSQL + pgvector 127.0.0.1:5432
          → Ollama 127.0.0.1:11434
          → Microsoft Graph / QQ / DeepSeek（仅出站）
```

- Caddy 负责 TLS、HTTP 到 HTTPS 跳转和反向代理。
- 腾讯云仅承担公网 HTTPS 和 SSH 中继，不运行 Agent、PostgreSQL 或 Ollama。
- Windows 应用和反向隧道目标均只监听回环地址；SSH 远端转发也只绑定腾讯云回环地址。
- PostgreSQL、队列和 Ollama 不得具有公网或局域网入口。
- OAuth 回调必须只接受预期 Provider、有效 `state` 和一次性授权码。

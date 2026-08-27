# Agent Context and RAG Upgrade

## Scope

This upgrade adds session-aware context, general QQ responses, proactive clarification,
automatic related-history retrieval for mail and user messages, a bounded RAG tool surface,
and reminder-time changes.

## Implementation Status

The initial implementation is superseded by the persistent AgentRun harness. QQ direct messages
receive a response in their own conversation. Mail results may notify the owner only when the
Agent explicitly records a material `NOTIFY` decision; uncertain or incomplete mail remains in its
EventCase as `HOLD` and never emits an unsolicited clarification. Every mail notification carries
a deterministic subject anchor. Retrieval is injected directly into the Agent runtime with
deterministic query normalization/ranking. Agenda, Reminder and Notification writes remain behind
their existing command/action ports.

## Safety boundary

- Conversation history and retrieved Knowledge chunks are untrusted T2 context.
- Retrieval may inform classification, clarification and proposals; it is never an Agenda,
  Proposal, Reminder or Confirmation fact source.
- The model may return a proposed action, but it cannot call database, QQ, mail or calendar
  providers directly.
- Agenda updates, reminder changes and non-reminder notifications require an owner command,
  a version check and an idempotency key.
- A clarification request is a notification only. It does not mutate business state.

## Context policy

Every owner message is persisted as an Inbox source. For understanding and general replies,
the application may retrieve:

1. recent owner messages in the same conversation window;
2. active pending Proposals and Agenda entries relevant to the message;
3. Knowledge chunks returned by the Retrieval port.
4. Identity-owned aliases that map an owner to a display label in a forwarded group transcript.

Context is bounded by item count and characters, excludes deleted sources, and is labelled as
evidence. The current message remains the only command authority.

Forwarded group transcripts have no reliable QQ member identifier. The owner may state a natural
language request such as “我的群聊昵称是风拾一”; the Agent registers the exact display label through
the Identity tool. Later Agent turns receive a trusted owner-identity rule for that label. It only
attributes lines in the T2 transcript and never upgrades their content to a command. If no rule
matches, the Agent must say that the speaker is unknown and request a nickname mapping rather than
guessing.

## General messages and clarification

Plain owner messages that are not explicit commands are routed through the Agent and may receive
a focused question in that same conversation. A mail event with incomplete information must not
trigger a standalone QQ question. The Agent records it as `HOLD` in the related EventCase and can
use later mail or a user-initiated conversation to resolve it. A `NOTIFY` mail result is rendered
with its source subject, so it never appears as an unreferenced message.

## RAG runtime

RAG is not exposed as an Agent tool or MCP transport. The Context Assembler invokes the
owner-scoped Retrieval port directly, bounds and labels the returned T2 evidence, then injects it
into the Agent request. Retrieval cannot write Agenda, Reminder, Proposal, Credential or
Notification state.

## Ranking and query optimization

Queries are normalized deterministically, duplicate terms are removed, and exact quoted terms
are preserved for lexical search. Vector and lexical rankings are fused with weighted RRF;
ties are resolved by source recency and stable chunk ID. Retrieval returns scores and source
metadata for audit and citation.

## Reminder updates

The owner may express a reminder change in natural language. The Agent resolves the target and
asks the Calendar System to create a version-checked reminder update action. It never edits the
Agenda entry.
Relative durations use the owner timezone and all resulting times are timezone-aware. Existing
reminder occurrences are cancelled/replaced idempotently; sent reminders are not rewritten.

The runtime clock is canonical UTC; container or host local timezone settings cannot change the
meaning of persisted instants. The owner timezone is injected into each Agent turn so “明天 9 点”
is resolved as 09:00 in `Asia/Shanghai` unless the user explicitly names another timezone.
Scoped conversation history, retrieved evidence, Agenda facts, pending proposals and prior Agent
replies are converted to the owner timezone before entering the model context. UTC database session
values must not leak into the conversational time semantics.

## QQ outbound presentation

The outgoing QQ boundary renders message origin deterministically. A direct Agent reply is
`<configured QQ display name>：<body>` (default display name: `小智`) and never has an Agent
category heading. Persistent notification intents are prefixed at delivery time with one of
`[邮件处理｜Outlook]`, `[邮件处理｜QQ邮箱]`, `[日程摘要]`, `[日程冲突]`, or `[系统通知]`.
Reminders are rendered separately as `[日程提醒]`. The Agent, email content, retrieval evidence,
and tool observations may supply only the body; square brackets in those untrusted bodies are
converted to full-width characters before delivery so they cannot impersonate a source label.

# Agent Context and RAG Upgrade

## Scope

This upgrade adds session-aware context, general QQ responses, proactive clarification,
automatic related-history retrieval for mail and user messages, a bounded RAG tool surface,
and reminder-time changes.

## Implementation Status

The first implementation slice is complete: Worker understanding receives bounded recent
conversation and automatic hybrid-RAG context; QQ supports read-only general replies and
title-based reminder commands; NEEDS_REVIEW items produce idempotent clarification messages;
retrieval exposes a local owner-scoped MCP-compatible registry and deterministic query
normalization/ranking. Agenda, Reminder and Notification writes remain behind their existing
command/action ports. Semantic event identity and automatic Agenda mutation remain a follow-up
because they require an explicit proposal and confirmation contract.

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

Context is bounded by item count and characters, excludes deleted sources, and is labelled as
evidence. The current message remains the only command authority.

## General messages and clarification

Plain owner messages that are not explicit commands are routed through a read-only response
use case. Event/Task messages continue through the asynchronous understanding workflow. If a
candidate lacks a reliable time, deadline or required constraint, the workflow creates a
clarification request and the QQ process asks a focused question. A reply is associated with
the open clarification by the conversation context window; it is not treated as a command
unless it matches an explicit command grammar.

## RAG tools

RAG tools are exposed through a local, allow-listed MCP-compatible adapter. The adapter has
read-only tools for `search_knowledge`, `get_source`, and `list_related_events`. Tool inputs
are schema validated, owner-scoped, bounded, and time-filtered. Tool output is converted to
the existing `RetrievedChunk`/source contracts before it reaches a model. No tool can write
Agenda, Reminder, Proposal, Credential or Notification state.

## Ranking and query optimization

Queries are normalized deterministically, duplicate terms are removed, and exact quoted terms
are preserved for lexical search. Vector and lexical rankings are fused with weighted RRF;
ties are resolved by source recency and stable chunk ID. Retrieval returns scores and source
metadata for audit and citation.

## Reminder updates

The owner may say `提醒 <agenda-id> 提前 <duration>` or `提醒 <agenda-id> 改为 <time>`.
The command creates a version-checked reminder update action. It never edits the Agenda entry.
Relative durations use the owner timezone and all resulting times are timezone-aware. Existing
reminder occurrences are cancelled/replaced idempotently; sent reminders are not rewritten.

# Agent Harness and Calendar System

## Decision

The system uses a bounded, tool-driven Agent loop for owner messages. The user does not need
to type a structured command or confirm every valid calendar update. After a valid update the
Agent reports the result. This convenience does not grant the model write access: every
calendar mutation is accepted or rejected by the Calendar System.

## Agent boundary

The Agent owns interpretation, context selection, tool sequencing and the final explanation.
It may only call allow-listed tool contracts. It cannot access ORM entities, repositories,
credentials, provider SDKs or database sessions. Every turn has a maximum step count, model
budget, tool timeout and bounded observation size.

Every QQ direct message and eligible mail Inbox item creates exactly one persistent `AgentRun`
identified by its Inbox item. A run stores control state, tool-call identifiers and bounded
observations, but refers to Inbox for source content. Runs execute through the durable Job queue;
the QQ process may execute a newly queued run immediately, while the queued job remains the
recovery path. A repeated provider message reuses the same run and cannot repeat a completed tool
call. Transient model, retrieval and infrastructure failures are retried; policy rejection, stale
version and ambiguity are observations; unexpected programming failures terminate the attempt.

The model returns either a final response or one validated tool call. The harness validates
the tool name and JSON arguments, executes the tool, appends a bounded tool observation, and
continues until a final response or a safety limit is reached. Tool errors are observations,
not permission to bypass the tool boundary.

## Calendar System

Calendar operations are exposed through a single Calendar System facade. The facade owns:

- owner authorization;
- target resolution and ambiguity rejection;
- active-status and time-zone validation;
- optimistic version checks;
- conflict and policy checks;
- idempotency keys;
- reminder consistency;
- audit records and result rendering.

The Agent can request `find_agenda_candidates`, `get_agenda`, `update_agenda`, and
`update_reminder`. It cannot call `AgendaCommandPort`, `ReminderCommandPort`, repositories or
Actions directly. A request such as “刚才那个任务改到明天” is valid only when the facade can
resolve exactly one active target and a complete timezone-aware patch. Otherwise the system
rejects the operation and the Agent asks a focused question.

The facade performs no Agenda or Reminder write itself. Every mutation creates or reuses a
persistent Actions-owned `ActionRequest`; Actions is the only component allowed to call Agenda and
Reminder command ports. Action execution records authorization, operation type, idempotency key,
target version, outcome and audit event. Agenda changes cancel reminders for the previous version
and create idempotent reminders for the new version. Create and update both reject overlapping
active entries, excluding the update target itself.

Authorization is supplied through a Calendar-owned authorization port. A caller-provided literal
such as `owner` is not itself proof of identity. Tool definitions use the provider-neutral shared
tool contract; Calendar System does not depend on the Agent module.

## Retrieval context

RAG is not an MCP transport in the runtime path. The Context Assembler performs bounded
query rewriting, hybrid retrieval and source filtering, then injects labelled T2 evidence
into the Agent turn. LLM query rewriting has a strict schema, timeout and deterministic
fallback. Recent conversation, open clarification state, relevant active Agenda entries and pending
Proposals are labelled separately from T2 RAG evidence. RAG evidence can inform a decision but
cannot become calendar truth.

## Compatibility policy

This architecture is a clean replacement for the previous command-first understanding path.
Production QQ and mail processing use the persistent AgentRun path. Legacy confirmation, revise,
complete, snooze and reminder parsers are removed after their Calendar System equivalents have
coverage; no compatibility shim is retained.

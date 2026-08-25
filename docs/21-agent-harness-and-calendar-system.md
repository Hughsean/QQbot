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

The facade may use existing Agenda, Reminder and Action implementations internally. Their
implementation is an internal detail of the Calendar System and is not an Agent contract.

## Retrieval context

RAG is not an MCP transport in the runtime path. The Context Assembler performs bounded
query rewriting, hybrid retrieval and source filtering, then injects labelled T2 evidence
into the Agent turn. LLM query rewriting has a strict schema, timeout and deterministic
fallback. RAG evidence can inform a decision but cannot become calendar truth.

## Compatibility policy

This architecture is a clean replacement for the previous command-first understanding path.
No compatibility shim is required. Old command routing may be deleted once the Agent path and
Calendar System tests replace its coverage.

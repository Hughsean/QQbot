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

All internal clocks use UTC instants and do not depend on the host timezone. The Agent receives the
owner timezone and a current reference time on every turn; when no other timezone is explicitly
stated, relative dates and clock times are interpreted in the configured owner timezone (by
default `Asia/Shanghai`) and converted to ISO-8601 values with the correct offset before Calendar
System execution. Calendar records keep the UTC instant plus their original IANA timezone for
display.
All model-facing calendar reads and owner-facing reminder/proposal messages render instants in the
configured owner timezone. Calendar tool writes require ISO-8601 offsets. An offset-bearing value is
an absolute instant and must never be stripped and reinterpreted as a local wall-clock value.

Every QQ direct message and eligible mail Inbox item creates exactly one persistent `AgentRun`
identified by its Inbox item. A run stores control state, tool-call identifiers, argument hashes
and bounded observations, but refers to Inbox for source content. Each completed tool call is
checkpointed atomically with its audit row; recovery resumes with those observations and does not
repeat the same call identifier and arguments. Runs execute through the durable Job queue;
the QQ process may execute a newly queued run immediately, while the queued job remains the
recovery path. A repeated provider message reuses the same run and cannot repeat a completed tool
call. Transient model, retrieval and infrastructure failures are retried; policy rejection, stale
version and ambiguity are observations; unexpected programming failures terminate the attempt.
For `QQ_DIRECT`, a queued recovery job does nothing when the synchronous path already completed the
run. If the Worker itself completes a previously failed run, it freezes a dedicated recovery
delivery marker and creates one idempotent `QQ_DIRECT_AGENT_RESULT` intent; a retry after a crash
replays that intent without repeating Agent execution. This path never asks for a mail notification
source and does not apply mail quiet-hour policy to the delayed answer of an active user request.

`AgentRun` is not a logical conversation. QQ direct messages attach to a durable `Conversation`
identified by the owner channel/thread. Eligible mail attaches to an `EventCase` identified by the
provider thread, or a stable message identity when no thread exists. A run links one Inbox item to
one or both scopes. Context assembly reads bounded scoped history before generic retrieval, keeping
unrelated mail out of the user's dialogue while retaining multiple instances of one event together.
The stable system policy and scoped history are assembled before the volatile current Inbox item and
tool observations, providing a cache-friendly prompt prefix without treating raw Inbox data as state.

The model returns either a final response or one validated tool call. The harness validates
the tool name and JSON arguments, executes the tool, appends a bounded tool observation, and
continues until a final response or a safety limit is reached. Tool errors are observations,
not permission to bypass the tool boundary.

The allow-list also includes a narrowly scoped Identity tool for registering an owner group-chat
display alias. The tool is callable only by the authenticated owner AgentRun and writes only
Identity-owned alias state. Context assembly reads those aliases as trusted attribution rules for
forwarded transcript speaker labels; it does not make the transcript itself trusted or actionable.
Two further narrowly scoped tools follow the same pattern (ADR-0014): `register_mail_rule`
(Identity-owned owner mail notification rules) and `find_recent_mail` (Inbox-owned read-only
recent-mail metadata query with masked senders, bounded limits and T2 labeling, so "did you
receive my mail" is answered from persisted inbox state instead of retrieval luck).

Each final result also carries a persisted delivery decision. A direct QQ result is returned only
to the current conversation. A mail result follows ADR-0014: the model applies a classification
matrix — commitment mail (interview/assessment/appointments/itinerary changes) and deadline mail
(expiry, arrears, cutoffs) must be `NOTIFY`; confirmations, receipts, marketing and non-actionable
notices are `HOLD`; unclassifiable mail leans toward `NOTIFY` because silence is the single-user
failure mode. A `NOTIFY` content is the push body itself and must be self-contained (source, key
times, required action); generic follow-up questions must never be pushed. The notification renderer
prefixes every mail result with its source subject. The final delivery is
resolved deterministically in code: an owner-registered mail rule (sender/subject containment,
`NOTIFY` or `HOLD`) overrides the model's choice; otherwise the model's matrix decision stands.
Mail AgentRuns never write calendar state — mutation tools are denied for non-`QQ_DIRECT` sources
at the Calendar authorization boundary. Every completed mail run summary additionally enters the
next-morning `MAIL_DIGEST` notification (idempotent per day) unless that run already produced a
mail-result notification, so a `HOLD` means "not immediate", never "invisible". Legacy polling of
`NEEDS_REVIEW` items and standalone clarification templates are not permitted.

The QQ presentation boundary, rather than the model, identifies message origin. Direct Agent
replies use the configured nickname and a full-width colon. Durable mail, digest, conflict and
connection notifications receive an immutable deterministic heading at send time; mail headings
also name Outlook or QQ Mail. Reminder delivery has its own deterministic heading. Untrusted
message bodies cannot create a competing heading because square brackets are escaped before
delivery.
The reminder body contains only its title, owner-local start time and lead-time text. It never
prints internal Agenda or Reminder UUIDs or legacy text commands. Complete and defer are opaque,
owner-bound interactive buttons whose tokens are action-bound, version-bound, occurrence-bound,
single-use and valid for 24 hours. The first claimed action for an occurrence excludes its sibling.
Complete executes through an idempotent Actions-owned `COMPLETE_AGENDA` request; defer executes only
through the Reminders command gate. Provider callback acknowledgement is separate from the explicit
result message returned to the owner.

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

The Agent can request `list_agenda`, `find_agenda_candidates`, `get_agenda`, `create_agenda`,
`update_agenda`, `complete_agenda`, `cancel_agenda`, and `update_reminder`. `list_agenda` is the
authoritative bounded-range read used whenever the owner asks for the current agenda. Calendar mutations (`create_agenda`,
`update_agenda`, `complete_agenda`, `cancel_agenda`, `update_reminder`) are authorized only for
`QQ_DIRECT`-sourced runs; mail-sourced runs are read-only on the calendar and receive a permission
observation instead. `create_agenda` accepts an optional `reminder_due_at` (offset-bearing
ISO-8601, not later than the entry start) for owners who name an exact reminder time; the reply
must state the effective reminder time. The Agent cannot call `AgendaCommandPort`,
`ReminderCommandPort`, repositories or Actions directly. A request such as “刚才那个任务改到明天” is valid only when the facade can
resolve exactly one active target and a complete timezone-aware patch. Otherwise the system
rejects the operation and the Agent asks a focused question.

Successful create receipts include the title, normalized interval, timezone and effective reminder
time in addition to persistent identifiers. For an explicit multi-entry request, the loop counts
successful `create_agenda` receipts and rejects an early final response until the requested count is
covered. If the bounded loop cannot complete every entry, it reports the exact confirmed fraction
instead of claiming that the whole request succeeded. Short acknowledgement-only QQ turns are
completed deterministically with a short acknowledgement and do not replay agenda context.
If `list_agenda` has already returned a valid successful observation but DeepSeek exhausts its
bounded retries with an empty or otherwise invalid JSON response, the harness renders the ACTIVE
items directly from that observation. It never falls back to conversation history and never turns a
successful authoritative read into a generic processing failure.

The facade performs no Agenda or Reminder write itself. Every mutation creates or reuses a
persistent Actions-owned `ActionRequest`; Actions is the only component allowed to call Agenda and
Reminder command ports. Action execution records authorization, operation type, idempotency key,
target version, outcome and audit event. Agenda changes cancel reminders for the previous version
and create idempotent reminders for the new version. Create and update both reject overlapping
active entries, excluding the update target itself.
Completing an Agenda entry is a versioned state transition from `ACTIVE` to `COMPLETED`, not a
physical delete. The retained row supports audit, idempotency and stale-interaction rejection, while
all current-agenda reads exclude it. User-facing responses must not describe a completed row as a
current Agenda item or claim that it was deleted or archived.
Passing `ends_at` never implies successful attendance or task completion and does not automatically
change the entry state. Without an explicit owner complete/cancel action, the entry remains ACTIVE.

Authorization is supplied explicitly through a Calendar-owned authorization port during Bootstrap.
The principal comes from the authenticated AgentRun; Calendar System has no default or caller-
provided literal fallback. Tool definitions use the provider-neutral shared tool contract; Calendar
System does not depend on the Agent module.

## Retrieval context

RAG is not an MCP transport in the runtime path. The Context Assembler performs bounded
query rewriting, hybrid retrieval and source filtering, then injects labelled T2 evidence
into the Agent turn. LLM query rewriting has a strict schema, timeout and deterministic
fallback. Recent conversation, open clarification state, relevant active Agenda entries and pending
Proposals are labelled separately from T2 RAG evidence. RAG evidence can inform a decision but
cannot become calendar truth.
If normalization or query rewriting removes every searchable token, retrieval returns no chunks and
does not call the embedding provider. Context-assembly failures are persisted on the AgentRun before
the immediate or recovery path returns; permanent input failures are not retried as transient
provider failures. Provider JSON output that is malformed receives bounded retries; `InvalidOutput`
remains retryable at the durable AgentRun boundary because a later provider response may be valid.
Internal exception text is never returned over QQ.

Understanding is optional structured extraction, not an AgentRun gate. QQ direct messages and
eligible mail create/queue AgentRuns after deterministic normalization. Batch extraction may produce
candidates for later use, but it cannot delay or replace the Agent's interpretation.

## Compatibility policy

This architecture is a clean replacement for the previous command-first understanding path.
Production QQ and mail processing use the persistent AgentRun path. QQ Router does not retain
confirmation, revise, complete, snooze, reminder or general-answer parser fallbacks; no
compatibility shim is retained.

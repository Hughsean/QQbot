"""Bounded Agent loop with allow-listed tool execution and observations."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from qq_time_agent.contracts.clock import Clock, SystemClock
from qq_time_agent.contracts.tools import ToolCallContext
from qq_time_agent.modules.agent.application.model_failure_logging import log_model_failure
from qq_time_agent.modules.agent.application.observation_codec import (
    canonicalize_observation_output,
    observation_token_text,
)
from qq_time_agent.modules.agent.application.request_guards import (
    agenda_list_fallback,
    creation_coverage_observation,
    expected_agenda_creates,
    incomplete_creation_reply,
    is_short_acknowledgement,
    successful_agenda_creates,
)
from qq_time_agent.modules.agent.application.system_instruction import SYSTEM_INSTRUCTION
from qq_time_agent.modules.agent.application.tool_call_validation import (
    arguments_hash,
    validate_schema,
)
from qq_time_agent.modules.agent.contracts import (
    AgentFinal,
    AgentModelPort,
    AgentRequest,
    AgentResponse,
    AgentResponseMode,
    AgentResponseProtocolError,
    AgentToolPort,
    ToolObservation,
)
from qq_time_agent.modules.agent.contracts.models import AgentToolCall
from qq_time_agent.modules.ai_gateway.contracts import AgentMessage, ModelFailure, estimate_tokens

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentLoopConfig:
    max_steps: int = 8
    tool_timeout_seconds: float = 8.0
    max_observation_chars: int = 12_000
    model_output_token_budget: int = 9_600
    max_output_tokens_per_request: int = 1_200
    observation_token_budget: int = 4_000

    def __post_init__(self) -> None:
        if not 1 <= self.max_steps <= 20:
            raise ValueError("Agent max steps must be between 1 and 20")
        if (
            self.tool_timeout_seconds <= 0
            or self.max_observation_chars < 500
            or self.model_output_token_budget < 1
            or self.max_output_tokens_per_request < 1
            or self.observation_token_budget < 500
        ):
            raise ValueError("Agent loop limits are invalid")
        if self.max_output_tokens_per_request > self.model_output_token_budget:
            raise ValueError("Per-request output limit exceeds Agent output budget")
        if self.model_output_token_budget < 2 * self.max_output_tokens_per_request:
            raise ValueError("Agent output budget must reserve a final response request")


class AgentLoop:
    def __init__(
        self,
        model: AgentModelPort,
        tools: AgentToolPort,
        config: AgentLoopConfig | None = None,
        owner_timezone: str = "Asia/Shanghai",
        clock: Clock | None = None,
    ) -> None:
        try:
            self._owner_zone = ZoneInfo(owner_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Agent owner timezone is invalid") from exc
        self._model = model
        self._tools = tools
        self._config = config or AgentLoopConfig()
        self._owner_timezone = owner_timezone
        self._clock = clock or SystemClock()

    async def run(  # noqa: C901
        self,
        owner_id: str,
        message: str,
        context: str = "",
        timeline_messages: tuple[AgentMessage, ...] = (),
        prior_observations: tuple[ToolObservation, ...] = (),
        on_tool_call: Callable[[ToolObservation], Awaitable[None]] | None = None,
        on_boundary: Callable[[], Awaitable[None]] | None = None,
        on_event: Callable[[str, int, Mapping[str, object]], Awaitable[None]] | None = None,
        source_type: str = "QQ_DIRECT",
        inbox_item_id: UUID | None = None,
    ) -> AgentFinal:
        if not owner_id.strip() or not message.strip():
            raise ValueError("Agent owner and message are required")
        run_id = uuid4().hex[:16]
        tool_context = ToolCallContext(source_type, inbox_item_id)
        reference_time = self._clock.now()
        if reference_time.tzinfo is None or reference_time.utcoffset() is None:
            raise ValueError("Agent reference time must be timezone-aware")
        owner_time = reference_time.astimezone(self._owner_zone)
        observations = list(prior_observations)
        calls = {item.call_id: item.arguments_hash for item in observations if item.arguments_hash}
        if source_type == "QQ_DIRECT" and is_short_acknowledgement(message):
            return AgentFinal("好的。")
        expected_creates = expected_agenda_creates(message) if source_type == "QQ_DIRECT" else 0
        LOGGER.info(
            "Agent 回合开始: 已接受用户请求, 准备进行模型决策",
            extra={
                "role": "agent",
                "run_id": run_id,
                "status": "started",
                "step": len(observations),
                "context_chars": len(context),
            },
        )
        await _emit(on_event, "ROUND_STARTED", 0, {"observation_count": len(observations)})
        tool_steps = sum(not item.is_error for item in observations)
        reserved_output = self._config.max_output_tokens_per_request
        remaining_output = self._config.model_output_token_budget
        request_step = 0
        while tool_steps < self._config.max_steps and remaining_output > reserved_output:
            if on_boundary is not None:
                await on_boundary()
            output_tokens = min(
                self._config.max_output_tokens_per_request,
                remaining_output - reserved_output,
            )
            if output_tokens < 1:
                break
            response = await self._respond(
                message,
                context,
                timeline_messages,
                observations,
                owner_time,
                request_step,
                output_tokens,
                AgentResponseMode.TOOL_OR_FINAL,
                run_id,
                on_event,
            )
            remaining_output -= output_tokens
            if response.final is not None:
                completed_creates = successful_agenda_creates(observations)
                if completed_creates < expected_creates:
                    observations.append(
                        creation_coverage_observation(
                            request_step, expected_creates, completed_creates
                        )
                    )
                    request_step += 1
                    continue
                self._log_final(run_id, request_step, response.final, observations)
                return response.final
            call = response.tool_call
            if call is None:
                raise AgentResponseProtocolError("Agent response omitted final and tool call")
            existing_hash = calls.get(call.call_id)
            observation = await self._observe_call(
                owner_id, call, calls, observations, run_id, request_step, on_event, tool_context
            )
            if existing_hash is not None:
                if existing_hash != arguments_hash(call.arguments):
                    observations.append(observation)
                request_step += 1
                continue
            observations.append(observation)
            tool_steps += 1
            if on_tool_call is not None:
                await on_tool_call(observation)
            request_step += 1

        final_tokens = min(self._config.max_output_tokens_per_request, remaining_output)
        if final_tokens < 1:
            raise RuntimeError("Agent output token budget exhausted before finalization")
        if on_boundary is not None:
            await on_boundary()
        response = await self._respond(
            message,
            context,
            timeline_messages,
            observations,
            owner_time,
            request_step,
            final_tokens,
            AgentResponseMode.FINAL_ONLY,
            run_id,
            on_event,
        )
        if response.final is None:
            raise AgentResponseProtocolError("Agent finalization response must be final")
        completed_creates = successful_agenda_creates(observations)
        if completed_creates < expected_creates:
            return AgentFinal(incomplete_creation_reply(expected_creates, completed_creates))
        self._log_final(run_id, request_step, response.final, observations)
        return response.final

    async def _respond(
        self,
        message: str,
        context: str,
        timeline_messages: tuple[AgentMessage, ...],
        observations: list[ToolObservation],
        owner_time: datetime,
        step: int,
        output_tokens: int,
        response_mode: AgentResponseMode,
        run_id: str,
        on_event: Callable[[str, int, Mapping[str, object]], Awaitable[None]] | None = None,
    ) -> AgentResponse:
        model_observations = _bound_observations(
            observations, self._config.observation_token_budget
        )
        tools = () if response_mode is AgentResponseMode.FINAL_ONLY else self._tools.definitions()
        try:
            started = perf_counter()
            response = await self._model.respond(
                AgentRequest(
                    SYSTEM_INSTRUCTION,
                    message,
                    context,
                    tools,
                    tuple(model_observations),
                    step,
                    self._owner_timezone,
                    owner_time,
                    output_tokens,
                    response_mode,
                    timeline_messages,
                )
            )
            await _emit(
                on_event,
                "MODEL_RESULT",
                step,
                {
                    "response_type": "final" if response.final is not None else "tool_call",
                    "duration_ms": round((perf_counter() - started) * 1000),
                    "response_mode": response_mode.value,
                },
            )
            return response
        except ModelFailure as exc:
            fallback = (
                agenda_list_fallback(observations, self._owner_timezone)
                if exc.failure_class == "InvalidOutput"
                else None
            )
            if fallback is not None:
                LOGGER.warning(
                    "Agent 模型输出无效: 使用已成功读取的权威日程结果",
                    extra={
                        "role": "agent",
                        "run_id": run_id,
                        "step": step,
                        "status": "deterministic_fallback",
                        "failure_class": exc.failure_class,
                        "observation_count": len(observations),
                    },
                )
                await _emit(
                    on_event,
                    "MODEL_RESULT",
                    step,
                    {
                        "response_type": "deterministic_fallback",
                        "response_mode": response_mode.value,
                        "failure_class": exc.failure_class,
                    },
                )
                return AgentResponse(final=AgentFinal(fallback))
            await log_model_failure(exc, run_id, step, observations, on_event)
            raise
        except Exception as exc:
            await log_model_failure(exc, run_id, step, observations, on_event)
            raise

    @staticmethod
    def _log_final(
        run_id: str,
        step: int,
        result: AgentFinal,
        observations: list[ToolObservation],
    ) -> None:
        LOGGER.info(
            "Agent 回合完成: 模型返回最终答复",
            extra={
                "role": "agent",
                "run_id": run_id,
                "step": step,
                "status": "completed",
                "result_type": "final",
                "result_chars": len(result.content),
                "observation_count": len(observations),
            },
        )

    async def _observe_call(
        self,
        owner_id: str,
        call: AgentToolCall,
        calls: dict[str, str],
        observations: list[ToolObservation],
        run_id: str,
        step: int,
        on_event: Callable[[str, int, Mapping[str, object]], Awaitable[None]] | None = None,
        tool_context: ToolCallContext | None = None,
    ) -> ToolObservation:
        definitions = self._tools.definitions()
        schema = next((item.input_schema for item in definitions if item.name == call.name), None)
        argument_hash = arguments_hash(call.arguments)
        await _emit(
            on_event,
            "TOOL_CALL_STARTED",
            step,
            {"tool_name": call.name, "call_id": call.call_id, "arguments_hash": argument_hash},
        )
        if schema is None:
            return _error_observation(call, "未注册的工具", argument_hash)
        previous = calls.get(call.call_id)
        if previous is not None:
            if previous != argument_hash:
                return _error_observation(call, "call_id 已用于不同参数", argument_hash)
            return next(item for item in observations if item.call_id == call.call_id)
        calls[call.call_id] = argument_hash
        try:
            validate_schema(schema, call.arguments)
        except ValueError as exc:
            observation = _error_observation(call, str(exc), argument_hash)
            await _emit(
                on_event,
                "TOOL_RESULT",
                step,
                {
                    "tool_name": call.name,
                    "call_id": call.call_id,
                    "status": "rejected",
                    "error_class": type(exc).__name__,
                },
            )
            return observation
        return await self._call(
            owner_id,
            call.name,
            call.arguments,
            call.call_id,
            argument_hash,
            run_id,
            step,
            on_event,
            tool_context,
        )

    async def _call(
        self,
        owner_id: str,
        name: str,
        arguments: object,
        call_id: str,
        arguments_hash: str,
        run_id: str,
        step: int,
        on_event: Callable[[str, int, Mapping[str, object]], Awaitable[None]] | None = None,
        tool_context: ToolCallContext | None = None,
    ) -> ToolObservation:
        if not isinstance(arguments, dict):
            LOGGER.warning(
                "Agent 工具调用拒绝: 参数不是 JSON 对象",
                extra={
                    "role": "agent",
                    "run_id": run_id,
                    "step": step,
                    "tool": name,
                    "call_id": call_id,
                    "status": "invalid_arguments",
                },
            )
            return _error_observation(
                AgentToolCall(call_id, name, {}),
                "工具参数必须是 JSON 对象",
                arguments_hash,
            )
        started = perf_counter()
        try:
            output = await asyncio.wait_for(
                self._tools.call(
                    owner_id, name, arguments, tool_context or ToolCallContext("QQ_DIRECT")
                ),
                self._config.tool_timeout_seconds,
            )
        except (PermissionError, LookupError, ValueError) as exc:
            LOGGER.warning(
                "Agent 工具调用失败: 工具返回异常",
                extra={
                    "role": "agent",
                    "run_id": run_id,
                    "step": step,
                    "tool": name,
                    "call_id": call_id,
                    "status": "rejected",
                    "failure_class": type(exc).__name__,
                    "elapsed_ms": round((perf_counter() - started) * 1000),
                    "argument_names": ",".join(sorted(arguments)),
                },
            )
            return _error_observation(
                AgentToolCall(call_id, name, {}),
                f"工具拒绝请求: {type(exc).__name__}",
                arguments_hash,
            )
        except Exception:
            LOGGER.exception(
                "Agent 工具调用失败: 基础设施或程序异常, 交由 Job 重试",
                extra={
                    "role": "agent",
                    "run_id": run_id,
                    "step": step,
                    "tool": name,
                    "call_id": call_id,
                    "status": "unexpected_failure",
                    "elapsed_ms": round((perf_counter() - started) * 1000),
                },
            )
            raise
        LOGGER.info(
            "Agent 工具调用完成: 已获得受控观察结果",
            extra={
                "role": "agent",
                "run_id": run_id,
                "step": step,
                "tool": name,
                "call_id": call_id,
                "status": "completed",
                "elapsed_ms": round((perf_counter() - started) * 1000),
                "argument_names": ",".join(sorted(arguments)),
                "result_type": type(output).__name__,
            },
        )
        observation = ToolObservation(
            call_id,
            name,
            _bounded(output, self._config.max_observation_chars),
            False,
            arguments_hash,
        )
        await _emit(
            on_event,
            "TOOL_RESULT",
            step,
            {
                "tool_name": name,
                "call_id": call_id,
                "status": "completed",
                "result_type": type(output).__name__,
            },
        )
        return observation


async def _emit(
    callback: Callable[[str, int, Mapping[str, object]], Awaitable[None]] | None,
    event_type: str,
    step: int,
    metadata: Mapping[str, object],
) -> None:
    if callback is not None:
        await callback(event_type, step, metadata)


def _error_observation(call: AgentToolCall, message: str, arguments_hash: str) -> ToolObservation:
    return ToolObservation(
        call.call_id,
        call.name,
        canonicalize_observation_output({"error": message}, 12_000),
        True,
        arguments_hash,
    )


def _bound_observations(
    observations: list[ToolObservation], maximum_tokens: int
) -> list[ToolObservation]:
    selected: list[ToolObservation] = []
    used = 0
    for item in reversed(observations):
        cost = estimate_tokens(observation_token_text(item.output))
        if selected and used + cost > maximum_tokens:
            break
        selected.append(item)
        used += cost
    selected.reverse()
    return selected


def _bounded(value: object, maximum: int) -> str:
    return canonicalize_observation_output(value, maximum)

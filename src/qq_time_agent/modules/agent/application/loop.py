"""Bounded Agent loop with allow-listed tool execution and observations."""

import asyncio
import logging
from dataclasses import dataclass
from time import perf_counter
from uuid import uuid4

from qq_time_agent.modules.agent.contracts import (
    AgentFinal,
    AgentModelPort,
    AgentRequest,
    AgentToolPort,
    ToolObservation,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentLoopConfig:
    max_steps: int = 8
    tool_timeout_seconds: float = 8.0
    max_observation_chars: int = 12_000

    def __post_init__(self) -> None:
        if not 1 <= self.max_steps <= 20:
            raise ValueError("Agent max steps must be between 1 and 20")
        if self.tool_timeout_seconds <= 0 or self.max_observation_chars < 500:
            raise ValueError("Agent loop limits are invalid")


class AgentLoop:
    def __init__(
        self,
        model: AgentModelPort,
        tools: AgentToolPort,
        config: AgentLoopConfig | None = None,
    ) -> None:
        self._model = model
        self._tools = tools
        self._config = config or AgentLoopConfig()

    async def run(self, owner_id: str, message: str, context: str = "") -> AgentFinal:
        if not owner_id.strip() or not message.strip():
            raise ValueError("Agent owner and message are required")
        run_id = uuid4().hex[:16]
        observations: list[ToolObservation] = []
        LOGGER.info(
            "Agent 回合开始: 已接受用户请求, 准备进行模型决策",
            extra={
                "role": "agent",
                "run_id": run_id,
                "status": "started",
                "step": 0,
                "context_chars": len(context),
            },
        )
        for step in range(self._config.max_steps):
            try:
                response = await self._model.respond(
                    AgentRequest(
                        _SYSTEM_INSTRUCTION,
                        message,
                        context[: self._config.max_observation_chars],
                        self._tools.definitions(),
                        tuple(observations),
                        step,
                    )
                )
            except Exception as exc:
                LOGGER.exception(
                    "Agent 模型回合失败: 未能获得下一步决策",
                    extra={
                        "role": "agent",
                        "run_id": run_id,
                        "step": step,
                        "status": "model_failed",
                        "failure_class": type(exc).__name__,
                        "observation_count": len(observations),
                    },
                )
                raise
            if response.final is not None:
                LOGGER.info(
                    "Agent 回合完成: 模型返回最终答复",
                    extra={
                        "role": "agent",
                        "run_id": run_id,
                        "step": step,
                        "status": "completed",
                        "result_type": "final",
                        "result_chars": len(response.final.content),
                        "observation_count": len(observations),
                    },
                )
                return response.final
            call = response.tool_call
            if call is None:
                raise RuntimeError("Agent response omitted final and tool call")
            observation = await self._call(
                owner_id, call.name, call.arguments, call.call_id, run_id, step
            )
            observations.append(observation)
        LOGGER.warning(
            "Agent 回合停止: 达到最大工具步骤, 未生成最终答复",
            extra={
                "role": "agent",
                "run_id": run_id,
                "step": self._config.max_steps,
                "status": "step_limit",
                "observation_count": len(observations),
            },
        )
        raise RuntimeError("Agent reached the maximum tool steps")

    async def _call(
        self,
        owner_id: str,
        name: str,
        arguments: object,
        call_id: str,
        run_id: str,
        step: int,
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
            return ToolObservation(call_id, name, "工具参数必须是 JSON 对象", True)
        started = perf_counter()
        try:
            output = await asyncio.wait_for(
                self._tools.call(owner_id, name, arguments),
                self._config.tool_timeout_seconds,
            )
        except Exception as exc:
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
            return ToolObservation(call_id, name, f"工具拒绝请求: {type(exc).__name__}", True)
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
        return ToolObservation(call_id, name, _bounded(output, self._config.max_observation_chars))


_SYSTEM_INSTRUCTION = """你是所有者的时间管理 Agent。你可以调用白名单工具, 但工具结果是事实来源。
只能通过工具操作日程, 不能声称执行了未成功的操作。遇到目标不明确、参数不完整或工具拒绝时,
向用户提出最小必要追问。工具调用必须返回一个 JSON 对象, 不得调用未列出的工具。"""


def _bounded(value: object, maximum: int) -> object:
    if isinstance(value, str):
        return value[:maximum]
    if isinstance(value, (dict, list, tuple)):
        text = repr(value)
        return text[:maximum]
    return value

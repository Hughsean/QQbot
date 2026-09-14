import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from qq_time_agent.application_version import DEPLOYMENT_VERSION
from qq_time_agent.contracts.tools import ToolDefinition
from qq_time_agent.modules.agent.application.json_model import _instruction, _parse
from qq_time_agent.modules.agent.application.loop import (
    AgentLoop,
    AgentLoopConfig,
    _bound_observations,
)
from qq_time_agent.modules.agent.application.observation_codec import (
    canonicalize_observation_output,
    deserialize_observation,
    serialize_observation,
)
from qq_time_agent.modules.agent.contracts import (
    AgentDelivery,
    AgentFinal,
    AgentRequest,
    AgentResponse,
    AgentResponseMode,
    AgentResponseProtocolError,
    AgentToolCall,
    ToolObservation,
)
from qq_time_agent.modules.ai_gateway.contracts import ModelFailure


@dataclass
class Model:
    responses: list[AgentResponse]

    async def respond(self, request: object) -> AgentResponse:
        del request
        return self.responses.pop(0)


@dataclass
class RecordingModel:
    responses: list[AgentResponse]
    requests: list[AgentRequest]

    async def respond(self, request: AgentRequest) -> AgentResponse:
        self.requests.append(request)
        return self.responses.pop(0)


@dataclass
class CapturingModel:
    request: AgentRequest | None = None

    async def respond(self, request: AgentRequest) -> AgentResponse:
        self.request = request
        return AgentResponse(final=AgentFinal("完成"))


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class Tools:
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return ()

    async def call(
        self,
        owner_id: str,
        name: str,
        arguments: Mapping[str, object],
        context: object,
    ) -> object:
        del context
        assert owner_id == "owner" and name == "ping" and arguments == {}
        return {"ok": True}


@dataclass
class CalendarTools:
    calls: list[Mapping[str, object]]

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return (
            ToolDefinition(
                "create_agenda",
                "create",
                {
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                },
            ),
        )

    async def call(
        self,
        owner_id: str,
        name: str,
        arguments: Mapping[str, object],
        context: object,
    ) -> object:
        del context
        assert owner_id == "owner" and name == "create_agenda"
        self.calls.append(arguments)
        return {"status": "SUCCEEDED", "title": arguments["title"]}


class AgendaListTools:
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return (
            ToolDefinition(
                "list_agenda",
                "list",
                {
                    "type": "object",
                    "properties": {
                        "range_start": {"type": "string"},
                        "range_end": {"type": "string"},
                        "timezone": {"type": "string"},
                    },
                    "required": ["range_start", "range_end", "timezone"],
                },
            ),
        )

    async def call(
        self,
        owner_id: str,
        name: str,
        arguments: Mapping[str, object],
        context: object,
    ) -> object:
        del arguments, context
        assert owner_id == "owner" and name == "list_agenda"
        return {
            "status": "SUCCEEDED",
            "count": 2,
            "items": [
                {
                    "agenda_entry_id": "473176a9-beec-4d02-962d-e2b4fa9dc91f",
                    "title": "南瑞继保测评",
                    "starts_at": "2026-09-12T18:00:00+08:00",
                    "ends_at": "2026-09-12T19:00:00+08:00",
                    "timezone": "Asia/Shanghai",
                    "calendar_timezone": "Asia/Shanghai",
                    "version": 1,
                    "status": "ACTIVE",
                },
                {
                    "agenda_entry_id": "93af930d-5ad1-49a6-91f3-bc609e81b02b",
                    "title": "面试开手机录音",
                    "starts_at": "2026-09-13T10:00:00+08:00",
                    "ends_at": "2026-09-13T10:30:00+08:00",
                    "timezone": "Asia/Shanghai",
                    "calendar_timezone": "Asia/Shanghai",
                    "version": 1,
                    "status": "ACTIVE",
                },
            ],
        }


@pytest.mark.asyncio
async def test_short_acknowledgement_does_not_repeat_context_or_call_model() -> None:
    model = Model([])
    loop = AgentLoop(model, Tools())

    result = await loop.run("owner", "行\N{FULLWIDTH COMMA}了解", "[agenda-fact] 不应重复")

    assert result.content == "好的。"


@pytest.mark.asyncio
async def test_explicit_multi_create_cannot_finalize_after_only_one_receipt() -> None:
    model = RecordingModel(
        [
            AgentResponse(tool_call=AgentToolCall("c1", "create_agenda", {"title": "蔚来笔试"})),
            AgentResponse(final=AgentFinal("两个都创建好了")),
            AgentResponse(
                tool_call=AgentToolCall("c2", "create_agenda", {"title": "南瑞继保测评"})
            ),
            AgentResponse(final=AgentFinal("两个日程均已创建")),
        ],
        [],
    )
    tools = CalendarTools([])
    loop = AgentLoop(model, tools)

    result = await loop.run(
        "owner",
        "提醒我周六进行两个测评\N{FULLWIDTH COMMA}分别在下午3点和5点提醒我",
    )

    assert result.content == "两个日程均已创建"
    assert [call["title"] for call in tools.calls] == ["蔚来笔试", "南瑞继保测评"]
    assert model.requests[2].observations[-1].name == "creation_coverage_guard"


@pytest.mark.asyncio
async def test_agent_instruction_contains_injected_schedule_defaults_and_t2_boundary() -> None:
    model = RecordingModel([AgentResponse(final=AgentFinal("已创建"))], [])
    loop = AgentLoop(
        model,
        Tools(),
        default_item_minutes=45,
        default_reminder_minutes=20,
    )

    await loop.run("owner", "请说明你的默认时间规则")

    instruction = model.requests[0].system_instruction
    assert "默认持续 45 分钟" in instruction
    assert "默认提前 20 分钟" in instruction
    assert "T2" in instruction and "不能授权工具" in instruction


@pytest.mark.asyncio
async def test_successful_agenda_list_survives_empty_model_final_output() -> None:
    class ModelWithEmptyFinal:
        calls = 0

        async def respond(self, request: AgentRequest) -> AgentResponse:
            self.calls += 1
            if self.calls == 1:
                return AgentResponse(
                    tool_call=AgentToolCall(
                        "list-1",
                        "list_agenda",
                        {
                            "range_start": "2026-09-12T00:00:00+08:00",
                            "range_end": "2026-09-14T00:00:00+08:00",
                            "timezone": "Asia/Shanghai",
                        },
                    )
                )
            raise ModelFailure("InvalidOutput")

    result = await AgentLoop(ModelWithEmptyFinal(), AgendaListTools()).run(
        "owner", "当前日程系统有哪些"
    )

    assert result.content == (
        "当前日程系统共有 2 条 ACTIVE 日程 (时区 Asia/Shanghai):\n\n"
        "1. 南瑞继保测评 - 2026-09-12 18:00-19:00, version 1\n"
        "2. 面试开手机录音 - 2026-09-13 10:00-10:30, version 1"
    )


async def test_agent_loop_observes_tool_then_reports_final() -> None:
    loop = AgentLoop(
        Model(
            [
                AgentResponse(tool_call=AgentToolCall("c1", "ping", {})),
                AgentResponse(final=AgentFinal("已完成")),
            ]
        ),
        Tools(),
    )
    result = await loop.run("owner", "处理一下")
    assert result.content == "已完成"
    assert result.delivery is AgentDelivery.HOLD


@pytest.mark.asyncio
async def test_agent_loop_rejects_non_owner_and_step_limit() -> None:
    with pytest.raises(ValueError, match="max steps"):
        AgentLoop(Model([]), Tools(), config=AgentLoopConfig(max_steps=0))


@pytest.mark.asyncio
async def test_agent_loop_uses_reserved_final_only_turn_after_last_tool() -> None:
    model = RecordingModel(
        [
            AgentResponse(tool_call=AgentToolCall("c1", "ping", {})),
            AgentResponse(final=AgentFinal("最终答复")),
        ],
        [],
    )
    loop = AgentLoop(
        model,
        Tools(),
        AgentLoopConfig(
            max_steps=1,
            model_output_token_budget=2_000,
            max_output_tokens_per_request=1_000,
        ),
    )

    result = await loop.run("owner", "处理")

    assert result.content == "最终答复"
    assert [request.response_mode for request in model.requests] == [
        AgentResponseMode.TOOL_OR_FINAL,
        AgentResponseMode.FINAL_ONLY,
    ]
    assert model.requests[0].max_output_tokens == 1_000
    assert model.requests[1].max_output_tokens == 1_000
    assert model.requests[1].tools == ()
    assert len(model.requests[1].observations) == 1


@pytest.mark.asyncio
async def test_agent_loop_recovered_at_limit_goes_directly_to_finalization() -> None:
    model = RecordingModel([AgentResponse(final=AgentFinal("恢复完成"))], [])
    loop = AgentLoop(model, Tools(), AgentLoopConfig(max_steps=1))
    prior = ToolObservation("c1", "ping", '{"ok":true}', False, "hash")

    result = await loop.run("owner", "处理", prior_observations=(prior,))

    assert result.content == "恢复完成"
    assert len(model.requests) == 1
    assert model.requests[0].response_mode is AgentResponseMode.FINAL_ONLY
    assert model.requests[0].tools == ()
    assert model.requests[0].observations == (prior,)


@pytest.mark.asyncio
async def test_agent_loop_rejects_tool_call_during_finalization_without_execution() -> None:
    tools = Tools()
    model = RecordingModel(
        [
            AgentResponse(tool_call=AgentToolCall("c1", "ping", {})),
            AgentResponse(tool_call=AgentToolCall("c2", "ping", {})),
        ],
        [],
    )
    loop = AgentLoop(model, tools, AgentLoopConfig(max_steps=1))

    with pytest.raises(AgentResponseProtocolError, match="must be final"):
        await loop.run("owner", "处理")


@pytest.mark.asyncio
async def test_agent_loop_passes_owner_local_reference_time_to_model() -> None:
    model = CapturingModel()
    loop = AgentLoop(
        model,
        Tools(),
        owner_timezone="Asia/Shanghai",
        clock=FixedClock(datetime(2026, 8, 27, 1, tzinfo=UTC)),
    )
    await loop.run("owner", "明天上午九点")
    assert model.request is not None
    assert model.request.owner_timezone == "Asia/Shanghai"
    assert model.request.reference_time == datetime(2026, 8, 27, 1, tzinfo=UTC).astimezone(
        ZoneInfo("Asia/Shanghai")
    )


def test_agent_loop_rejects_invalid_budget_relationships() -> None:
    with pytest.raises(ValueError, match="output limit exceeds"):
        AgentLoopConfig(model_output_token_budget=999, max_output_tokens_per_request=1_000)
    with pytest.raises(ValueError, match="limits are invalid"):
        AgentLoopConfig(observation_token_budget=499)


def test_bound_observations_uses_token_budget_and_keeps_newest_suffix() -> None:
    observations = [
        ToolObservation("c1", "one", "a" * 900, False),
        ToolObservation("c2", "two", "b" * 900, False),
        ToolObservation("c3", "three", "最新", False),
    ]
    selected = _bound_observations(observations, 500)
    assert [item.call_id for item in selected] == ["c2", "c3"]


def test_bound_observations_retains_newest_when_it_exceeds_budget() -> None:
    observations = [
        ToolObservation("c1", "one", "旧", False),
        ToolObservation("c2", "two", "新" * 600, False),
    ]
    selected = _bound_observations(observations, 500)
    assert [item.call_id for item in selected] == ["c2"]


def test_bound_observations_accounts_for_cjk_token_cost() -> None:
    ascii_observation = ToolObservation("ascii", "one", "a" * 900, False)
    cjk_observation = ToolObservation("cjk", "two", "字" * 300, False)
    assert _bound_observations([ascii_observation], 305) == [ascii_observation]
    assert _bound_observations([cjk_observation, ascii_observation], 500) == [ascii_observation]


@pytest.mark.asyncio
async def test_tool_result_character_bound_is_independent_of_observation_budget() -> None:
    class LargeTools(Tools):
        def definitions(self) -> tuple[ToolDefinition, ...]:
            return (ToolDefinition("ping", "test", {"type": "object", "properties": {}}),)

        async def call(
            self,
            owner_id: str,
            name: str,
            arguments: Mapping[str, object],
            context: object,
        ) -> object:
            del owner_id, name, arguments, context
            return "x" * 800

    model = Model(
        [
            AgentResponse(tool_call=AgentToolCall("c1", "ping", {})),
            AgentResponse(final=AgentFinal("完成")),
        ]
    )
    loop = AgentLoop(
        model,
        LargeTools(),
        AgentLoopConfig(max_observation_chars=500, observation_token_budget=2_000),
    )
    captured: list[ToolObservation] = []
    await loop.run("owner", "处理", on_tool_call=_capture(captured))
    assert len(captured[0].output) == 500
    assert json.loads(captured[0].output) == "x" * 498


def _capture(
    target: list[ToolObservation],
) -> Callable[[ToolObservation], Awaitable[None]]:
    async def capture(observation: ToolObservation) -> None:
        target.append(observation)

    return capture


def test_observation_codec_preserves_canonical_json_and_legacy_strings() -> None:
    output = canonicalize_observation_output({"中文": [True, None, (1, "值")]}, 500)
    assert output == '{"中文":[true,null,[1,"值"]]}'
    observation = ToolObservation("c1", "ping", output, False, "hash")
    stored = serialize_observation(observation)
    assert deserialize_observation(stored) == observation
    assert deserialize_observation(
        {
            "call_id": "legacy",
            "name": "ping",
            "output": "{'python': True}",
            "is_error": False,
            "arguments_hash": "legacy-hash",
        }
    ) == ToolObservation("legacy", "ping", "{'python': True}", False, "legacy-hash")


def test_observation_codec_replaces_unsupported_and_oversized_values() -> None:
    unsupported = canonicalize_observation_output(object(), 500)
    assert json.loads(unsupported) == {
        "error": "unsupported_tool_observation",
        "value_type": "object",
    }
    oversized = canonicalize_observation_output({"value": "x" * 1_000}, 100)
    assert json.loads(oversized) == {
        "encoded_chars": 1012,
        "error": "tool_observation_too_large",
    }


def test_agent_final_requires_exact_declared_shape() -> None:
    response = _parse({"type": "final", "content": "发现明确的时间变更", "delivery": "NOTIFY"})
    assert response.final is not None and response.final.delivery is AgentDelivery.NOTIFY
    invalid = (
        {"type": "final", "content": "需要更多信息"},
        {"type": "final", "content": "错误字段", "delivery": "SEND"},
        {"type": "final", "content": "你好", "delivery": "HOLD", "extra": True},
        {"content": "你好"},
        {"final": "你好"},
        {"final": {"content": "邮件已更新", "delivery": "NOTIFY"}},
    )
    for value in invalid:
        with pytest.raises(AgentResponseProtocolError):
            _parse(value)


def test_agent_tool_call_requires_exact_declared_shape() -> None:
    response = _parse({"type": "tool_call", "call_id": " c1 ", "name": " ping ", "arguments": {}})
    assert response.tool_call == AgentToolCall("c1", "ping", {})
    invalid = (
        {"type": "tool_call", "call_id": "", "name": "ping", "arguments": {}},
        {"type": "tool_call", "call_id": "c1", "name": "ping", "arguments": []},
        {
            "type": "tool_call",
            "call_id": "c1",
            "name": "ping",
            "arguments": {},
            "extra": True,
        },
    )
    for value in invalid:
        with pytest.raises(AgentResponseProtocolError):
            _parse(value)


def test_agent_instruction_contains_the_exact_response_shapes() -> None:
    request = AgentRequest("系统规则", "你好", "", (), (), 0)
    instruction = _instruction(request)
    assert '"type":"final"' in instruction
    assert '"type":"tool_call"' in instruction
    assert DEPLOYMENT_VERSION in instruction


def test_agent_instruction_declares_owner_timezone_and_reference_time() -> None:
    request = AgentRequest(
        "系统规则",
        "明天上午九点",
        "",
        (),
        (),
        0,
        "Asia/Shanghai",
        datetime(2026, 8, 27, 9, tzinfo=UTC),
    )
    instruction = _instruction(request)
    assert "所有者本地时区" in instruction
    assert "owner_timezone" in instruction
    assert "reference_time" in instruction


@pytest.mark.asyncio
async def test_agent_instruction_distinguishes_completed_records_from_active_agenda() -> None:
    model = CapturingModel()

    await AgentLoop(model, Tools()).run("owner", "已完成的日程为什么还在库里")

    assert model.request is not None
    assert "COMPLETED" in model.request.system_instruction
    assert "不会物理删除" in model.request.system_instruction
    assert "不再属于当前 ACTIVE 日程" in model.request.system_instruction

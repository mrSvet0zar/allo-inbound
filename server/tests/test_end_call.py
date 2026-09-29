"""Tests du raccrochage par l'agent en fin de conversation (outil end_call)."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.core.call_session import CallSession
from app.llm.toolbox import ALL_TOOL_DEFINITIONS, AgentToolbox, InMemoryTicketRepo
from app.llm.tools_rdv import InMemoryCalendar, ToolExecutor
from app.support.knowledge_base import InMemoryKnowledgeBase
from app.telephony.transfer import hang_up_call
from app.telephony.twilio_media import MediaStreamStart


def _make_toolbox():
    return AgentToolbox(
        rdv_executor=ToolExecutor(InMemoryCalendar()),
        knowledge_base=InMemoryKnowledgeBase(),
        ticket_repo=InMemoryTicketRepo(),
    )


def test_end_call_tool_is_declared():
    assert any(t["name"] == "end_call" for t in ALL_TOOL_DEFINITIONS)


async def test_end_call_sets_flag():
    toolbox = _make_toolbox()
    assert toolbox.end_call_requested is False
    result = json.loads(await toolbox.execute("end_call", {}))
    assert result["fin_appel"] is True
    assert toolbox.end_call_requested is True


async def test_end_call_does_not_change_outcome():
    toolbox = _make_toolbox()
    await toolbox.execute(
        "book_appointment",
        {"date": "2026-09-21", "heure": "10:00", "nom": "Durand", "motif": "x"},
    )
    await toolbox.execute("end_call", {})
    assert toolbox.outcome == "booked"


@pytest.mark.asyncio
async def test_hang_up_calls_twilio_rest_api():
    settings = Settings(twilio_account_sid="AC_test", twilio_auth_token="token")
    with patch("app.telephony.transfer.Client") as client_cls:
        result = await hang_up_call(settings, "CA42")

    assert result is True
    client_cls.return_value.calls.assert_called_once_with("CA42")
    client_cls.return_value.calls.return_value.update.assert_called_once_with(
        status="completed"
    )


def _make_session(end_call: bool):
    with (
        patch("app.core.call_session.DeepgramStream"),
        patch("app.core.call_session.ElevenLabsTTS"),
        patch("app.core.call_session.VoiceAgent") as agent_cls,
        patch("app.core.call_session.AsyncAnthropic"),
    ):
        session = CallSession(
            Settings(),
            MediaStreamStart(stream_sid="MZ1", call_sid="CA1", caller_phone=None),
            send_text=AsyncMock(),
        )

        async def run_turn(_):
            yield "Au revoir !"

        async def synthesize(_):
            yield b"\x00"

        agent_cls.return_value.escalation_requested = None
        agent_cls.return_value.end_call_requested = end_call
        session._agent.run_turn = run_turn
        session._tts.synthesize = synthesize
        session._stt = AsyncMock()
        return session


@pytest.mark.asyncio
@patch("app.core.call_session.asyncio.sleep", new_callable=AsyncMock)
@patch("app.core.call_session.hang_up_call", new_callable=AsyncMock, return_value=True)
async def test_agent_hangs_up_after_goodbye(mock_hangup, _mock_sleep):
    session = _make_session(end_call=True)
    await session._on_transcript("au revoir", is_final=True, speech_final=True)
    await session._speaking_task

    mock_hangup.assert_awaited_once()
    assert mock_hangup.await_args.args[1] == "CA1"


@pytest.mark.asyncio
@patch("app.core.call_session.hang_up_call", new_callable=AsyncMock)
async def test_no_hangup_when_not_requested(mock_hangup):
    session = _make_session(end_call=False)
    await session._on_transcript("bonjour", is_final=True, speech_final=True)
    await session._speaking_task
    mock_hangup.assert_not_awaited()

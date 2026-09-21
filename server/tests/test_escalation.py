"""Tests de l'escalade humaine : transfert Twilio déclenché après la réponse."""

from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.core.call_session import CallSession
from app.telephony.transfer import transfer_call_to_human
from app.telephony.twilio_media import MediaStreamStart


def _make_session(escalation: str | None):
    with (
        patch("app.core.call_session.DeepgramStream"),
        patch("app.core.call_session.ElevenLabsTTS"),
        patch("app.core.call_session.VoiceAgent") as agent_cls,
        patch("app.core.call_session.AsyncAnthropic"),
    ):
        session = CallSession(
            Settings(human_transfer_number="+33100000000"),
            MediaStreamStart(stream_sid="MZ1", call_sid="CA1", caller_phone=None),
            send_text=AsyncMock(),
        )

        async def run_turn(_):
            yield "Je vous transfère."

        async def synthesize(_):
            yield b"\x00"

        agent_cls.return_value.escalation_requested = escalation
        session._agent.run_turn = run_turn
        session._tts.synthesize = synthesize
        session._stt = AsyncMock()
        return session


@pytest.mark.asyncio
@patch("app.core.call_session.transfer_call_to_human", new_callable=AsyncMock, return_value=True)
async def test_escalation_triggers_transfer_after_response(mock_transfer):
    session = _make_session(escalation="demande d'un humain")
    await session._on_transcript("un humain svp", is_final=True, speech_final=True)
    await session._speaking_task

    mock_transfer.assert_awaited_once()
    assert mock_transfer.await_args.args[1] == "CA1"
    assert session._transferred is True


@pytest.mark.asyncio
@patch("app.core.call_session.transfer_call_to_human", new_callable=AsyncMock)
async def test_no_escalation_no_transfer(mock_transfer):
    session = _make_session(escalation=None)
    await session._on_transcript("bonjour", is_final=True, speech_final=True)
    await session._speaking_task
    mock_transfer.assert_not_awaited()


@pytest.mark.asyncio
async def test_transfer_without_number_configured_returns_false():
    result = await transfer_call_to_human(Settings(human_transfer_number=""), "CA1")
    assert result is False


@pytest.mark.asyncio
async def test_transfer_calls_twilio_rest_api():
    settings = Settings(
        twilio_account_sid="AC_test",
        twilio_auth_token="token",
        human_transfer_number="+33100000000",
    )
    with patch("app.telephony.transfer.Client") as client_cls:
        result = await transfer_call_to_human(settings, "CA42")

    assert result is True
    client_cls.assert_called_once_with("AC_test", "token")
    call_update = client_cls.return_value.calls.return_value.update
    client_cls.return_value.calls.assert_called_once_with("CA42")
    twiml = call_update.call_args.kwargs["twiml"]
    assert "<Dial>+33100000000</Dial>" in twiml

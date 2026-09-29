"""Tests de la session d'appel : pipeline de réponse et barge-in."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.core.call_session import CallSession
from app.telephony.twilio_media import MediaStreamStart
from app.tts.elevenlabs_stream import VOICE_IDS_BY_LANGUAGE
from tests.fakes import FakeTtsStream


def _make_session(sent: list[str], agent_sentences=None, tts_chunks=None):
    """Construit une CallSession avec STT/TTS/agent mockés."""
    with (
        patch("app.core.call_session.DeepgramStream") as stt_cls,
        patch("app.core.call_session.ElevenLabsTTS"),
        patch("app.core.call_session.VoiceAgent") as agent_cls,
        patch("app.core.call_session.AsyncAnthropic"),
    ):
        async def send_text(msg: str):
            sent.append(msg)

        session = CallSession(
            Settings(),
            MediaStreamStart(stream_sid="MZ1", call_sid="CA1", caller_phone=None),
            send_text=send_text,
        )
        stt_cls.assert_called_once()

        async def run_turn(_, confirmed=None):
            for s in agent_sentences or []:
                yield s

        agent_cls.return_value.run_turn = run_turn
        agent_cls.return_value.escalation_requested = None
        agent_cls.return_value.end_call_requested = False
        session._agent.run_turn = run_turn
        session._tts.acquire_stream = AsyncMock(
            side_effect=lambda: FakeTtsStream(tts_chunks or [])
        )
        session._tts.close = AsyncMock()
        session._stt = AsyncMock()
        return session


@pytest.mark.asyncio
async def test_speech_final_triggers_response_audio():
    sent: list[str] = []
    session = _make_session(sent, agent_sentences=["Bonjour !"], tts_chunks=[b"\x01\x02"])

    await session._on_transcript("bonjour", is_final=True, speech_final=True)
    await session._speaking_task

    media = [json.loads(m) for m in sent if json.loads(m)["event"] == "media"]
    assert len(media) == 1
    assert media[0]["streamSid"] == "MZ1"
    assert session.stats.turns == 1
    assert len(session.stats.turn_latencies_ms) == 1
    assert "Appelant : bonjour" in session.transcript_lines
    assert "Agent : Bonjour !" in session.transcript_lines


@pytest.mark.asyncio
async def test_interim_parts_accumulate_until_speech_final():
    sent: list[str] = []
    session = _make_session(sent, agent_sentences=[], tts_chunks=[])

    await session._on_transcript("je voudrais", is_final=True, speech_final=False)
    # Une spéculation silencieuse démarre, mais aucun audio ne part
    assert not session._go.is_set()
    assert session.stats.turns == 0
    await session._on_transcript("un rendez-vous", is_final=True, speech_final=True)
    await session._speaking_task
    assert session.stats.turns == 1


@pytest.mark.asyncio
async def test_barge_in_cancels_response_and_clears_buffer():
    sent: list[str] = []
    # Beaucoup de chunks : la réponse est longue, l'appelant interrompt au milieu
    session = _make_session(
        sent, agent_sentences=["Une longue réponse."], tts_chunks=[b"\x00"] * 1000
    )

    await session._on_transcript("bonjour", is_final=True, speech_final=True)
    await asyncio.sleep(0.01)  # la diffusion démarre
    assert session._is_speaking()

    # L'appelant reparle (transcript intérimaire) → interruption immédiate
    await session._on_transcript("attendez", is_final=False, speech_final=False)
    await asyncio.sleep(0.01)

    # L'audio est coupé (une spéculation silencieuse peut avoir pris la suite)
    assert not session._go.is_set()
    assert session.stats.barge_ins == 1
    events = [json.loads(m)["event"] for m in sent]
    assert "clear" in events
    media_count = events.count("media")
    assert media_count < 1000  # la diffusion a bien été coupée en route
    await session.close()  # nettoie la spéculation en attente


@pytest.mark.asyncio
async def test_close_cancels_ongoing_response():
    sent: list[str] = []
    session = _make_session(sent, agent_sentences=["Réponse."], tts_chunks=[b"\x00"] * 1000)
    await session._on_transcript("bonjour", is_final=True, speech_final=True)
    await asyncio.sleep(0.01)
    await session.close()
    assert not session._is_speaking()
    session._stt.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_greeting_spoken_at_call_start():
    """L'agent amorce la conversation : accueil diffusé dès l'ouverture du stream."""
    sent: list[str] = []
    session = _make_session(sent, tts_chunks=[b"\x01"])
    session._stt.connect = AsyncMock()

    await session.start()
    await session._speaking_task

    events = [json.loads(m)["event"] for m in sent]
    assert "media" in events  # de l'audio est parti sans que l'appelant ait parlé
    greeting_lines = [line for line in session.transcript_lines if line.startswith("Agent :")]
    assert greeting_lines  # l'accueil figure au transcript


@pytest.mark.asyncio
async def test_caller_can_interrupt_greeting():
    """Le message d'accueil est interruptible comme n'importe quelle réponse."""
    sent: list[str] = []
    session = _make_session(sent, tts_chunks=[b"\x00"] * 1000)
    session._stt.connect = AsyncMock()

    await session.start()
    await asyncio.sleep(0.01)  # l'accueil démarre
    assert session._is_speaking()

    await session._on_transcript("bonjour j'appelle pour", is_final=False, speech_final=False)
    # L'accueil est coupé ; une spéculation silencieuse peut avoir démarré
    assert not session._go.is_set()
    assert session.stats.barge_ins == 1
    assert "clear" in [json.loads(m)["event"] for m in sent]
    await session.close()


@pytest.mark.parametrize("language", ["fr", "en"])
def test_tts_uses_voice_matching_call_language(language):
    """La voix ElevenLabs choisie doit correspondre à la langue de l'appel."""
    with (
        patch("app.core.call_session.DeepgramStream"),
        patch("app.core.call_session.ElevenLabsTTS") as tts_cls,
        patch("app.core.call_session.VoiceAgent"),
        patch("app.core.call_session.AsyncAnthropic"),
    ):
        CallSession(
            Settings(),
            MediaStreamStart(stream_sid="MZ1", call_sid="CA1", caller_phone=None, language=language),
            send_text=AsyncMock(),
        )
        tts_cls.assert_called_once()
        assert tts_cls.call_args.kwargs["voice_id"] == VOICE_IDS_BY_LANGUAGE[language]

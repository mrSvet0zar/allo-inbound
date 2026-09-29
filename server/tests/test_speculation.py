"""Tests de l'exécution spéculative : génération anticipée, audio et outils
retenus jusqu'à la confirmation de fin de parole."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from app.core.call_session import CallSession
from app.llm.claude_agent import VoiceAgent
from app.llm.toolbox import AgentToolbox, InMemoryTicketRepo
from app.llm.tools_rdv import InMemoryCalendar, ToolExecutor
from app.support.knowledge_base import InMemoryKnowledgeBase
from app.telephony.twilio_media import MediaStreamStart
from tests.fakes import FakeTtsStream


def _make_session(sent: list[str], agent_sentences=None, tts_chunks=None):
    with (
        patch("app.core.call_session.DeepgramStream"),
        patch("app.core.call_session.ElevenLabsTTS"),
        patch("app.core.call_session.VoiceAgent") as agent_cls,
        patch("app.core.call_session.AsyncAnthropic"),
    ):
        async def send_text(msg):
            sent.append(msg)

        session = CallSession(
            Settings(),
            MediaStreamStart(stream_sid="MZ1", call_sid="CA1", caller_phone=None),
            send_text=send_text,
        )

        received_utterances: list[str] = []

        async def run_turn(utterance, confirmed=None):
            received_utterances.append(utterance)
            for s in agent_sentences or ["Réponse."]:
                yield s

        agent_cls.return_value.run_turn = run_turn
        agent_cls.return_value.escalation_requested = None
        agent_cls.return_value.end_call_requested = False
        session._agent.run_turn = run_turn
        session._agent.received_utterances = received_utterances
        session._tts.acquire_stream = AsyncMock(
            side_effect=lambda: FakeTtsStream(tts_chunks or [b"\x00"])
        )
        session._tts.close = AsyncMock()
        session._stt = AsyncMock()
        return session


@pytest.mark.asyncio
async def test_interim_starts_silent_speculation():
    sent: list[str] = []
    session = _make_session(sent)

    await session._on_transcript("je voudrais un rendez", is_final=False, speech_final=False)
    await asyncio.sleep(0.01)

    assert session._is_speaking()  # génération en cours
    assert not session._go.is_set()  # mais rien ne part
    assert not [m for m in sent if json.loads(m)["event"] == "media"]
    await session.close()


@pytest.mark.asyncio
async def test_matching_speculation_commits_without_regenerating():
    """Si le transcript final correspond à la spéculation (modulo casse et
    ponctuation), l'audio déjà préparé est libéré sans nouvelle génération."""
    sent: list[str] = []
    session = _make_session(sent)

    await session._on_transcript("oui c'est ça", is_final=False, speech_final=False)
    await asyncio.sleep(0.01)
    await session._on_transcript("Oui, c'est ça.", is_final=True, speech_final=True)
    await session._speaking_task

    # Une seule génération : la spéculation a servi telle quelle
    assert session._agent.received_utterances == ["oui c'est ça"]
    assert [m for m in sent if json.loads(m)["event"] == "media"]
    assert session.stats.turns == 1
    assert len(session.stats.turn_latencies_ms) == 1


@pytest.mark.asyncio
async def test_superseded_speculation_is_replaced_and_rolled_back():
    """Si l'appelant continue de parler, la spéculation est remplacée et
    l'historique de l'agent est ramené en arrière."""
    sent: list[str] = []
    session = _make_session(sent)
    rollbacks: list[bool] = []
    session._agent.rollback_turn = lambda: rollbacks.append(True)

    await session._on_transcript("je voudrais", is_final=False, speech_final=False)
    await asyncio.sleep(0.01)
    await session._on_transcript("je voudrais annuler mon rendez-vous", is_final=True, speech_final=True)
    await session._speaking_task

    assert len(rollbacks) >= 1
    assert session._agent.received_utterances[-1] == "je voudrais annuler mon rendez-vous"
    assert session.stats.turns == 1


def _make_agent():
    toolbox = AgentToolbox(
        rdv_executor=ToolExecutor(InMemoryCalendar()),
        knowledge_base=InMemoryKnowledgeBase(),
        ticket_repo=InMemoryTicketRepo(),
    )
    from unittest.mock import MagicMock

    return VoiceAgent(MagicMock(), toolbox)


def test_rollback_turn_removes_speculative_messages():
    agent = _make_agent()
    agent._messages = [{"role": "user", "content": "bonjour"}, {"role": "assistant", "content": "Bonjour !"}]
    agent._turn_start_index = 2
    agent._messages.append({"role": "user", "content": "tour spéculatif"})
    agent._pending_spoken = ["Phrase jamais prononcée."]

    agent.rollback_turn()

    assert len(agent._messages) == 2  # le tour spéculatif a disparu
    assert agent._pending_spoken == []  # rien à réinjecter comme 'interrompu'


def test_rollback_turn_noop_without_active_turn():
    agent = _make_agent()
    agent._messages = [{"role": "user", "content": "bonjour"}]
    agent.rollback_turn()
    assert len(agent._messages) == 1

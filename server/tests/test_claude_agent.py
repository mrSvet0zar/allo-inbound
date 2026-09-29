"""Tests de l'agent vocal : découpage en phrases (unité TTS) et choix de langue."""

from unittest.mock import MagicMock

from app.llm.claude_agent import (
    FILLER_SENTENCES,
    GREETING_SENTENCES,
    SentenceBuffer,
    VoiceAgent,
)
from app.llm.toolbox import AgentToolbox, InMemoryTicketRepo
from app.llm.tools_rdv import InMemoryCalendar, ToolExecutor
from app.support.knowledge_base import InMemoryKnowledgeBase


def test_sentences_emitted_as_completed():
    buf = SentenceBuffer()
    assert buf.feed("Bonjour, je vérifie") == []
    assert buf.feed(" les disponibilités. Un ins") == ["Bonjour, je vérifie les disponibilités."]
    assert buf.feed("tant s'il vous plaît ! D'ac") == ["Un instant s'il vous plaît !"]
    assert buf.flush() == "D'ac"


def test_multiple_sentences_in_one_delta():
    buf = SentenceBuffer()
    assert buf.feed("Oui. Bien sûr. Avec plaisir. Et enc") == [
        "Oui.",
        "Bien sûr.",
        "Avec plaisir.",
    ]


def test_ellipsis_and_final_punctuation():
    buf = SentenceBuffer()
    assert buf.feed("Voyons voir… ") == ["Voyons voir…"]
    assert buf.feed("C'est noté.") == []  # pas encore d'espace ni de flush
    assert buf.flush() == "C'est noté."


def test_decimal_number_not_split():
    buf = SentenceBuffer()
    # Un point sans espace derrière (ex: nombre décimal) ne coupe pas la phrase
    assert buf.feed("Cela coûte 3.50 euros. Merci") == ["Cela coûte 3.50 euros."]
    assert buf.flush() == "Merci"


def test_flush_empty_returns_none():
    buf = SentenceBuffer()
    assert buf.flush() is None
    buf.feed("Fini. ")
    assert buf.feed("") == []
    assert buf.flush() is None


def _make_agent(language="fr"):
    toolbox = AgentToolbox(
        rdv_executor=ToolExecutor(InMemoryCalendar()),
        knowledge_base=InMemoryKnowledgeBase(),
        ticket_repo=InMemoryTicketRepo(),
    )
    return VoiceAgent(MagicMock(), toolbox, language=language)


def test_voice_agent_defaults_to_french():
    agent = _make_agent()
    assert agent._language == "fr"


def test_voice_agent_accepts_english():
    agent = _make_agent(language="en")
    assert agent._language == "en"


def test_voice_agent_unknown_language_falls_back_to_french():
    agent = _make_agent(language="de")
    assert agent._language == "fr"


def test_filler_sentences_defined_for_both_languages():
    assert FILLER_SENTENCES["fr"]
    assert FILLER_SENTENCES["en"]
    # aucune phrase française ne doit se glisser dans la liste anglaise et inversement
    assert not set(FILLER_SENTENCES["fr"]) & set(FILLER_SENTENCES["en"])


def test_interrupted_speech_flushed_into_history():
    """Ce qui a été prononcé avant une interruption est réinjecté dans
    l'historique au tour suivant, avec la note d'interruption."""
    agent = _make_agent()
    agent._pending_spoken = ["Bien sûr.", "Demain j'ai trois créneaux :"]
    agent._flush_interrupted_speech()

    assert len(agent._messages) == 1
    msg = agent._messages[0]
    assert msg["role"] == "assistant"
    assert "Demain j'ai trois créneaux" in msg["content"]
    assert "interrompu" in msg["content"]
    assert agent._pending_spoken == []


def test_flush_noop_when_nothing_was_spoken():
    agent = _make_agent()
    agent._flush_interrupted_speech()
    assert agent._messages == []


def test_interruption_note_in_english_for_english_calls():
    agent = _make_agent(language="en")
    agent._pending_spoken = ["Sure."]
    agent._flush_interrupted_speech()
    assert "interrupted" in agent._messages[0]["content"]


def test_greeting_defined_for_both_languages():
    for language in ("fr", "en"):
        sentences = GREETING_SENTENCES[language]
        assert sentences
        # chaque entrée est une phrase complète, prête pour un appel TTS
        assert all(s.rstrip().endswith(("!", "?", ".")) for s in sentences)

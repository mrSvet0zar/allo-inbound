"""Tests du retrieval lexical de la base de connaissances (matching + pondération IDF)."""

import pytest

from app.support.knowledge_base import InMemoryKnowledgeBase


@pytest.fixture
def kb():
    return InMemoryKnowledgeBase()


async def _top_question(kb, query: str) -> str | None:
    results = await kb.search(query)
    return results[0].question if results else None


async def test_exact_keyword_match(kb):
    assert await _top_question(kb, "quels horaires") == "Quels sont vos horaires d'ouverture ?"


async def test_containment_matches_compound_word(kb):
    """Régression : 'consultations' (requête) doit matcher 'teleconsultations'
    (FAQ) même sans intersection exacte de tokens — 'consultations' est une
    sous-chaîne de 'teleconsultations'."""
    question = await _top_question(
        kb, "est-ce que vous faites des consultations à distance, en visio ?"
    )
    assert question == "Proposez-vous des téléconsultations ?"


async def test_exact_match_on_common_word_beats_containment_on_rare_word(kb):
    """Régression : un mot générique ('consultation') présent dans plusieurs
    entrées doit quand même l'emporter par match exact sur une entrée hors
    sujet appariée seulement par inclusion (ex: 'teleconsultations')."""
    question = await _top_question(kb, "combien coûte une consultation")
    assert question == "Quels sont les tarifs et moyens de paiement acceptés ?"


async def test_accent_insensitive_match(kb):
    question = await _top_question(kb, "faites-vous des teleconsultations")
    assert question == "Proposez-vous des téléconsultations ?"


async def test_no_match_returns_empty(kb):
    assert await kb.search("xyzabc totalement hors sujet") == []


async def test_empty_query_returns_empty(kb):
    assert await kb.search("") == []


async def test_short_tokens_do_not_trigger_containment(kb):
    # "vue" ne doit pas matcher par inclusion un token type "revue"/"avenue"
    # (sous le seuil de longueur minimale pour le containment)
    results = await kb.search("vue")
    for entry in results:
        assert "vue" in entry.question.lower() + entry.answer.lower()


async def test_list_all_returns_full_faq(kb):
    entries = await kb.list_all()
    assert len(entries) == 6


async def test_custom_entries_override_demo_faq():
    kb = InMemoryKnowledgeBase([("Question test ?", "Réponse test.")])
    entries = await kb.list_all()
    assert len(entries) == 1
    assert entries[0].question == "Question test ?"

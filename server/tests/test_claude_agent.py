"""Tests de l'agent vocal : découpage en phrases (unité TTS)."""

from app.llm.claude_agent import SentenceBuffer


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

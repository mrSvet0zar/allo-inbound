"""Tests du parsing d'ingestion de la base de connaissances (sans base)."""

from pathlib import Path

import pytest

from scripts.ingest_kb import parse_csv, parse_file, parse_markdown

KB_EXAMPLE = Path(__file__).parent.parent / "kb" / "cabinet_exemple.md"


def test_parse_markdown_basic():
    entries = parse_markdown(
        "# Titre ignoré\n"
        "préambule ignoré\n"
        "## Question une ?\n"
        "Réponse une.\n"
        "\n"
        "Suite de la réponse une.\n"
        "## Question deux ?\n"
        "Réponse deux.\n"
    )
    assert entries == [
        ("Question une ?", "Réponse une.\n\nSuite de la réponse une."),
        ("Question deux ?", "Réponse deux."),
    ]


def test_parse_markdown_skips_empty_answer():
    entries = parse_markdown("## Question sans réponse ?\n## Vraie question ?\nRéponse.\n")
    assert entries == [("Vraie question ?", "Réponse.")]


def test_parse_csv_basic():
    entries = parse_csv("question,answer\nQ1 ?,R1\nQ2 ?,R2\n")
    assert entries == [("Q1 ?", "R1"), ("Q2 ?", "R2")]


def test_parse_csv_case_insensitive_headers():
    entries = parse_csv("Question,Answer\nQ ?,R\n")
    assert entries == [("Q ?", "R")]


def test_parse_csv_missing_columns_raises():
    with pytest.raises(ValueError, match="question"):
        parse_csv("q,r\nQ ?,R\n")


def test_parse_csv_skips_incomplete_rows():
    entries = parse_csv("question,answer\nQ1 ?,R1\nQ2 ?,\n,R3\n")
    assert entries == [("Q1 ?", "R1")]


def test_parse_file_rejects_unknown_format(tmp_path):
    path = tmp_path / "faq.txt"
    path.write_text("peu importe")
    with pytest.raises(ValueError, match="Format non géré"):
        parse_file(path)


def test_example_kb_file_is_valid_and_rich():
    """Le fichier d'exemple livré doit se parser et couvrir les questions
    observées en appels réels (types de consultations, urgences...)."""
    entries = parse_file(KB_EXAMPLE)
    assert len(entries) >= 12
    questions = " ".join(q for q, _ in entries).lower()
    assert "consultations" in questions  # la question restée sans réponse en test réel
    assert "horaires" in questions
    answers = " ".join(a for _, a in entries)
    # Cohérence avec les créneaux de l'outil RDV (lun-ven 9h-12h / 14h-18h)
    assert "9h à 12h" in answers and "14h à 18h" in answers

"""Tests de la boîte à outils unifiée : support, orientation, résultat d'appel."""

import json

import pytest

from app.llm.toolbox import AgentToolbox, InMemoryTicketRepo
from app.llm.tools_rdv import InMemoryCalendar, ToolExecutor
from app.support.knowledge_base import InMemoryKnowledgeBase


@pytest.fixture
def toolbox():
    return AgentToolbox(
        rdv_executor=ToolExecutor(InMemoryCalendar(), caller_phone="+336"),
        knowledge_base=InMemoryKnowledgeBase(),
        ticket_repo=InMemoryTicketRepo(),
        caller_phone="+336",
    )


async def _call(toolbox, name, args):
    return json.loads(await toolbox.execute(name, args))


async def test_kb_search_finds_horaires(toolbox):
    result = await _call(toolbox, "search_knowledge_base", {"question": "quels horaires ?"})
    assert any("lundi au vendredi" in r["reponse"] for r in result["resultats"])
    assert toolbox.use_case == "support"
    assert toolbox.outcome == "resolved"


async def test_kb_search_accent_insensitive(toolbox):
    result = await _call(
        toolbox, "search_knowledge_base", {"question": "faites-vous des teleconsultations"}
    )
    assert any("téléconsultation" in r["reponse"].lower() for r in result["resultats"])


async def test_kb_no_match_suggests_fallback(toolbox):
    result = await _call(
        toolbox, "search_knowledge_base", {"question": "xyzabc introuvable"}
    )
    assert "Aucune information" in result["resultats"]
    assert toolbox.outcome == "abandoned"  # rien résolu


async def test_create_ticket(toolbox):
    result = await _call(
        toolbox,
        "create_support_ticket",
        {"resume": "Demande de duplicata de facture", "priorite": "low"},
    )
    assert result["ticket_cree"] is True
    assert toolbox.outcome == "resolved"


async def test_rdv_orients_use_case_and_outcome(toolbox):
    await _call(
        toolbox,
        "book_appointment",
        {"date": "2026-09-21", "heure": "10:00", "nom": "Durand", "motif": "consultation"},
    )
    assert toolbox.use_case == "rdv"
    assert toolbox.outcome == "booked"


async def test_escalation_wins_over_other_outcomes(toolbox):
    await _call(
        toolbox,
        "book_appointment",
        {"date": "2026-09-21", "heure": "10:00", "nom": "Durand", "motif": "x"},
    )
    await _call(toolbox, "escalate_to_human", {"raison": "litige"})
    assert toolbox.outcome == "escalated"
    assert toolbox.escalation_requested == "litige"


async def test_first_tool_family_sets_use_case(toolbox):
    await _call(toolbox, "search_knowledge_base", {"question": "tarifs"})
    await _call(
        toolbox, "check_availability", {"date": "2026-09-21"}
    )  # bascule RDV ensuite
    assert toolbox.use_case == "support"  # le premier gagne

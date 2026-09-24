"""Tests du vérificateur d'attentes des scénarios (sans appel API)."""

from pathlib import Path

import yaml

from eval.checks import check_expectations, tools_called

BOOKING_TIMELINE = [
    ("say", "Je vérifie les disponibilités."),
    ("tool", "check_availability"),
    ("say", "Je vous propose neuf heures trente."),
    ("say", "Je confirme : lundi cinq octobre à neuf heures trente, c'est bien ça ?"),
    ("tool", "book_appointment"),
    ("say", "C'est réservé, à lundi !"),
]


def test_all_expectations_pass():
    failures = check_expectations(
        BOOKING_TIMELINE,
        outcome="booked",
        use_case="rdv",
        expect={
            "tools_called": ["check_availability", "book_appointment"],
            "tools_not_called": ["cancel_appointment"],
            "outcome": "booked",
            "use_case": "rdv",
            "agent_says": "neuf heures trente",
            "confirmation_before": "book_appointment",
        },
    )
    assert failures == []


def test_missing_tool_reported():
    failures = check_expectations(
        BOOKING_TIMELINE, outcome="booked", use_case="rdv",
        expect={"tools_called": ["escalate_to_human"]},
    )
    assert len(failures) == 1
    assert "escalate_to_human" in failures[0]


def test_forbidden_tool_reported():
    failures = check_expectations(
        BOOKING_TIMELINE, outcome="booked", use_case="rdv",
        expect={"tools_not_called": ["book_appointment"]},
    )
    assert "outil interdit" in failures[0]


def test_wrong_outcome_and_use_case():
    failures = check_expectations(
        BOOKING_TIMELINE, outcome="abandoned", use_case="support",
        expect={"outcome": "booked", "use_case": "rdv"},
    )
    assert len(failures) == 2


def test_confirmation_missing_before_booking():
    timeline = [
        ("say", "Très bien, je réserve tout de suite."),  # pas une question de confirmation
        ("tool", "book_appointment"),
    ]
    failures = check_expectations(
        timeline, outcome="booked", use_case="rdv",
        expect={"confirmation_before": "book_appointment"},
    )
    assert "confirmation" in failures[0]


def test_confirmation_check_when_tool_never_called():
    failures = check_expectations(
        [("say", "Bonjour !")], outcome="abandoned", use_case=None,
        expect={"confirmation_before": "book_appointment"},
    )
    assert "jamais été appelé" in failures[0]


def test_agent_says_regex():
    failures = check_expectations(
        BOOKING_TIMELINE, outcome="booked", use_case="rdv",
        expect={"agent_says": "mardi|mercredi"},
    )
    assert "n'a jamais dit" in failures[0]


def test_tools_called_helper():
    assert tools_called(BOOKING_TIMELINE) == ["check_availability", "book_appointment"]


def test_scenarios_file_is_valid():
    """Le dataset se charge et respecte le format attendu par le runner."""
    scenarios = yaml.safe_load(
        (Path(__file__).parent.parent / "eval" / "scenarios.yaml").read_text(encoding="utf-8")
    )
    assert len(scenarios) >= 15  # objectif CLAUDE.md : 15-20 scénarios
    names = [s["name"] for s in scenarios]
    assert len(names) == len(set(names)), "noms de scénarios dupliqués"
    known_keys = {"tools_called", "tools_not_called", "outcome", "use_case",
                  "agent_says", "confirmation_before"}
    for scenario in scenarios:
        assert scenario["turns"], f"{scenario['name']} : aucun tour"
        assert scenario.get("expect"), f"{scenario['name']} : aucune attente"
        unknown = set(scenario["expect"]) - known_keys
        assert not unknown, f"{scenario['name']} : clés inconnues {unknown}"
        for appt in scenario.get("setup", {}).get("appointments", []):
            assert set(appt) == {"date", "heure", "nom", "motif"}

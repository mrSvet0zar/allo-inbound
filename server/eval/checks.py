"""Vérification des attentes d'un scénario rejoué.

La timeline d'un scénario est la séquence chronologique des événements :
("say", <phrase de l'agent>) et ("tool", <nom d'outil>), tous tours confondus.
"""

import re
from typing import Any

Timeline = list[tuple[str, str]]

# Marqueurs d'une demande de confirmation orale dans une phrase de l'agent
_CONFIRMATION_RE = re.compile(r"confirm|c'est bien|correct|d'accord\s*\?", re.IGNORECASE)


def tools_called(timeline: Timeline) -> list[str]:
    return [value for kind, value in timeline if kind == "tool"]


def check_expectations(
    timeline: Timeline,
    outcome: str,
    use_case: str | None,
    expect: dict[str, Any],
) -> list[str]:
    """Retourne la liste des échecs (vide = scénario réussi)."""
    failures: list[str] = []
    called = tools_called(timeline)
    agent_text = " ".join(value for kind, value in timeline if kind == "say")

    for tool in expect.get("tools_called", []):
        if tool not in called:
            failures.append(f"outil attendu non appelé : {tool} (appelés : {called or 'aucun'})")

    for tool in expect.get("tools_not_called", []):
        if tool in called:
            failures.append(f"outil interdit appelé : {tool}")

    if (expected_outcome := expect.get("outcome")) and outcome != expected_outcome:
        failures.append(f"outcome attendu {expected_outcome!r}, obtenu {outcome!r}")

    if (expected_use_case := expect.get("use_case")) and use_case != expected_use_case:
        failures.append(f"use_case attendu {expected_use_case!r}, obtenu {use_case!r}")

    pattern = expect.get("agent_says")
    if pattern and not re.search(pattern, agent_text, re.IGNORECASE):
        failures.append(f"l'agent n'a jamais dit /{pattern}/")

    if tool := expect.get("confirmation_before"):
        failures.extend(_check_confirmation_before(timeline, tool))

    return failures


def _check_confirmation_before(timeline: Timeline, tool: str) -> list[str]:
    """Vérifie qu'une demande de confirmation précède le premier appel de `tool`."""
    said_before: list[str] = []
    for kind, value in timeline:
        if kind == "say":
            said_before.append(value)
        elif kind == "tool" and value == tool:
            if any(_CONFIRMATION_RE.search(s) for s in said_before):
                return []
            return [f"aucune demande de confirmation avant {tool}"]
    return [f"confirmation_before : {tool} n'a jamais été appelé"]

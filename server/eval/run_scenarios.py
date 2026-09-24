"""Rejoue les scénarios conversationnels contre le vrai agent (Claude réel).

Le pipeline audio (STT/TTS/barge-in) est court-circuité : les tours de
l'appelant sont injectés en texte, les backends sont en mémoire. Mesure
aussi la latence texte par tour (envoi du tour → première phrase émise),
composante Claude de l'objectif < 1.2s du CLAUDE.md.

Usage :
    .venv/bin/python -m eval.run_scenarios [--only <nom>] [--json <fichier>]

Nécessite ANTHROPIC_API_KEY (ou .env). Coût : ~15 scénarios × 2-3 tours Haiku.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import date, datetime
from datetime import time as dtime
from pathlib import Path
from typing import Any

import yaml
from anthropic import AsyncAnthropic

from app.config import get_settings
from app.llm.claude_agent import VoiceAgent
from app.llm.toolbox import AgentToolbox, InMemoryTicketRepo
from app.llm.tools_rdv import Appointment, InMemoryCalendar, ToolExecutor
from app.support.knowledge_base import InMemoryKnowledgeBase
from eval.checks import Timeline, check_expectations

SCENARIOS_FILE = Path(__file__).parent / "scenarios.yaml"


class RecordingToolbox(AgentToolbox):
    """Toolbox qui enregistre les appels d'outils dans la timeline du scénario."""

    def __init__(self, *args: Any, timeline: Timeline, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._timeline = timeline

    async def execute(self, name: str, args: dict[str, Any]) -> str:
        self._timeline.append(("tool", name))
        return await super().execute(name, args)


def _build_agent(scenario: dict, timeline: Timeline) -> VoiceAgent:
    settings = get_settings()
    calendar = InMemoryCalendar()
    for i, appt in enumerate(scenario.get("setup", {}).get("appointments", []), start=1):
        calendar.appointments.append(
            Appointment(
                id=i,
                scheduled_at=datetime.combine(
                    date.fromisoformat(appt["date"]), dtime.fromisoformat(appt["heure"])
                ),
                nom=appt["nom"],
                motif=appt["motif"],
            )
        )
        calendar._next_id = i + 1

    toolbox = RecordingToolbox(
        rdv_executor=ToolExecutor(calendar, caller_phone="+33600000000"),
        knowledge_base=InMemoryKnowledgeBase(),
        ticket_repo=InMemoryTicketRepo(),
        caller_phone="+33600000000",
        timeline=timeline,
    )
    return VoiceAgent(AsyncAnthropic(api_key=settings.anthropic_api_key), toolbox)


async def run_scenario(scenario: dict) -> dict:
    timeline: Timeline = []
    agent = _build_agent(scenario, timeline)
    turn_latencies_ms: list[int] = []

    for caller_turn in scenario["turns"]:
        started = time.monotonic()
        first_sentence = True
        async for sentence in agent.run_turn(caller_turn):
            if first_sentence:
                turn_latencies_ms.append(int((time.monotonic() - started) * 1000))
                first_sentence = False
            timeline.append(("say", sentence))

    failures = check_expectations(
        timeline,
        outcome=agent.toolbox.outcome,
        use_case=agent.toolbox.use_case,
        expect=scenario.get("expect", {}),
    )
    return {
        "name": scenario["name"],
        "passed": not failures,
        "failures": failures,
        "turn_latencies_ms": turn_latencies_ms,
        "timeline": timeline,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="ne rejouer que ce scénario")
    parser.add_argument("--json", help="exporter les résultats détaillés en JSON")
    args = parser.parse_args()

    scenarios = yaml.safe_load(SCENARIOS_FILE.read_text(encoding="utf-8"))
    if args.only:
        scenarios = [s for s in scenarios if s["name"] == args.only]
        if not scenarios:
            print(f"Scénario inconnu : {args.only}")
            return 2

    results = []
    for scenario in scenarios:
        print(f"▶ {scenario['name']} ... ", end="", flush=True)
        try:
            result = await run_scenario(scenario)
        except Exception as exc:  # noqa: BLE001 — un scénario en erreur ne doit pas stopper la campagne
            result = {
                "name": scenario["name"],
                "passed": False,
                "failures": [f"exception : {exc}"],
                "turn_latencies_ms": [],
                "timeline": [],
            }
        results.append(result)
        if result["passed"]:
            print("OK")
        else:
            print("ÉCHEC")
            for failure in result["failures"]:
                print(f"    - {failure}")

    passed = sum(1 for r in results if r["passed"])
    all_latencies = [ms for r in results for ms in r["turn_latencies_ms"]]
    print(f"\n{'=' * 60}")
    print(f"Résultat : {passed}/{len(results)} scénarios réussis "
          f"({100 * passed / len(results):.0f}% — objectif > 80%)")
    if all_latencies:
        avg = statistics.mean(all_latencies)
        p95 = statistics.quantiles(all_latencies, n=20)[18] if len(all_latencies) > 1 else avg
        print(f"Latence texte par tour (Claude → 1re phrase) : "
              f"moyenne {avg:.0f}ms, P95 {p95:.0f}ms sur {len(all_latencies)} tours")
        print("(la latence totale perçue ajoute STT ~300ms + TTS ~200ms)")

    if args.json:
        Path(args.json).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Détails exportés : {args.json}")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

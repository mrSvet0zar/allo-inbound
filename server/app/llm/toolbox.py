"""Boîte à outils unifiée de l'agent : RDV + support + escalade.

Les deux jeux d'outils partagent le même moteur conversationnel (cf CLAUDE.md) ;
c'est l'intention détectée par l'agent qui détermine quels outils il appelle.
Le toolbox trace le cas d'usage et le résultat de l'appel pour l'observabilité.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.llm.tools_rdv import SLOW_TOOLS, TOOL_DEFINITIONS, ToolExecutor
from app.llm.tools_support import SUPPORT_SLOW_TOOLS, SUPPORT_TOOL_DEFINITIONS
from app.support.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)

ALL_TOOL_DEFINITIONS = TOOL_DEFINITIONS + SUPPORT_TOOL_DEFINITIONS
ALL_SLOW_TOOLS = SLOW_TOOLS | SUPPORT_SLOW_TOOLS

_RDV_TOOLS = {
    "check_availability",
    "book_appointment",
    "modify_appointment",
    "cancel_appointment",
    "find_appointment",
}
_SUPPORT_TOOLS = {"search_knowledge_base", "create_support_ticket"}


class TicketRepo(Protocol):
    async def create(self, resume: str, priorite: str, caller_phone: str | None) -> int: ...
    async def list_open(self) -> list[dict]: ...


@dataclass
class InMemoryTicketRepo:
    """Tickets de démo (dev/tests). Interface partagée avec PostgresTicketRepo."""

    tickets: list[dict] = field(default_factory=list)

    async def create(self, resume: str, priorite: str, caller_phone: str | None) -> int:
        ticket_id = len(self.tickets) + 1
        self.tickets.append(
            {
                "id": ticket_id,
                "resume": resume,
                "priorite": priorite,
                "caller_phone": caller_phone,
                "status": "open",
            }
        )
        return ticket_id

    async def list_open(self) -> list[dict]:
        return [t for t in self.tickets if t["status"] == "open"]


class AgentToolbox:
    """Dispatch des appels d'outils + suivi du cas d'usage et du résultat."""

    def __init__(
        self,
        rdv_executor: ToolExecutor,
        knowledge_base: KnowledgeBase,
        ticket_repo: TicketRepo,
        caller_phone: str | None = None,
    ):
        self._rdv = rdv_executor
        self._kb = knowledge_base
        self._tickets = ticket_repo
        self._caller_phone = caller_phone
        self.use_case: str | None = None  # rdv | support
        self.events: list[str] = []  # booked, modified, cancelled, ticket_created, kb_answered

    @property
    def escalation_requested(self) -> str | None:
        return self._rdv.escalation_requested

    @property
    def outcome(self) -> str:
        """Résultat de l'appel pour call_logs (cf schéma CLAUDE.md)."""
        if self.escalation_requested:
            return "escalated"
        if "booked" in self.events or "modified" in self.events:
            return "booked"
        if "cancelled" in self.events:
            return "cancelled"
        if "ticket_created" in self.events or "kb_answered" in self.events:
            return "resolved"
        return "abandoned"

    async def execute(self, name: str, args: dict[str, Any]) -> str:
        if name in _RDV_TOOLS:
            self.use_case = self.use_case or "rdv"
            result_json = await self._rdv.execute(name, args)
            self._track_rdv_event(result_json)
            return result_json
        if name in _SUPPORT_TOOLS:
            self.use_case = self.use_case or "support"
            return await self._execute_support(name, args)
        if name == "escalate_to_human":
            return await self._rdv.execute(name, args)
        return json.dumps({"error": f"Outil inconnu : {name}"}, ensure_ascii=False)

    def _track_rdv_event(self, result_json: str) -> None:
        result = json.loads(result_json)
        if result.get("confirme"):
            self.events.append("booked")
        elif result.get("modifie"):
            self.events.append("modified")
        elif result.get("annule"):
            self.events.append("cancelled")

    async def _execute_support(self, name: str, args: dict[str, Any]) -> str:
        try:
            if name == "search_knowledge_base":
                entries = await self._kb.search(args["question"], k=3)
                if entries:
                    self.events.append("kb_answered")
                return json.dumps(
                    {
                        "resultats": [
                            {"question": e.question, "reponse": e.answer} for e in entries
                        ]
                        or "Aucune information trouvée — proposer un ticket ou un transfert."
                    },
                    ensure_ascii=False,
                )
            # create_support_ticket
            ticket_id = await self._tickets.create(
                args["resume"], args["priorite"], self._caller_phone
            )
            self.events.append("ticket_created")
            return json.dumps({"ticket_cree": True, "ticket_id": ticket_id}, ensure_ascii=False)
        except (KeyError, ValueError) as exc:
            return json.dumps({"error": f"Arguments invalides : {exc}"}, ensure_ascii=False)

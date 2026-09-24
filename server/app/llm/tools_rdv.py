"""Outils de prise de rendez-vous (Phase 2 : calendrier en mémoire).

La Phase 3 remplacera `InMemoryCalendar` par PostgreSQL (Supabase) derrière
la même interface. Les définitions d'outils sont partagées avec l'agent.
"""

import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

# Créneaux ouverts : lun-ven, 9h-12h et 14h-18h, pas de 30 min
OPENING_SLOTS = [time(h, m) for h in (9, 10, 11) for m in (0, 30)] + [
    time(h, m) for h in (14, 15, 16, 17) for m in (0, 30)
]

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "check_availability",
        "description": (
            "Consulte les créneaux de rendez-vous disponibles pour une date donnée. "
            "À appeler AVANT de proposer un horaire à l'appelant."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date au format YYYY-MM-DD"},
            },
            "required": ["date"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "book_appointment",
        "description": (
            "Crée un rendez-vous. À n'appeler qu'APRÈS confirmation orale explicite "
            "de l'appelant sur la date, l'heure et le motif."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date au format YYYY-MM-DD"},
                "heure": {"type": "string", "description": "Heure au format HH:MM"},
                "nom": {"type": "string", "description": "Nom de l'appelant"},
                "motif": {"type": "string", "description": "Motif du rendez-vous"},
            },
            "required": ["date", "heure", "nom", "motif"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "modify_appointment",
        "description": (
            "Déplace un rendez-vous existant vers une nouvelle date/heure. À n'appeler "
            "qu'après confirmation orale explicite. Vérifier la disponibilité du nouveau "
            "créneau avec check_availability d'abord."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {"type": "integer", "description": "Identifiant du RDV"},
                "date": {"type": "string", "description": "Nouvelle date au format YYYY-MM-DD"},
                "heure": {"type": "string", "description": "Nouvelle heure au format HH:MM"},
            },
            "required": ["appointment_id", "date", "heure"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "cancel_appointment",
        "description": (
            "Annule un rendez-vous existant. À n'appeler qu'après confirmation orale "
            "explicite de l'appelant."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {"type": "integer", "description": "Identifiant du RDV"},
            },
            "required": ["appointment_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "find_appointment",
        "description": "Retrouve les rendez-vous à venir de l'appelant à partir de son nom.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nom": {"type": "string", "description": "Nom de l'appelant"},
            },
            "required": ["nom"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Transfère l'appel à un humain. À appeler dès que l'appelant le demande, "
            "ou pour toute demande sensible (litige, réclamation, remboursement)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "raison": {"type": "string", "description": "Raison du transfert"},
            },
            "required": ["raison"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]

# Outils dont l'exécution peut être lente → l'agent dit une relance avant
SLOW_TOOLS = {"check_availability", "book_appointment", "modify_appointment", "find_appointment"}


@dataclass
class Appointment:
    id: int
    scheduled_at: datetime
    nom: str
    motif: str
    caller_phone: str | None = None
    status: str = "confirmed"


@dataclass
class InMemoryCalendar:
    """Calendrier de démo (dev/tests). Interface async partagée avec PostgresCalendar."""

    appointments: list[Appointment] = field(default_factory=list)
    _next_id: int = 1

    async def available_slots(self, day: date) -> list[time]:
        if day.weekday() >= 5:  # week-end fermé
            return []
        taken = {
            a.scheduled_at.time()
            for a in self.appointments
            if a.status == "confirmed" and a.scheduled_at.date() == day
        }
        return [s for s in OPENING_SLOTS if s not in taken]

    async def book(self, at: datetime, nom: str, motif: str, phone: str | None) -> Appointment:
        appt = Appointment(self._next_id, at, nom, motif, phone)
        self._next_id += 1
        self.appointments.append(appt)
        return appt

    async def modify(self, appointment_id: int, new_at: datetime) -> Appointment | None:
        for a in self.appointments:
            if a.id == appointment_id and a.status == "confirmed":
                a.scheduled_at = new_at
                return a
        return None

    async def cancel(self, appointment_id: int) -> Appointment | None:
        for a in self.appointments:
            if a.id == appointment_id and a.status == "confirmed":
                a.status = "cancelled"
                return a
        return None

    async def find_by_name(self, nom: str) -> list[Appointment]:
        needle = nom.strip().lower()
        return [
            a
            for a in self.appointments
            if a.status == "confirmed" and needle in a.nom.lower()
        ]

    async def list_upcoming(self, from_day: date, to_day: date) -> list[Appointment]:
        """RDV confirmés dans l'intervalle [from_day, to_day] — dashboard admin."""
        return sorted(
            (
                a
                for a in self.appointments
                if a.status == "confirmed" and from_day <= a.scheduled_at.date() <= to_day
            ),
            key=lambda a: a.scheduled_at,
        )


class ToolExecutor:
    """Exécute les appels d'outils de l'agent et renvoie un résultat JSON (texte)."""

    def __init__(self, calendar: InMemoryCalendar, caller_phone: str | None = None):
        self.calendar = calendar
        self.caller_phone = caller_phone
        self.escalation_requested: str | None = None

    async def execute(self, name: str, args: dict[str, Any]) -> str:
        try:
            result = await self._dispatch(name, args)
        except (KeyError, ValueError) as exc:
            result = {"error": f"Arguments invalides : {exc}"}
        return json.dumps(result, ensure_ascii=False)

    async def _dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "check_availability":
            day = date.fromisoformat(args["date"])
            slots = await self.calendar.available_slots(day)
            return {
                "date": day.isoformat(),
                "creneaux_disponibles": [s.strftime("%H:%M") for s in slots],
            }
        if name == "book_appointment":
            at = datetime.combine(
                date.fromisoformat(args["date"]), time.fromisoformat(args["heure"])
            )
            if at.time() not in await self.calendar.available_slots(at.date()):
                return {"error": "Ce créneau n'est pas disponible."}
            appt = await self.calendar.book(at, args["nom"], args["motif"], self.caller_phone)
            return {
                "confirme": True,
                "appointment_id": appt.id,
                "date": at.date().isoformat(),
                "heure": at.time().strftime("%H:%M"),
            }
        if name == "modify_appointment":
            new_at = datetime.combine(
                date.fromisoformat(args["date"]), time.fromisoformat(args["heure"])
            )
            if new_at.time() not in await self.calendar.available_slots(new_at.date()):
                return {"error": "Ce créneau n'est pas disponible."}
            appt = await self.calendar.modify(int(args["appointment_id"]), new_at)
            if appt is None:
                return {"error": "Rendez-vous introuvable ou déjà annulé."}
            return {
                "modifie": True,
                "appointment_id": appt.id,
                "date": new_at.date().isoformat(),
                "heure": new_at.time().strftime("%H:%M"),
            }
        if name == "cancel_appointment":
            appt = await self.calendar.cancel(int(args["appointment_id"]))
            if appt is None:
                return {"error": "Rendez-vous introuvable ou déjà annulé."}
            return {"annule": True, "appointment_id": appt.id}
        if name == "find_appointment":
            appts = await self.calendar.find_by_name(args["nom"])
            return {
                "rendez_vous": [
                    {
                        "appointment_id": a.id,
                        "date": a.scheduled_at.date().isoformat(),
                        "heure": a.scheduled_at.time().strftime("%H:%M"),
                        "motif": a.motif,
                    }
                    for a in appts
                ]
            }
        if name == "escalate_to_human":
            self.escalation_requested = args.get("raison", "demande de l'appelant")
            return {"transfert_en_cours": True}
        return {"error": f"Outil inconnu : {name}"}


def next_open_day(from_day: date) -> date:
    """Prochain jour ouvré (utile pour les tests et les suggestions)."""
    day = from_day
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day

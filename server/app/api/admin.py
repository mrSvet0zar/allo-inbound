"""API admin en lecture seule pour le dashboard (cf CLAUDE.md — Phase 5).

Authentification par clé partagée (`ADMIN_API_KEY`, en-tête `X-Admin-Key`) —
suffisant pour ce portfolio de démonstration à un seul opérateur ; une vraie
mise en production remplacerait ceci par une session utilisateur.
"""

# ruff: noqa: B008 — `Depends(...)` en valeur par défaut est le pattern FastAPI standard

import logging
from datetime import datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException

from app.config import Settings, get_settings
from app.core.call_session import shared_calendar, shared_call_logs, shared_kb, shared_tickets
from app.db.database import Database
from app.observability.alerting import check_alerts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/api", tags=["admin"])
PARIS_TZ = ZoneInfo("Europe/Paris")

# Injecté par main.py au démarrage (None tant que Postgres n'est pas connecté)
_db_holder: dict[str, Database | None] = {"db": None}


def set_db(db: Database | None) -> None:
    _db_holder["db"] = db


def get_db() -> Database | None:
    return _db_holder["db"]


async def require_admin_key(
    x_admin_key: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.admin_api_key:
        # Pas de clé configurée : accès ouvert (dev local uniquement — cf README)
        return
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Clé admin invalide ou absente")


@router.get("/stats", dependencies=[Depends(require_admin_key)])
async def stats(db: Database | None = Depends(get_db)):
    """Métriques agrégées + alertes actives (cf roadmap Observabilité)."""
    repo = db.call_logs if db else shared_call_logs
    tickets_repo = db.tickets if db else shared_tickets
    recent = await repo.list_recent(limit=100)
    alerts = check_alerts(recent)

    latencies = [c.avg_turn_latency_ms for c in recent if c.avg_turn_latency_ms is not None]
    escalated = sum(1 for c in recent if c.escalated_to_human)
    open_tickets = await tickets_repo.list_open()

    return {
        "calls_count": len(recent),
        "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else None,
        "escalation_rate": escalated / len(recent) if recent else None,
        "open_tickets_count": len(open_tickets),
        "alerts": [{"level": a.level, "message": a.message} for a in alerts],
    }


@router.get("/calls", dependencies=[Depends(require_admin_key)])
async def list_calls(limit: int = 50, db: Database | None = Depends(get_db)):
    repo = db.call_logs if db else shared_call_logs
    calls = await repo.list_recent(limit=limit)
    return [
        {
            "twilio_call_sid": c.twilio_call_sid,
            "use_case": c.use_case,
            "duration_seconds": c.duration_seconds,
            "outcome": c.outcome,
            "escalated_to_human": c.escalated_to_human,
            "avg_turn_latency_ms": c.avg_turn_latency_ms,
            "tool_calls_count": c.tool_calls_count,
            "created_at": c.created_at,
        }
        for c in calls
    ]


@router.get("/calls/{call_sid}", dependencies=[Depends(require_admin_key)])
async def get_call(call_sid: str, db: Database | None = Depends(get_db)):
    repo = db.call_logs if db else shared_call_logs
    call = await repo.get(call_sid)
    if call is None:
        raise HTTPException(status_code=404, detail="Appel introuvable")
    return {
        "twilio_call_sid": call.twilio_call_sid,
        "use_case": call.use_case,
        "duration_seconds": call.duration_seconds,
        "outcome": call.outcome,
        "escalated_to_human": call.escalated_to_human,
        "avg_turn_latency_ms": call.avg_turn_latency_ms,
        "tool_calls_count": call.tool_calls_count,
        "created_at": call.created_at,
        "transcript": call.transcript,
    }


@router.get("/appointments", dependencies=[Depends(require_admin_key)])
async def list_appointments(days_ahead: int = 7, db: Database | None = Depends(get_db)):
    """RDV confirmés entre aujourd'hui et `days_ahead` jours."""
    calendar = db.calendar if db else shared_calendar
    today = datetime.now(tz=PARIS_TZ).date()
    appts = await calendar.list_upcoming(today, today + timedelta(days=days_ahead))
    return [
        {
            "id": a.id,
            "scheduled_at": a.scheduled_at.isoformat(),
            "nom": a.nom,
            "motif": a.motif,
            "caller_phone": a.caller_phone,
            "status": a.status,
        }
        for a in appts
    ]


@router.get("/tickets", dependencies=[Depends(require_admin_key)])
async def list_tickets(db: Database | None = Depends(get_db)):
    tickets_repo = db.tickets if db else shared_tickets
    return await tickets_repo.list_open()


@router.get("/knowledge-base", dependencies=[Depends(require_admin_key)])
async def list_knowledge_base(db: Database | None = Depends(get_db)):
    """Liste la FAQ pour affichage/consultation dans le dashboard."""
    kb = db.knowledge_base if db else shared_kb
    entries = await kb.list_all()
    return [{"id": e.id, "question": e.question, "answer": e.answer} for e in entries]

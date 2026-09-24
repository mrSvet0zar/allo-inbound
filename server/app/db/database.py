"""Backends PostgreSQL (asyncpg) : calendrier, tickets, base de connaissances, logs.

Mêmes interfaces que les versions en mémoire (tools_rdv.InMemoryCalendar,
toolbox.InMemoryTicketRepo, knowledge_base.InMemoryKnowledgeBase) — le serveur
bascule sur Postgres quand DATABASE_URL est renseignée, sinon reste en mémoire
(dev sans infra).
"""

import logging
from datetime import date, datetime, time

import asyncpg

from app.llm.tools_rdv import OPENING_SLOTS, Appointment
from app.observability.call_logs import CallLogEntry
from app.support.knowledge_base import DEMO_FAQ, KBEntry

logger = logging.getLogger(__name__)


class Database:
    """Pool de connexions + accès aux repositories."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.calendar = PostgresCalendar(pool)
        self.tickets = PostgresTicketRepo(pool)
        self.knowledge_base = PostgresKnowledgeBase(pool)
        self.call_logs = PostgresCallLogRepo(pool)

    @classmethod
    async def connect(cls, dsn: str) -> "Database":
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10)
        logger.info("PostgreSQL connecté")
        return cls(pool)

    async def close(self) -> None:
        await self.pool.close()

    async def seed_knowledge_base_if_empty(self) -> None:
        """Insère la FAQ de démo au premier démarrage."""
        async with self.pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM knowledge_base")
            if count == 0:
                await conn.executemany(
                    "INSERT INTO knowledge_base (question, answer) VALUES ($1, $2)",
                    DEMO_FAQ,
                )
                logger.info("Base de connaissances initialisée (%d entrées)", len(DEMO_FAQ))


def _row_to_appointment(row: asyncpg.Record) -> Appointment:
    return Appointment(
        id=row["id"],
        scheduled_at=row["scheduled_at"],
        nom=row["caller_name"],
        motif=row["motif"],
        caller_phone=row["caller_phone"],
        status=row["status"],
    )


class PostgresCalendar:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def available_slots(self, day: date) -> list[time]:
        if day.weekday() >= 5:
            return []
        rows = await self._pool.fetch(
            "SELECT scheduled_at FROM appointments "
            "WHERE status = 'confirmed' AND scheduled_at::date = $1",
            day,
        )
        taken = {r["scheduled_at"].time() for r in rows}
        return [s for s in OPENING_SLOTS if s not in taken]

    async def book(self, at: datetime, nom: str, motif: str, phone: str | None) -> Appointment:
        row = await self._pool.fetchrow(
            "INSERT INTO appointments (caller_phone, caller_name, scheduled_at, motif) "
            "VALUES ($1, $2, $3, $4) RETURNING *",
            phone, nom, at, motif,
        )
        return _row_to_appointment(row)

    async def modify(self, appointment_id: int, new_at: datetime) -> Appointment | None:
        row = await self._pool.fetchrow(
            "UPDATE appointments SET scheduled_at = $2 "
            "WHERE id = $1 AND status = 'confirmed' RETURNING *",
            appointment_id, new_at,
        )
        return _row_to_appointment(row) if row else None

    async def cancel(self, appointment_id: int) -> Appointment | None:
        row = await self._pool.fetchrow(
            "UPDATE appointments SET status = 'cancelled' "
            "WHERE id = $1 AND status = 'confirmed' RETURNING *",
            appointment_id,
        )
        return _row_to_appointment(row) if row else None

    async def find_by_name(self, nom: str) -> list[Appointment]:
        rows = await self._pool.fetch(
            "SELECT * FROM appointments WHERE status = 'confirmed' "
            "AND caller_name ILIKE '%' || $1 || '%' AND scheduled_at >= NOW() "
            "ORDER BY scheduled_at",
            nom.strip(),
        )
        return [_row_to_appointment(r) for r in rows]

    async def list_upcoming(self, from_day: date, to_day: date) -> list[Appointment]:
        """RDV confirmés dans l'intervalle [from_day, to_day] — dashboard admin."""
        rows = await self._pool.fetch(
            "SELECT * FROM appointments WHERE status = 'confirmed' "
            "AND scheduled_at::date BETWEEN $1 AND $2 ORDER BY scheduled_at",
            from_day, to_day,
        )
        return [_row_to_appointment(r) for r in rows]


class PostgresTicketRepo:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def create(self, resume: str, priorite: str, caller_phone: str | None) -> int:
        return await self._pool.fetchval(
            "INSERT INTO support_tickets (caller_phone, summary, priority) "
            "VALUES ($1, $2, $3) RETURNING id",
            caller_phone, resume, priorite,
        )

    async def list_open(self) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT * FROM support_tickets WHERE status = 'open' ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]


class PostgresKnowledgeBase:
    """Retrieval full-text français (websearch_to_tsquery + ts_rank)."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def search(self, query: str, k: int = 3) -> list[KBEntry]:
        rows = await self._pool.fetch(
            "SELECT id, question, answer, "
            "ts_rank(tsv, websearch_to_tsquery('french', $1)) AS rank "
            "FROM knowledge_base "
            "WHERE tsv @@ websearch_to_tsquery('french', $1) "
            "ORDER BY rank DESC LIMIT $2",
            query, k,
        )
        return [KBEntry(r["id"], r["question"], r["answer"]) for r in rows]

    async def list_all(self) -> list[KBEntry]:
        rows = await self._pool.fetch("SELECT id, question, answer FROM knowledge_base ORDER BY id")
        return [KBEntry(r["id"], r["question"], r["answer"]) for r in rows]


def _row_to_call_log(row: asyncpg.Record) -> CallLogEntry:
    return CallLogEntry(
        twilio_call_sid=row["twilio_call_sid"],
        use_case=row["use_case"],
        transcript=row["transcript"],
        duration_seconds=row["duration_seconds"],
        outcome=row["outcome"],
        escalated_to_human=row["escalated_to_human"],
        avg_turn_latency_ms=row["avg_turn_latency_ms"],
        tool_calls_count=row["tool_calls_count"],
        created_at=row["created_at"].timestamp(),
    )


class PostgresCallLogRepo:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def save(self, entry: CallLogEntry) -> None:
        await self._pool.execute(
            "INSERT INTO call_logs (twilio_call_sid, use_case, transcript, duration_seconds, "
            "outcome, escalated_to_human, avg_turn_latency_ms, tool_calls_count) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
            "ON CONFLICT (twilio_call_sid) DO NOTHING",
            entry.twilio_call_sid, entry.use_case, entry.transcript, entry.duration_seconds,
            entry.outcome, entry.escalated_to_human, entry.avg_turn_latency_ms,
            entry.tool_calls_count,
        )

    async def list_recent(self, limit: int = 50) -> list[CallLogEntry]:
        rows = await self._pool.fetch(
            "SELECT * FROM call_logs ORDER BY created_at DESC LIMIT $1", limit
        )
        return [_row_to_call_log(r) for r in rows]

    async def get(self, twilio_call_sid: str) -> CallLogEntry | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM call_logs WHERE twilio_call_sid = $1", twilio_call_sid
        )
        return _row_to_call_log(row) if row else None

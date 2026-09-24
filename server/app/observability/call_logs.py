"""Journal des appels : interface partagée entre le backend mémoire et Postgres.

`CallLogRepo` (Protocol) est implémenté par `InMemoryCallLogRepo` (dev sans
base) et par `app.db.database.PostgresCallLogRepo`. Le dashboard admin lit
toujours via cette interface pour ne pas dupliquer la logique de requête.
"""

import time
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class CallLogEntry:
    twilio_call_sid: str
    use_case: str | None
    transcript: str
    duration_seconds: int
    outcome: str
    escalated_to_human: bool
    avg_turn_latency_ms: int | None
    tool_calls_count: int
    created_at: float = field(default_factory=time.time)


class CallLogRepo(Protocol):
    async def save(self, entry: CallLogEntry) -> None: ...
    async def list_recent(self, limit: int = 50) -> list[CallLogEntry]: ...
    async def get(self, twilio_call_sid: str) -> CallLogEntry | None: ...


@dataclass
class InMemoryCallLogRepo:
    """Journal en mémoire (dev sans base) — dernier appel gagne sur un même SID."""

    _entries: dict[str, CallLogEntry] = field(default_factory=dict)

    async def save(self, entry: CallLogEntry) -> None:
        self._entries[entry.twilio_call_sid] = entry

    async def list_recent(self, limit: int = 50) -> list[CallLogEntry]:
        ordered = sorted(self._entries.values(), key=lambda e: e.created_at, reverse=True)
        return ordered[:limit]

    async def get(self, twilio_call_sid: str) -> CallLogEntry | None:
        return self._entries.get(twilio_call_sid)

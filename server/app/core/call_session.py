"""Session d'appel : orchestre le pipeline pour un appel entrant.

Phase 1 : Twilio → Deepgram → log du transcript (mode "écho texte").
Phase 2 branchera ici Claude (tool_use) et le TTS streaming, ainsi que
le barge-in (interruption de la réponse en cours).
"""

import logging
import time
from dataclasses import dataclass, field

from app.config import Settings
from app.stt.deepgram_stream import DeepgramConfig, DeepgramStream
from app.telephony.twilio_media import MediaStreamStart

logger = logging.getLogger(__name__)


@dataclass
class CallStats:
    """Métriques collectées pendant l'appel (observabilité, cf CLAUDE.md)."""

    started_at: float = field(default_factory=time.monotonic)
    turns: int = 0
    turn_latencies_ms: list[int] = field(default_factory=list)

    @property
    def duration_seconds(self) -> int:
        return int(time.monotonic() - self.started_at)


class CallSession:
    """Cycle de vie d'un appel : créé au `start` du Media Stream, fermé au `stop`."""

    def __init__(self, settings: Settings, stream_info: MediaStreamStart):
        self.settings = settings
        self.stream_info = stream_info
        self.stats = CallStats()
        self.transcript_lines: list[str] = []
        self._stt = DeepgramStream(
            DeepgramConfig(
                api_key=settings.deepgram_api_key,
                model=settings.deepgram_model,
                language=settings.deepgram_language,
            ),
            on_transcript=self._on_transcript,
        )

    async def start(self) -> None:
        await self._stt.connect()
        logger.info(
            "Appel démarré call_sid=%s stream_sid=%s",
            self.stream_info.call_sid,
            self.stream_info.stream_sid,
        )

    async def on_audio_chunk(self, mulaw_chunk: bytes) -> None:
        """Chunk audio entrant (appelant) relayé vers le STT."""
        await self._stt.send_audio(mulaw_chunk)

    async def _on_transcript(self, text: str, is_final: bool, speech_final: bool) -> None:
        if not is_final:
            return
        self.transcript_lines.append(text)
        logger.info("[%s] Transcript: %s", self.stream_info.call_sid, text)
        if speech_final:
            # Fin de tour de parole détectée (endpointing).
            # Phase 2 : déclencher ici la réponse Claude + TTS.
            self.stats.turns += 1
            logger.info(
                "[%s] Fin de tour #%d — tour complet: %s",
                self.stream_info.call_sid,
                self.stats.turns,
                " ".join(self.transcript_lines[-3:]),
            )

    async def close(self) -> None:
        await self._stt.close()
        logger.info(
            "Appel terminé call_sid=%s durée=%ds tours=%d",
            self.stream_info.call_sid,
            self.stats.duration_seconds,
            self.stats.turns,
        )

"""Session d'appel : orchestre le pipeline complet pour un appel entrant.

Twilio → Deepgram (STT) → Claude (tool_use) → ElevenLabs (TTS) → Twilio.

Barge-in : si l'appelant reparle pendant que l'agent diffuse une réponse,
la tâche de réponse est annulée et un message `clear` vide le buffer audio
côté Twilio — l'agent se tait immédiatement et repasse en écoute.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from anthropic import AsyncAnthropic

from app.config import Settings
from app.db.database import Database
from app.llm.claude_agent import GREETING_SENTENCES, VoiceAgent
from app.llm.toolbox import AgentToolbox, InMemoryTicketRepo
from app.llm.tools_rdv import InMemoryCalendar, ToolExecutor
from app.observability.call_logs import CallLogEntry, CallLogRepo, InMemoryCallLogRepo
from app.stt.deepgram_stream import DeepgramConfig, DeepgramStream
from app.support.knowledge_base import InMemoryKnowledgeBase
from app.telephony.audio_pacer import AudioPacer
from app.telephony.transfer import hang_up_call, transfer_call_to_human
from app.telephony.twilio_media import (
    MediaStreamStart,
    build_clear_message,
    build_media_message,
)
from app.tts.elevenlabs_stream import ElevenLabsTTS, voice_id_for_language

logger = logging.getLogger(__name__)

# Callback d'envoi d'un message texte sur le WebSocket Twilio
SendText = Callable[[str], Awaitable[None]]

# Backends en mémoire partagés entre les appels quand il n'y a pas de base
shared_calendar = InMemoryCalendar()
shared_tickets = InMemoryTicketRepo()
shared_kb = InMemoryKnowledgeBase()
shared_call_logs = InMemoryCallLogRepo()


@dataclass
class CallStats:
    """Métriques collectées pendant l'appel (observabilité, cf CLAUDE.md)."""

    started_at: float = field(default_factory=time.monotonic)
    turns: int = 0
    turn_latencies_ms: list[int] = field(default_factory=list)
    barge_ins: int = 0

    @property
    def duration_seconds(self) -> int:
        return int(time.monotonic() - self.started_at)

    @property
    def avg_turn_latency_ms(self) -> int | None:
        if not self.turn_latencies_ms:
            return None
        return sum(self.turn_latencies_ms) // len(self.turn_latencies_ms)


class CallSession:
    """Cycle de vie d'un appel : créé au `start` du Media Stream, fermé au `stop`."""

    def __init__(
        self,
        settings: Settings,
        stream_info: MediaStreamStart,
        send_text: SendText,
        db: Database | None = None,
    ):
        self.settings = settings
        self.stream_info = stream_info
        self._send_text = send_text
        self._db = db
        self.stats = CallStats()
        self.transcript_lines: list[str] = []
        self._utterance_parts: list[str] = []
        self._speaking_task: asyncio.Task | None = None
        self._transferred = False

        self._stt = DeepgramStream(
            DeepgramConfig(
                api_key=settings.deepgram_api_key,
                model=settings.deepgram_model,
                language=stream_info.language,
            ),
            on_transcript=self._on_transcript,
        )
        self._tts = ElevenLabsTTS(
            settings.elevenlabs_api_key, voice_id=voice_id_for_language(stream_info.language)
        )
        calendar = db.calendar if db else shared_calendar
        toolbox = AgentToolbox(
            rdv_executor=ToolExecutor(calendar, caller_phone=stream_info.caller_phone),
            knowledge_base=db.knowledge_base if db else shared_kb,
            ticket_repo=db.tickets if db else shared_tickets,
            caller_phone=stream_info.caller_phone,
        )
        self._agent = VoiceAgent(
            AsyncAnthropic(api_key=settings.anthropic_api_key), toolbox, language=stream_info.language
        )

    async def start(self) -> None:
        await self._stt.connect()
        logger.info(
            "Appel démarré call_sid=%s stream_sid=%s",
            self.stream_info.call_sid,
            self.stream_info.stream_sid,
        )
        # C'est l'agent qui amorce la conversation : accueil dans sa vraie voix
        # dès l'ouverture du stream, interruptible comme n'importe quelle
        # réponse (même mécanisme _speaking_task → barge-in fonctionnel).
        self._speaking_task = asyncio.create_task(self._speak_greeting())

    async def _speak_greeting(self) -> None:
        """Prononce le message d'accueil (l'appelant n'a encore rien dit)."""
        self._tts.reset_context()
        pacer = AudioPacer()
        try:
            for sentence in GREETING_SENTENCES[self.stream_info.language]:
                self.transcript_lines.append(f"Agent : {sentence}")
                async for audio_chunk in self._tts.synthesize(sentence):
                    await pacer.pace(audio_chunk)
                    await self._send_text(
                        build_media_message(self.stream_info.stream_sid, audio_chunk)
                    )
        except asyncio.CancelledError:
            raise  # l'appelant a parlé pendant l'accueil : on l'écoute
        except Exception:
            logger.exception("[%s] Erreur pendant l'accueil", self.stream_info.call_sid)

    async def on_audio_chunk(self, mulaw_chunk: bytes) -> None:
        """Chunk audio entrant (appelant) relayé vers le STT."""
        await self._stt.send_audio(mulaw_chunk)

    async def _on_transcript(self, text: str, is_final: bool, speech_final: bool) -> None:
        # Barge-in : l'appelant parle pendant que l'agent diffuse une réponse
        if self._is_speaking():
            await self._interrupt_agent()

        if not is_final:
            return

        self._utterance_parts.append(text)
        self.transcript_lines.append(f"Appelant : {text}")

        if speech_final:
            utterance = " ".join(self._utterance_parts)
            self._utterance_parts = []
            self.stats.turns += 1
            logger.info("[%s] Tour #%d : %s", self.stream_info.call_sid, self.stats.turns, utterance)
            self._speaking_task = asyncio.create_task(self._respond(utterance))

    def _is_speaking(self) -> bool:
        return self._speaking_task is not None and not self._speaking_task.done()

    async def _cancel_speaking(self) -> None:
        assert self._speaking_task is not None
        self._speaking_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._speaking_task

    async def _interrupt_agent(self) -> None:
        await self._cancel_speaking()
        self.stats.barge_ins += 1
        # Vide le buffer audio en cours de lecture côté Twilio
        await self._send_text(build_clear_message(self.stream_info.stream_sid))
        logger.info("[%s] Barge-in : réponse interrompue", self.stream_info.call_sid)

    async def _respond(self, utterance: str) -> None:
        """Génère la réponse (Claude → TTS) et la diffuse phrase par phrase."""
        self._tts.reset_context()
        turn_started = time.monotonic()
        first_audio_sent = False
        pacer = AudioPacer()
        try:
            async for sentence in self._agent.run_turn(utterance):
                self.transcript_lines.append(f"Agent : {sentence}")
                async for audio_chunk in self._tts.synthesize(sentence):
                    if not first_audio_sent:
                        latency_ms = int((time.monotonic() - turn_started) * 1000)
                        self.stats.turn_latencies_ms.append(latency_ms)
                        logger.info(
                            "[%s] Première syllabe en %dms",
                            self.stream_info.call_sid,
                            latency_ms,
                        )
                        first_audio_sent = True
                    # Cadence au débit de lecture réel : garde la tâche vivante
                    # pendant toute la durée de la parole pour que le barge-in
                    # (annulation + clear Twilio) soit réellement efficace.
                    await pacer.pace(audio_chunk)
                    await self._send_text(
                        build_media_message(self.stream_info.stream_sid, audio_chunk)
                    )
            # L'agent a demandé une escalade : transfert réel une fois sa
            # phrase d'annonce diffusée
            if self._agent.escalation_requested and not self._transferred:
                self._transferred = await transfer_call_to_human(
                    self.settings, self.stream_info.call_sid
                )
            # L'agent a dit au revoir et demandé la fin d'appel : on laisse
            # Twilio finir de jouer le dernier chunk (le pacer nous amène déjà
            # quasiment à la fin de l'audio), puis on raccroche proprement.
            elif self._agent.end_call_requested:
                await asyncio.sleep(1.0)
                await hang_up_call(self.settings, self.stream_info.call_sid)
        except asyncio.CancelledError:
            raise  # barge-in : rien à faire, le buffer Twilio est déjà vidé
        except Exception:
            logger.exception("[%s] Erreur pendant la réponse", self.stream_info.call_sid)

    async def close(self) -> None:
        if self._is_speaking():
            await self._cancel_speaking()
        await self._stt.close()
        await self._tts.close()
        await self._save_call_log()
        logger.info(
            "Appel terminé call_sid=%s durée=%ds tours=%d barge_ins=%d latence_moy=%sms outils=%d",
            self.stream_info.call_sid,
            self.stats.duration_seconds,
            self.stats.turns,
            self.stats.barge_ins,
            self.stats.avg_turn_latency_ms,
            self._agent.tool_calls_count,
        )

    async def _save_call_log(self) -> None:
        repo: CallLogRepo = self._db.call_logs if self._db else shared_call_logs
        toolbox = self._agent.toolbox
        try:
            await repo.save(
                CallLogEntry(
                    twilio_call_sid=self.stream_info.call_sid,
                    use_case=toolbox.use_case,
                    transcript="\n".join(self.transcript_lines),
                    duration_seconds=self.stats.duration_seconds,
                    outcome=toolbox.outcome,
                    escalated_to_human=self._transferred,
                    avg_turn_latency_ms=self.stats.avg_turn_latency_ms,
                    tool_calls_count=self._agent.tool_calls_count,
                )
            )
        except Exception:
            logger.exception("Échec de l'enregistrement du call log")

"""Session d'appel : orchestre le pipeline complet pour un appel entrant.

Twilio → Deepgram (STT) → Claude (tool_use) → ElevenLabs (TTS) → Twilio.

Barge-in : si l'appelant reparle pendant que l'agent diffuse une réponse,
la tâche de réponse est annulée et un message `clear` vide le buffer audio
côté Twilio — l'agent se tait immédiatement et repasse en écoute.
"""

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
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
        # Exécution spéculative : la génération démarre sur les transcripts
        # provisoires, mais l'audio (et les outils) ne partent qu'une fois la
        # fin de parole confirmée (_go levé). _speculative_text mémorise le
        # texte sur lequel porte la spéculation en cours.
        self._go = asyncio.Event()
        self._commit_time: float | None = None
        self._speculative_text: str | None = None

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
        self._go.set()  # l'accueil est de l'audio réel, pas une spéculation
        self._speaking_task = asyncio.create_task(self._speak_greeting())

    async def _speak_greeting(self) -> None:
        """Prononce le message d'accueil (l'appelant n'a encore rien dit)."""
        pacer = AudioPacer()
        sentences = GREETING_SENTENCES[self.stream_info.language]
        for sentence in sentences:
            self.transcript_lines.append(f"Agent : {sentence}")
        try:
            stream = None
            with contextlib.suppress(Exception):
                stream = await self._tts.acquire_stream()
            if stream is None:
                # Repli HTTP par phrase
                self._tts.reset_context()
                for sentence in sentences:
                    async for audio_chunk in self._tts.synthesize(sentence):
                        await pacer.pace(audio_chunk)
                        await self._send_text(
                            build_media_message(self.stream_info.stream_sid, audio_chunk)
                        )
                return
            try:
                for sentence in sentences:
                    await stream.send_sentence(sentence)
                await stream.end()
                async for audio_chunk in stream.audio_chunks():
                    await pacer.pace(audio_chunk)
                    await self._send_text(
                        build_media_message(self.stream_info.stream_sid, audio_chunk)
                    )
            finally:
                await stream.close()
        except asyncio.CancelledError:
            raise  # l'appelant a parlé pendant l'accueil : on l'écoute
        except Exception:
            logger.exception("[%s] Erreur pendant l'accueil", self.stream_info.call_sid)

    async def on_audio_chunk(self, mulaw_chunk: bytes) -> None:
        """Chunk audio entrant (appelant) relayé vers le STT."""
        await self._stt.send_audio(mulaw_chunk)

    @staticmethod
    def _normalize(text: str) -> str:
        """Compare les textes en ignorant casse, ponctuation et espaces —
        le transcript provisoire et le final diffèrent souvent sur ces points."""
        return re.sub(r"[^a-z0-9àâäéèêëîïôöùûüç]+", "", text.lower())

    async def _on_transcript(self, text: str, is_final: bool, speech_final: bool) -> None:
        # Barge-in : l'appelant parle pendant que de l'audio est réellement
        # diffusé (_go levé) — une spéculation en cours (silencieuse) n'a pas
        # besoin de clear, elle est simplement remplacée plus bas.
        if self._is_speaking() and self._go.is_set():
            await self._interrupt_agent()

        if not is_final:
            # L'appelant parle encore : on spécule sur le transcript provisoire
            candidate = " ".join([*self._utterance_parts, text]).strip()
            await self._maybe_speculate(candidate)
            return

        self._utterance_parts.append(text)
        self.transcript_lines.append(f"Appelant : {text}")

        if speech_final:
            utterance = " ".join(self._utterance_parts)
            self._utterance_parts = []
            self.stats.turns += 1
            logger.info("[%s] Tour #%d : %s", self.stream_info.call_sid, self.stats.turns, utterance)
            await self._commit_turn(utterance)
        else:
            # Segment finalisé mais l'appelant n'a pas fini son tour
            await self._maybe_speculate(" ".join(self._utterance_parts))

    async def _maybe_speculate(self, candidate: str) -> None:
        """(Re)lance une génération spéculative si le texte candidat a changé."""
        if not candidate:
            return
        if self._speculative_text is not None and self._normalize(candidate) == self._normalize(
            self._speculative_text
        ):
            return  # spéculation déjà en cours sur ce texte
        await self._cancel_speculation()
        self._speculative_text = candidate
        self._go = asyncio.Event()
        self._speaking_task = asyncio.create_task(self._respond(candidate, self._go))

    async def _commit_turn(self, utterance: str) -> None:
        """Fin de parole confirmée : libère la spéculation si elle correspond,
        sinon repart d'une génération fraîche."""
        if (
            self._speculative_text is not None
            and self._is_speaking()
            and self._normalize(utterance) == self._normalize(self._speculative_text)
        ):
            self._speculative_text = None
            self._commit_time = time.monotonic()
            self._go.set()
            return
        await self._cancel_speculation()
        self._go = asyncio.Event()
        self._go.set()
        self._commit_time = time.monotonic()
        self._speaking_task = asyncio.create_task(self._respond(utterance, self._go))

    async def _cancel_speculation(self) -> None:
        """Abandonne la spéculation en cours : tâche annulée + historique
        de l'agent ramené à l'état d'avant le tour spéculatif."""
        if self._speculative_text is None:
            return
        self._speculative_text = None
        if self._is_speaking() and not self._go.is_set():
            await self._cancel_speaking()
        self._agent.rollback_turn()

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

    async def _send_paced(self, audio_chunk: bytes, pacer: AudioPacer, go: asyncio.Event) -> None:
        """Attend la confirmation du tour (spéculation), cadence, puis envoie.

        La mesure de latence (fin de parole confirmée → premier octet envoyé)
        est faite par l'appelant de cette méthode.
        """
        if not go.is_set():
            await go.wait()
        # Cadence au débit de lecture réel : garde la tâche vivante pendant
        # toute la durée de la parole pour que le barge-in (annulation +
        # clear Twilio) soit réellement efficace.
        await pacer.pace(audio_chunk)
        await self._send_text(build_media_message(self.stream_info.stream_sid, audio_chunk))

    def _record_turn_latency(self) -> None:
        if self._commit_time is None:
            return
        latency_ms = int((time.monotonic() - self._commit_time) * 1000)
        self.stats.turn_latencies_ms.append(latency_ms)
        logger.info("[%s] Première syllabe en %dms", self.stream_info.call_sid, latency_ms)

    async def _respond(self, utterance: str, go: asyncio.Event) -> None:
        """Génère la réponse (Claude → TTS WebSocket) et la diffuse.

        La génération démarre immédiatement (y compris en spéculation), mais
        aucun octet n'est envoyé — et aucun outil n'est exécuté, cf run_turn —
        tant que `go` n'est pas levé.
        """
        try:
            agen = self._agent.run_turn(utterance, confirmed=go)
            # La première phrase concentre la latence Claude : on l'attend
            # avant d'ouvrir la session TTS, pour que les spéculations
            # abandonnées tôt ne coûtent qu'une requête Claude annulée.
            first_sentence = await anext(agen, None)
            if first_sentence is None:
                return

            stream = None
            with contextlib.suppress(Exception):
                stream = await self._tts.acquire_stream()

            pacer = AudioPacer()
            first_audio_sent = False
            if stream is None:
                # Repli HTTP par phrase (session WebSocket indisponible)
                logger.warning("[%s] TTS WebSocket indisponible, repli HTTP", self.stream_info.call_sid)
                self._tts.reset_context()

                async def _sentences() -> AsyncIterator[str]:
                    yield first_sentence
                    async for s in agen:
                        yield s

                async for sentence in _sentences():
                    self.transcript_lines.append(f"Agent : {sentence}")
                    async for audio_chunk in self._tts.synthesize(sentence):
                        if not first_audio_sent:
                            first_audio_sent = True
                            if not go.is_set():
                                await go.wait()
                            self._record_turn_latency()
                        await self._send_paced(audio_chunk, pacer, go)
            else:

                async def _feed() -> None:
                    try:
                        self.transcript_lines.append(f"Agent : {first_sentence}")
                        await stream.send_sentence(first_sentence)
                        async for sentence in agen:
                            self.transcript_lines.append(f"Agent : {sentence}")
                            await stream.send_sentence(sentence)
                    finally:
                        await stream.end()

                feeder = asyncio.create_task(_feed())
                try:
                    async for audio_chunk in stream.audio_chunks():
                        if not first_audio_sent:
                            first_audio_sent = True
                            if not go.is_set():
                                await go.wait()
                            self._record_turn_latency()
                        await self._send_paced(audio_chunk, pacer, go)
                    await feeder  # propage une éventuelle erreur Claude
                finally:
                    if not feeder.done():
                        feeder.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await feeder
                    await stream.close()

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
            raise  # barge-in ou spéculation remplacée
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

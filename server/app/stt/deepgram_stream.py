"""Client Deepgram streaming (STT temps réel).

Ouvre une connexion WebSocket vers Deepgram, y pousse les chunks audio μ-law
8kHz reçus de Twilio, et émet les transcripts via un callback. L'endpointing
Deepgram (`speech_final`) sert de signal "l'appelant a fini de parler".
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlencode

import websockets

logger = logging.getLogger(__name__)

DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"

# Callback appelé à chaque transcript : (texte, is_final, speech_final)
TranscriptCallback = Callable[[str, bool, bool], Awaitable[None]]


@dataclass
class DeepgramConfig:
    api_key: str
    model: str = "nova-3"
    language: str = "fr"
    # Silence (ms) après lequel Deepgram considère le tour de parole terminé
    endpointing_ms: int = 300


class DeepgramStream:
    """Connexion streaming vers Deepgram pour un appel.

    Usage :
        stream = DeepgramStream(config, on_transcript)
        await stream.connect()
        await stream.send_audio(chunk)  # pour chaque chunk Twilio
        await stream.close()
    """

    def __init__(self, config: DeepgramConfig, on_transcript: TranscriptCallback):
        self._config = config
        self._on_transcript = on_transcript
        self._ws: websockets.ClientConnection | None = None
        self._receive_task: asyncio.Task | None = None

    async def connect(self) -> None:
        params = urlencode(
            {
                "model": self._config.model,
                "language": self._config.language,
                "encoding": "mulaw",
                "sample_rate": 8000,
                "channels": 1,
                "punctuate": "true",
                "interim_results": "true",
                "endpointing": self._config.endpointing_ms,
                "vad_events": "true",
            }
        )
        self._ws = await websockets.connect(
            f"{DEEPGRAM_WS_URL}?{params}",
            additional_headers={"Authorization": f"Token {self._config.api_key}"},
        )
        self._receive_task = asyncio.create_task(self._receive_loop())
        logger.info("Deepgram connecté (model=%s, lang=%s)", self._config.model, self._config.language)

    async def send_audio(self, mulaw_chunk: bytes) -> None:
        if self._ws is not None:
            await self._ws.send(mulaw_chunk)

    async def close(self) -> None:
        if self._ws is not None:
            try:
                # Signale la fin du flux pour récupérer le dernier transcript
                await self._ws.send(json.dumps({"type": "CloseStream"}))
                await self._ws.close()
            except websockets.WebSocketException:
                pass
        if self._receive_task is not None:
            self._receive_task.cancel()

    async def _receive_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if msg.get("type") != "Results":
                    continue
                alt = msg["channel"]["alternatives"][0]
                text = alt.get("transcript", "").strip()
                if not text:
                    continue
                is_final = msg.get("is_final", False)
                speech_final = msg.get("speech_final", False)
                await self._on_transcript(text, is_final, speech_final)
        except websockets.ConnectionClosed:
            logger.info("Connexion Deepgram fermée")
        except asyncio.CancelledError:
            pass

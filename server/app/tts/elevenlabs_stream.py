"""TTS ElevenLabs en streaming, sortie μ-law 8kHz directement compatible Twilio.

Chemin principal : WebSocket stream-input — une connexion par réponse, les
phrases y sont poussées au fil de l'eau et l'audio ressort en continu, avec
une prosodie naturellement continue (même contexte de génération) et un
premier octet ~100-250ms plus rapide que l'appel HTTP par phrase (mesuré).
La connexion suivante est pré-ouverte en arrière-plan pour masquer le
handshake (~170ms).

Chemin de secours : l'appel HTTP par phrase (synthesize), utilisé si
l'ouverture du WebSocket échoue.
"""

import asyncio
import base64
import contextlib
import json
import logging
from collections.abc import AsyncIterator

import httpx
import websockets

logger = logging.getLogger(__name__)

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
ELEVENLABS_WS_URL = (
    "wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
    "?model_id={model_id}&output_format=ulaw_8000&auto_mode=true&inactivity_timeout=60"
)

# Une voix par langue, choisie pour son naturel dans cette langue plutôt que
# de réutiliser une même voix multilingue — cf app.telephony.twilio_media
# pour la liste des langues supportées et le choix par l'appelant (menu DTMF).
VOICE_IDS_BY_LANGUAGE = {
    "fr": "YxrwjAKoUKULGd0g8K9Y",  # voix française native, choisie pour le projet
    "en": "7EzWGsX10sAS4c9m9cPf",  # voix anglophone native, choisie pour le projet
}
DEFAULT_VOICE_ID = VOICE_IDS_BY_LANGUAGE["fr"]
# Flash v2.5 : seul modèle basse latence supporté par le WebSocket
# stream-input (eleven_v4_turbo y est refusé — 'unsupported_model', vérifié).
# La continuité de prosodie du WS (une connexion = un contexte de génération)
# compense la moindre expressivité par phrase du modèle.
MODEL_ID = "eleven_flash_v2_5"
# stability modérée + style > 0 : un peu d'expressivité sans tomber dans les
# variations d'intonation erratiques qu'une stability trop basse peut produire
VOICE_SETTINGS = {
    "stability": 0.5,
    "similarity_boost": 0.8,
    "style": 0.15,
    "use_speaker_boost": True,
}

# Nombre de request_id précédents à chaîner pour la continuité de prosodie
# entre phrases consécutives d'une même réponse (max supporté par l'API : 3)
_CONTEXT_CHAIN_LENGTH = 3


def voice_id_for_language(language: str) -> str:
    """Voix à utiliser pour une langue donnée (repli sur le français)."""
    return VOICE_IDS_BY_LANGUAGE.get(language, DEFAULT_VOICE_ID)


class TtsStreamSession:
    """Une réponse vocale = une session : texte poussé phrase par phrase,
    audio μ-law lu en continu. auto_mode=true déclenche la génération dès
    qu'une phrase complète arrive, sans flush explicite."""

    def __init__(self, ws: websockets.ClientConnection):
        self._ws = ws

    async def send_sentence(self, text: str) -> None:
        # L'API exige que chaque envoi se termine par un espace
        await self._ws.send(json.dumps({"text": text.rstrip() + " "}))

    async def end(self) -> None:
        """Signale la fin du texte : le serveur termine puis envoie isFinal."""
        with contextlib.suppress(websockets.WebSocketException):
            await self._ws.send(json.dumps({"text": ""}))

    async def audio_chunks(self) -> AsyncIterator[bytes]:
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if msg.get("audio"):
                    yield base64.b64decode(msg["audio"])
                if msg.get("isFinal"):
                    return
        except websockets.ConnectionClosed:
            logger.warning("Connexion TTS fermée par le serveur en cours de session")

    async def close(self) -> None:
        with contextlib.suppress(websockets.WebSocketException):
            await self._ws.close()


class ElevenLabsTTS:
    """Client TTS réutilisé pour toutes les phrases d'un appel (connexion keep-alive)."""

    def __init__(self, api_key: str, voice_id: str = DEFAULT_VOICE_ID):
        self._api_key = api_key
        self._voice_id = voice_id
        self._client = httpx.AsyncClient(
            headers={"xi-api-key": api_key},
            timeout=httpx.Timeout(10.0, read=30.0),
        )
        # request_id des phrases précédentes de la réponse en cours, chaînés
        # pour que la prosodie reste continue d'une phrase à l'autre au lieu
        # que chaque appel TTS séparé sonne comme un clip isolé recollé.
        # (Utile uniquement sur le chemin de secours HTTP — le WebSocket
        # garde nativement le contexte au sein d'une session.)
        self._recent_request_ids: list[str] = []
        # Session WebSocket pré-ouverte pour masquer le handshake (~170ms)
        self._preopened: TtsStreamSession | None = None
        self._preopen_task: asyncio.Task | None = None

    async def _connect(self) -> TtsStreamSession:
        url = ELEVENLABS_WS_URL.format(voice_id=self._voice_id, model_id=MODEL_ID)
        ws = await websockets.connect(
            url, additional_headers={"xi-api-key": self._api_key}, open_timeout=5
        )
        await ws.send(json.dumps({"text": " ", "voice_settings": VOICE_SETTINGS}))
        return TtsStreamSession(ws)

    def _preopen_next(self) -> None:
        """Pré-ouvre la session suivante en arrière-plan (best effort)."""

        async def _open() -> None:
            try:
                self._preopened = await self._connect()
            except Exception:
                logger.warning("Pré-ouverture de session TTS échouée", exc_info=True)

        self._preopen_task = asyncio.create_task(_open())

    async def acquire_stream(self) -> TtsStreamSession:
        """Récupère une session prête (pré-ouverte si possible) et en
        pré-ouvre une nouvelle pour la prochaine réponse."""
        if self._preopen_task is not None and not self._preopen_task.done():
            with contextlib.suppress(Exception):
                await self._preopen_task
        session = self._preopened
        self._preopened = None
        self._preopen_next()
        if session is not None and not session._ws.close_code:
            return session
        return await self._connect()

    def reset_context(self) -> None:
        """À appeler au début de chaque nouvelle réponse (tour de parole).

        Les phrases d'un même tour s'enchaînent naturellement (contexte
        chaîné) ; un nouveau tour reprend sur une base neutre plutôt que de
        hériter de la prosodie d'un tour précédent, potentiellement sur un
        tout autre sujet ou émotion.
        """
        self._recent_request_ids = []

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Synthétise une phrase et émet l'audio μ-law 8kHz par chunks."""
        url = ELEVENLABS_TTS_URL.format(voice_id=self._voice_id)
        payload = {
            "text": text,
            "model_id": MODEL_ID,
            "voice_settings": VOICE_SETTINGS,
        }
        if self._recent_request_ids:
            payload["previous_request_ids"] = self._recent_request_ids[-_CONTEXT_CHAIN_LENGTH:]
        async with self._client.stream(
            "POST",
            url,
            params={"output_format": "ulaw_8000"},
            json=payload,
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                logger.error("Erreur TTS %s : %s", response.status_code, body[:200])
                return
            request_id = response.headers.get("request-id")
            if request_id:
                self._recent_request_ids.append(request_id)
            async for chunk in response.aiter_bytes():
                if chunk:
                    yield chunk

    async def close(self) -> None:
        if self._preopen_task is not None:
            self._preopen_task.cancel()
            with contextlib.suppress(Exception):
                await self._preopen_task
        if self._preopened is not None:
            await self._preopened.close()
            self._preopened = None
        await self._client.aclose()

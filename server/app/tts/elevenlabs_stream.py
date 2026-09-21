"""TTS ElevenLabs en streaming, sortie μ-law 8kHz directement compatible Twilio.

Chaque phrase de l'agent est synthétisée dès qu'elle est prête (pas d'attente
de la réponse complète) et les chunks audio sont émis au fil du téléchargement.
"""

import logging
from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
DEFAULT_VOICE_ID = "pFZP5JQG7iQjIQuC4Bku"  # "Lily" — voix féminine, bon rendu FR
MODEL_ID = "eleven_turbo_v2_5"  # latence minimale, multilingue


class ElevenLabsTTS:
    """Client TTS réutilisé pour toutes les phrases d'un appel (connexion keep-alive)."""

    def __init__(self, api_key: str, voice_id: str = DEFAULT_VOICE_ID):
        self._voice_id = voice_id
        self._client = httpx.AsyncClient(
            headers={"xi-api-key": api_key},
            timeout=httpx.Timeout(10.0, read=30.0),
        )

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Synthétise une phrase et émet l'audio μ-law 8kHz par chunks."""
        url = ELEVENLABS_TTS_URL.format(voice_id=self._voice_id)
        async with self._client.stream(
            "POST",
            url,
            params={"output_format": "ulaw_8000"},
            json={
                "text": text,
                "model_id": MODEL_ID,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                logger.error("Erreur TTS %s : %s", response.status_code, body[:200])
                return
            async for chunk in response.aiter_bytes():
                if chunk:
                    yield chunk

    async def close(self) -> None:
        await self._client.aclose()

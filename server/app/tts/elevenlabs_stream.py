"""TTS ElevenLabs en streaming, sortie μ-law 8kHz directement compatible Twilio.

Chaque phrase de l'agent est synthétisée dès qu'elle est prête (pas d'attente
de la réponse complète) et les chunks audio sont émis au fil du téléchargement.
"""

import logging
from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"

# Une voix par langue, choisie pour son naturel dans cette langue plutôt que
# de réutiliser une même voix multilingue — cf app.telephony.twilio_media
# pour la liste des langues supportées et le choix par l'appelant (menu DTMF).
VOICE_IDS_BY_LANGUAGE = {
    "fr": "YxrwjAKoUKULGd0g8K9Y",  # voix française native, choisie pour le projet
    "en": "7EzWGsX10sAS4c9m9cPf",  # voix anglophone native, choisie pour le projet
}
DEFAULT_VOICE_ID = VOICE_IDS_BY_LANGUAGE["fr"]
# Flash v2.5 : latence la plus basse (~75-100ms) et débit le plus rapide en
# streaming parmi les modèles testés — eleven_v4_turbo est plus expressif
# mais génère ~2x plus lentement, ce qui risque de faire décrocher le flux
# audio temps réel derrière la lecture côté appelant.
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


class ElevenLabsTTS:
    """Client TTS réutilisé pour toutes les phrases d'un appel (connexion keep-alive)."""

    def __init__(self, api_key: str, voice_id: str = DEFAULT_VOICE_ID):
        self._voice_id = voice_id
        self._client = httpx.AsyncClient(
            headers={"xi-api-key": api_key},
            timeout=httpx.Timeout(10.0, read=30.0),
        )
        # request_id des phrases précédentes de la réponse en cours, chaînés
        # pour que la prosodie reste continue d'une phrase à l'autre au lieu
        # que chaque appel TTS séparé sonne comme un clip isolé recollé.
        self._recent_request_ids: list[str] = []

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
        await self._client.aclose()

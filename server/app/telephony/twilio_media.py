"""Protocole Twilio Media Streams.

Twilio envoie sur le WebSocket des messages JSON avec un event parmi :
`connected`, `start`, `media`, `stop`, `mark`. L'audio est en μ-law 8 kHz
mono, encodé base64 dans `media.payload`, par chunks de 20 ms (160 octets).

Référence : https://www.twilio.com/docs/voice/media-streams/websocket-messages
"""

import base64
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class TwilioEvent(str, Enum):
    CONNECTED = "connected"
    START = "start"
    MEDIA = "media"
    STOP = "stop"
    MARK = "mark"


SUPPORTED_LANGUAGES = {"fr", "en"}
DEFAULT_LANGUAGE = "fr"


@dataclass
class MediaStreamStart:
    """Métadonnées reçues dans l'événement `start`."""

    stream_sid: str
    call_sid: str
    caller_phone: str | None
    language: str = DEFAULT_LANGUAGE


def parse_message(raw: str) -> tuple[TwilioEvent | None, dict[str, Any]]:
    """Parse un message brut du WebSocket Twilio. Événement inconnu → (None, {})."""
    msg = json.loads(raw)
    try:
        event = TwilioEvent(msg.get("event", ""))
    except ValueError:
        return None, {}
    return event, msg


def parse_start(msg: dict[str, Any]) -> MediaStreamStart:
    start = msg["start"]
    custom = start.get("customParameters", {})
    language = custom.get("language", DEFAULT_LANGUAGE)
    if language not in SUPPORTED_LANGUAGES:
        language = DEFAULT_LANGUAGE
    return MediaStreamStart(
        stream_sid=start["streamSid"],
        call_sid=start["callSid"],
        caller_phone=custom.get("caller_phone"),
        language=language,
    )


def decode_media_payload(msg: dict[str, Any]) -> bytes:
    """Extrait le chunk audio μ-law 8kHz d'un événement `media`."""
    return base64.b64decode(msg["media"]["payload"])


def build_media_message(stream_sid: str, mulaw_audio: bytes) -> str:
    """Construit un message `media` sortant (audio agent → appelant)."""
    return json.dumps(
        {
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": base64.b64encode(mulaw_audio).decode("ascii")},
        }
    )


def build_clear_message(stream_sid: str) -> str:
    """Message `clear` : vide le buffer audio en cours de lecture côté Twilio.

    C'est le mécanisme du barge-in (Phase 2) — quand l'appelant interrompt
    l'agent, on envoie `clear` pour couper immédiatement la réponse en cours.
    """
    return json.dumps({"event": "clear", "streamSid": stream_sid})


def build_mark_message(stream_sid: str, name: str) -> str:
    """Message `mark` : Twilio le renvoie quand tout l'audio envoyé avant a été lu."""
    return json.dumps({"event": "mark", "streamSid": stream_sid, "mark": {"name": name}})


def build_stream_twiml(
    public_host: str, language: str = DEFAULT_LANGUAGE, caller_phone: str | None = None
) -> str:
    """TwiML du webhook d'appel entrant : ouvre directement le Media Stream.

    L'IA décroche immédiatement — aucune annonce <Say> robotique ni menu.
    La transparence IA et la mention de transcription (obligation légale,
    cf CLAUDE.md) sont portées par le message d'accueil ElevenLabs de
    l'agent, première chose que l'appelant entend
    (cf app.llm.claude_agent.GREETING_SENTENCES, testé pour ça).
    """
    if language not in SUPPORTED_LANGUAGES:
        language = DEFAULT_LANGUAGE
    caller_param = (
        f'<Parameter name="caller_phone" value="{caller_phone}"/>' if caller_phone else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://{public_host}/media-stream">
      {caller_param}
      <Parameter name="language" value="{language}"/>
    </Stream>
  </Connect>
</Response>"""

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


def build_language_menu_twiml(language_select_url: str) -> str:
    """TwiML du tout premier webhook : menu DTMF de choix de langue.

    <Gather> capture une touche et poste sur `language_select_url` avec le
    paramètre `Digits`. Si l'appelant ne tape rien avant le timeout, on
    retombe sur le français par défaut (le <Redirect> après </Gather> n'est
    joué que dans ce cas — un Digits capturé court-circuite directement vers
    `action`).
    """
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Gather numDigits="1" timeout="6" action="{language_select_url}" method="POST">
    <Say language="fr-FR" voice="alice">Pour continuer en français, tapez 2.</Say>
    <Say language="en-US" voice="alice">For English, press 1.</Say>
  </Gather>
  <Redirect method="POST">{language_select_url}?Digits=2</Redirect>
</Response>"""


# Touche DTMF -> code langue
_LANGUAGE_DIGITS = {"1": "en", "2": "fr"}

# Message de transparence IA (obligation légale, cf CLAUDE.md), par langue
_DISCLAIMER = {
    "fr": (
        "Bonjour, vous êtes en relation avec l'assistant vocal de démonstration "
        "Allo IA. Cet appel est transcrit pour assurer le service. Vous pouvez "
        "demander un humain à tout moment."
    ),
    "en": (
        "Hello, you are speaking with the Allo IA demonstration voice assistant. "
        "This call is transcribed to provide the service. You may ask for a human "
        "at any time."
    ),
}
_DISCLAIMER_TWILIO_LOCALE = {"fr": "fr-FR", "en": "en-US"}


def digit_to_language(digits: str | None) -> str:
    """Touche DTMF -> code langue. Toute valeur inconnue retombe sur le défaut."""
    return _LANGUAGE_DIGITS.get(digits or "", DEFAULT_LANGUAGE)


def build_stream_twiml(public_host: str, language: str, caller_phone: str | None = None) -> str:
    """TwiML renvoyé après le choix de langue : ouvre le Media Stream bidirectionnel.

    Le message de transparence IA (obligation légale, cf CLAUDE.md) est prononcé
    par <Say> AVANT l'ouverture du stream, dans la langue choisie : l'appelant
    est informé qu'il parle à une IA et que l'appel est transcrit, même si le
    pipeline échoue ensuite.
    """
    if language not in SUPPORTED_LANGUAGES:
        language = DEFAULT_LANGUAGE
    caller_param = (
        f'<Parameter name="caller_phone" value="{caller_phone}"/>' if caller_phone else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say language="{_DISCLAIMER_TWILIO_LOCALE[language]}" voice="alice">
    {_DISCLAIMER[language]}
  </Say>
  <Connect>
    <Stream url="wss://{public_host}/media-stream">
      {caller_param}
      <Parameter name="language" value="{language}"/>
    </Stream>
  </Connect>
</Response>"""

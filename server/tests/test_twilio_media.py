"""Tests du protocole Twilio Media Streams (parsing + construction de messages)."""

import base64
import json

from app.llm.claude_agent import GREETING_SENTENCES
from app.telephony.twilio_media import (
    TwilioEvent,
    build_clear_message,
    build_media_message,
    build_stream_twiml,
    decode_media_payload,
    parse_message,
    parse_start,
)


def test_parse_media_event_roundtrip():
    audio = bytes(range(160))  # un chunk de 20ms μ-law
    raw = json.dumps(
        {
            "event": "media",
            "streamSid": "MZxxxx",
            "media": {"payload": base64.b64encode(audio).decode("ascii")},
        }
    )
    event, msg = parse_message(raw)
    assert event is TwilioEvent.MEDIA
    assert decode_media_payload(msg) == audio


def test_parse_start_event():
    raw = json.dumps(
        {
            "event": "start",
            "start": {
                "streamSid": "MZ123",
                "callSid": "CA456",
                "customParameters": {"caller_phone": "+33612345678"},
            },
        }
    )
    event, msg = parse_message(raw)
    assert event is TwilioEvent.START
    info = parse_start(msg)
    assert info.stream_sid == "MZ123"
    assert info.call_sid == "CA456"
    assert info.caller_phone == "+33612345678"


def test_parse_start_without_caller_phone():
    raw = json.dumps({"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA1"}})
    _, msg = parse_message(raw)
    assert parse_start(msg).caller_phone is None


def test_parse_start_defaults_to_french():
    raw = json.dumps({"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA1"}})
    _, msg = parse_message(raw)
    assert parse_start(msg).language == "fr"


def test_parse_start_reads_english_language():
    raw = json.dumps(
        {
            "event": "start",
            "start": {
                "streamSid": "MZ1",
                "callSid": "CA1",
                "customParameters": {"language": "en"},
            },
        }
    )
    _, msg = parse_message(raw)
    assert parse_start(msg).language == "en"


def test_parse_start_unknown_language_falls_back_to_french():
    raw = json.dumps(
        {
            "event": "start",
            "start": {
                "streamSid": "MZ1",
                "callSid": "CA1",
                "customParameters": {"language": "de"},
            },
        }
    )
    _, msg = parse_message(raw)
    assert parse_start(msg).language == "fr"


def test_parse_unknown_event_is_ignored():
    event, msg = parse_message(json.dumps({"event": "dtmf"}))
    assert event is None
    assert msg == {}


def test_build_media_message():
    audio = b"\x00\x7f\xff"
    msg = json.loads(build_media_message("MZ9", audio))
    assert msg["event"] == "media"
    assert msg["streamSid"] == "MZ9"
    assert base64.b64decode(msg["media"]["payload"]) == audio


def test_build_clear_message():
    msg = json.loads(build_clear_message("MZ9"))
    assert msg == {"event": "clear", "streamSid": "MZ9"}


def test_twiml_opens_stream_immediately():
    """L'IA décroche directement : pas de <Say> robotique ni de menu."""
    twiml = build_stream_twiml("example.fly.dev", caller_phone="+33600000000")
    assert "<Say" not in twiml
    assert "<Gather" not in twiml
    assert "wss://example.fly.dev/media-stream" in twiml
    assert 'value="+33600000000"' in twiml
    assert 'name="language" value="fr"' in twiml


def test_twiml_unknown_language_falls_back_to_french():
    twiml = build_stream_twiml("example.fly.dev", "de")
    assert 'name="language" value="fr"' in twiml


def test_greeting_carries_legal_disclosure():
    """Sans <Say> Twilio, l'accueil ElevenLabs est la première chose entendue :
    c'est lui qui doit porter la transparence IA et la mention de la
    transcription (obligations non négociables du CLAUDE.md)."""
    fr = " ".join(GREETING_SENTENCES["fr"]).lower()
    assert "assistante vocale" in fr  # l'appelant sait qu'il parle à une IA
    assert "transcrit" in fr  # consentement à la transcription
    en = " ".join(GREETING_SENTENCES["en"]).lower()
    assert "voice assistant" in en
    assert "transcribed" in en

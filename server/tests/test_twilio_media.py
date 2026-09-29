"""Tests du protocole Twilio Media Streams (parsing + construction de messages)."""

import base64
import json

from app.telephony.twilio_media import (
    TwilioEvent,
    build_clear_message,
    build_language_menu_twiml,
    build_media_message,
    build_stream_twiml,
    decode_media_payload,
    digit_to_language,
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


def test_twiml_announces_ai_before_stream():
    """La transparence IA (obligation légale) doit précéder l'ouverture du stream."""
    twiml = build_stream_twiml("example.fly.dev", "fr", caller_phone="+33600000000")
    assert "assistant vocal" in twiml
    assert "transcrit" in twiml  # consentement à la transcription
    assert twiml.index("<Say") < twiml.index("<Connect>")
    assert "wss://example.fly.dev/media-stream" in twiml
    assert 'value="+33600000000"' in twiml
    assert 'name="language" value="fr"' in twiml


def test_twiml_english_disclaimer():
    twiml = build_stream_twiml("example.fly.dev", "en")
    assert "Hello, you are speaking" in twiml
    assert 'language="en-US"' in twiml
    assert 'name="language" value="en"' in twiml


def test_twiml_unknown_language_falls_back_to_french():
    twiml = build_stream_twiml("example.fly.dev", "de")
    assert "assistant vocal" in twiml
    assert 'name="language" value="fr"' in twiml


def test_language_menu_twiml_structure():
    twiml = build_language_menu_twiml("https://example.fly.dev/voice/start")
    assert "<Gather" in twiml
    assert 'action="https://example.fly.dev/voice/start"' in twiml
    assert "français" in twiml
    assert "English" in twiml
    # Fallback si l'appelant ne tape rien : français par défaut
    assert "Digits=2" in twiml


def test_digit_to_language():
    assert digit_to_language("1") == "en"
    assert digit_to_language("2") == "fr"
    assert digit_to_language(None) == "fr"
    assert digit_to_language("") == "fr"
    assert digit_to_language("9") == "fr"  # touche inconnue -> défaut

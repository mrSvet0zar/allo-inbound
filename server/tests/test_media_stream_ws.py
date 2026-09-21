"""Test d'intégration du WebSocket /media-stream avec un STT factice.

Simule la séquence d'événements Twilio (start → media → stop) et vérifie
que l'audio est bien relayé vers le STT et que la session se ferme proprement.
"""

import base64
import json
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


def _twilio_events():
    audio = base64.b64encode(bytes(160)).decode("ascii")
    return [
        json.dumps({"event": "connected", "protocol": "Call"}),
        json.dumps({"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA1"}}),
        json.dumps({"event": "media", "streamSid": "MZ1", "media": {"payload": audio}}),
        json.dumps({"event": "media", "streamSid": "MZ1", "media": {"payload": audio}}),
        json.dumps({"event": "stop", "streamSid": "MZ1"}),
    ]


@patch("app.core.call_session.DeepgramStream")
def test_full_call_sequence(mock_stt_cls):
    mock_stt = AsyncMock()
    mock_stt_cls.return_value = mock_stt

    client = TestClient(app)
    with client.websocket_connect("/media-stream") as ws:
        for event in _twilio_events():
            ws.send_text(event)

    mock_stt.connect.assert_awaited_once()
    assert mock_stt.send_audio.await_count == 2
    mock_stt.close.assert_awaited_once()


def test_voice_webhook_returns_twiml():
    client = TestClient(app)
    resp = client.post("/voice", data={"From": "+33612345678"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    assert "<Connect>" in resp.text


def test_health():
    assert TestClient(app).get("/health").json() == {"status": "ok"}

"""Serveur temps réel Allo-IA.

Deux endpoints :
- POST /voice : webhook Twilio d'appel entrant → renvoie le TwiML qui annonce
  la transparence IA puis ouvre le Media Stream
- WS /media-stream : flux audio bidirectionnel pendant toute la durée de l'appel
"""

import logging

from fastapi import FastAPI, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from app.config import get_settings
from app.core.call_session import CallSession
from app.telephony.twilio_media import (
    TwilioEvent,
    build_stream_twiml,
    decode_media_payload,
    parse_message,
    parse_start,
)

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Allo-IA — serveur temps réel")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/voice")
async def incoming_call(From: str = Form(default="")) -> Response:
    """Webhook Twilio : un appel arrive sur le numéro."""
    logger.info("Appel entrant de %s", From or "(numéro masqué)")
    twiml = build_stream_twiml(settings.public_host, caller_phone=From or None)
    return Response(content=twiml, media_type="application/xml")


@app.websocket("/media-stream")
async def media_stream(ws: WebSocket) -> None:
    """WebSocket Twilio Media Streams — une connexion par appel."""
    await ws.accept()
    session: CallSession | None = None
    try:
        while True:
            raw = await ws.receive_text()
            event, msg = parse_message(raw)
            if event is TwilioEvent.START:
                session = CallSession(settings, parse_start(msg))
                await session.start()
            elif event is TwilioEvent.MEDIA and session is not None:
                await session.on_audio_chunk(decode_media_payload(msg))
            elif event is TwilioEvent.STOP:
                break
    except WebSocketDisconnect:
        logger.info("WebSocket Twilio déconnecté")
    finally:
        if session is not None:
            await session.close()

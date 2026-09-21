"""Transfert d'appel vers un humain (escalade).

Redirige l'appel en cours via l'API REST Twilio : le TwiML <Dial> remplace le
Media Stream, l'appelant est mis en relation avec le numéro humain configuré.
Le client Twilio est synchrone → exécuté dans un thread pour ne pas bloquer
la boucle asyncio (qui relaie l'audio des autres appels).
"""

import asyncio
import logging

from twilio.rest import Client

from app.config import Settings

logger = logging.getLogger(__name__)

TRANSFER_TWIML = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say language="fr-FR" voice="alice">Je vous mets en relation avec un conseiller.</Say>
  <Dial>{human_number}</Dial>
</Response>"""


async def transfer_call_to_human(settings: Settings, call_sid: str) -> bool:
    """Redirige l'appel vers le numéro humain. Retourne False si non configuré."""
    if not settings.human_transfer_number:
        logger.warning("Escalade demandée mais HUMAN_TRANSFER_NUMBER non configuré")
        return False

    def _redirect() -> None:
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.calls(call_sid).update(
            twiml=TRANSFER_TWIML.format(human_number=settings.human_transfer_number)
        )

    try:
        await asyncio.to_thread(_redirect)
        logger.info("Appel %s transféré vers un humain", call_sid)
        return True
    except Exception:
        logger.exception("Échec du transfert de l'appel %s", call_sid)
        return False

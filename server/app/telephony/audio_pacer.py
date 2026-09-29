"""Cadence l'envoi des chunks audio μ-law 8kHz au débit de lecture réel.

Sans ça, un long segment de réponse (ex: une énumération de créneaux) est
généré et envoyé à Twilio en 1-2 secondes alors qu'il faut plusieurs
secondes pour le prononcer — la tâche serveur se termine bien avant la fin
de la lecture audio côté Twilio. Le barge-in devient alors inefficace :
`_is_speaking()` répond "non" (la tâche est déjà terminée) au moment où
l'appelant interrompt, donc aucun `clear` n'est envoyé, et Twilio continue
de jouer son buffer déjà rempli jusqu'au bout.

Cadencer l'envoi garde la tâche active pendant toute la durée réelle de la
parole, ce qui rend l'annulation (et le `clear` Twilio) réellement efficace.
"""

import asyncio
import time
from collections.abc import Callable

# μ-law 8kHz mono : 1 octet par échantillon = 8000 octets/seconde
BYTES_PER_SECOND = 8000


class AudioPacer:
    """À utiliser une instance par réponse (peut couvrir plusieurs phrases/chunks)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._start: float | None = None
        self._bytes_sent = 0

    def delay_for(self, chunk_len: int) -> float:
        """Délai à attendre avant d'envoyer ce chunk (0 pour le tout premier).

        Le premier chunk part immédiatement (latence perçue préservée) ; les
        suivants sont retardés si le débit d'envoi dépasse le débit de
        lecture réel, en se basant sur le temps écoulé depuis le premier
        chunk et le volume déjà envoyé.
        """
        now = self._clock()
        if self._start is None:
            self._start = now
            self._bytes_sent = chunk_len
            return 0.0
        target_elapsed = self._bytes_sent / BYTES_PER_SECOND
        actual_elapsed = now - self._start
        self._bytes_sent += chunk_len
        return max(0.0, target_elapsed - actual_elapsed)

    async def pace(self, chunk: bytes) -> None:
        delay = self.delay_for(len(chunk))
        if delay > 0:
            await asyncio.sleep(delay)

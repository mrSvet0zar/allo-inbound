"""Tests du cadencement audio (calcul pur, sans vraie attente — clock injectée)."""

import pytest

from app.telephony.audio_pacer import BYTES_PER_SECOND, AudioPacer


class FakeClock:
    """Horloge contrôlable manuellement pour tester le calcul de délai."""

    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_first_chunk_has_no_delay():
    """Le tout premier chunk part immédiatement (latence perçue préservée)."""
    pacer = AudioPacer(clock=FakeClock())
    assert pacer.delay_for(4000) == 0.0


def test_second_chunk_delayed_when_sent_too_fast():
    clock = FakeClock()
    pacer = AudioPacer(clock=clock)
    # Un chunk de 8000 octets = 1s d'audio, envoyé instantanément (t=0)
    pacer.delay_for(BYTES_PER_SECOND)
    # Le chunk suivant arrive quasi aussitôt (t=0.01s) : il représente encore
    # 1s d'audio, mais rien n'a été "joué" depuis le premier chunk → on doit
    # attendre environ 1s avant de l'envoyer pour respecter le débit réel.
    clock.advance(0.01)
    delay = pacer.delay_for(BYTES_PER_SECOND)
    assert delay == pytest.approx(1.0, abs=0.02)


def test_no_delay_when_generation_keeps_up_with_playback():
    """Si le temps réel écoulé rattrape le débit de lecture, pas d'attente."""
    clock = FakeClock()
    pacer = AudioPacer(clock=clock)
    pacer.delay_for(BYTES_PER_SECOND)  # t=0, 1s d'audio envoyée
    clock.advance(1.5)  # 1.5s se sont écoulées réellement (TTS a pris du temps)
    delay = pacer.delay_for(BYTES_PER_SECOND)
    assert delay == 0.0


def test_cumulative_pacing_across_many_small_chunks():
    """Le cadencement doit tenir sur toute la durée d'une longue réponse,
    pas seulement chunk par chunk (régression sur l'énumération de créneaux)."""
    clock = FakeClock()
    pacer = AudioPacer(clock=clock)
    chunk = 1600  # 0.2s d'audio par chunk
    total_delay = 0.0
    for i in range(10):  # 10 chunks = 2s d'audio au total
        d = pacer.delay_for(chunk)
        total_delay += d
        clock.advance(d)  # simule l'attente réellement effectuée
    # ~2s d'audio générées quasi instantanément (aucune avance de clock hors
    # délais) → le total des délais doit approcher 2s, moins le 1er chunk gratuit
    assert total_delay == pytest.approx(2.0 - chunk / BYTES_PER_SECOND, abs=0.05)


async def test_pace_calls_asyncio_sleep_with_computed_delay(monkeypatch):
    import app.telephony.audio_pacer as module

    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(module.asyncio, "sleep", fake_sleep)

    clock = FakeClock()
    pacer = AudioPacer(clock=clock)
    await pacer.pace(b"\x00" * BYTES_PER_SECOND)  # 1er chunk : pas de sleep
    assert slept == []
    await pacer.pace(b"\x00" * BYTES_PER_SECOND)  # 2e chunk immédiat : sleep ~1s
    assert len(slept) == 1
    assert slept[0] > 0.9

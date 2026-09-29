"""Tests du chaînage de contexte ElevenLabs (continuité de prosodie entre phrases)."""

from app.tts.elevenlabs_stream import ElevenLabsTTS


class FakeResponse:
    def __init__(self, status_code=200, headers=None, chunks=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks or [b"\x00\x01"]

    async def aiter_bytes(self):
        for c in self._chunks:
            yield c

    async def aread(self):
        return b""


class FakeStreamCtx:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *args):
        return False


class FakeClient:
    """Remplace httpx.AsyncClient : enregistre les payloads envoyés, sans réseau."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.sent_payloads: list[dict] = []

    def stream(self, method, url, params=None, json=None):
        self.sent_payloads.append(json)
        return FakeStreamCtx(self._responses.pop(0))

    async def aclose(self):
        pass


def _make_tts(responses):
    tts = ElevenLabsTTS(api_key="fake-key")
    tts._client = FakeClient(responses)
    return tts


async def _drain(agen):
    return [chunk async for chunk in agen]


async def test_first_call_has_no_previous_request_ids():
    tts = _make_tts([FakeResponse(headers={"request-id": "req-1"})])
    await _drain(tts.synthesize("Bonjour."))
    assert "previous_request_ids" not in tts._client.sent_payloads[0]


async def test_second_call_chains_previous_request_id():
    tts = _make_tts(
        [
            FakeResponse(headers={"request-id": "req-1"}),
            FakeResponse(headers={"request-id": "req-2"}),
        ]
    )
    await _drain(tts.synthesize("Bonjour."))
    await _drain(tts.synthesize("Comment allez-vous ?"))
    assert tts._client.sent_payloads[1]["previous_request_ids"] == ["req-1"]


async def test_chain_caps_at_three_ids():
    tts = _make_tts([FakeResponse(headers={"request-id": f"req-{i}"}) for i in range(5)])
    for i in range(5):
        await _drain(tts.synthesize(f"Phrase {i}."))
    last_payload = tts._client.sent_payloads[-1]
    assert last_payload["previous_request_ids"] == ["req-1", "req-2", "req-3"]


async def test_reset_context_clears_chain():
    tts = _make_tts(
        [
            FakeResponse(headers={"request-id": "req-1"}),
            FakeResponse(headers={"request-id": "req-2"}),
        ]
    )
    await _drain(tts.synthesize("Première réponse."))
    tts.reset_context()
    await _drain(tts.synthesize("Nouvelle réponse, nouveau tour."))
    assert "previous_request_ids" not in tts._client.sent_payloads[1]


async def test_missing_request_id_header_does_not_crash():
    tts = _make_tts([FakeResponse(headers={}), FakeResponse(headers={"request-id": "req-2"})])
    await _drain(tts.synthesize("Bonjour."))
    await _drain(tts.synthesize("Suite."))
    # aucun request-id la 1ère fois -> rien à chaîner pour le 2e appel
    assert "previous_request_ids" not in tts._client.sent_payloads[1]


async def test_error_response_does_not_record_request_id():
    tts = _make_tts(
        [
            FakeResponse(status_code=401, headers={"request-id": "should-not-be-used"}),
            FakeResponse(status_code=200, headers={"request-id": "req-ok"}),
        ]
    )
    await _drain(tts.synthesize("Erreur."))
    await _drain(tts.synthesize("Retente."))
    assert "previous_request_ids" not in tts._client.sent_payloads[1]

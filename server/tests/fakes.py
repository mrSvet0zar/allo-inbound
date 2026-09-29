"""Doubles de test partagés pour le pipeline vocal."""

import asyncio


class FakeTtsStream:
    """Session TTS WebSocket factice : enregistre le texte, rejoue des chunks."""

    def __init__(self, chunks: list[bytes]):
        self._chunks = list(chunks)
        self.sent_sentences: list[str] = []
        self.ended = False
        self.closed = False

    async def send_sentence(self, text: str) -> None:
        self.sent_sentences.append(text)

    async def end(self) -> None:
        self.ended = True

    async def audio_chunks(self):
        for chunk in self._chunks:
            yield chunk
            await asyncio.sleep(0)  # laisse une chance au barge-in

    async def close(self) -> None:
        self.closed = True

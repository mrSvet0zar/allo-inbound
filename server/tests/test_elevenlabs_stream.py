"""Tests du choix de voix ElevenLabs par langue."""

from app.tts.elevenlabs_stream import DEFAULT_VOICE_ID, VOICE_IDS_BY_LANGUAGE, voice_id_for_language


def test_french_and_english_have_distinct_voices():
    assert VOICE_IDS_BY_LANGUAGE["fr"] != VOICE_IDS_BY_LANGUAGE["en"]


def test_voice_id_for_french():
    assert voice_id_for_language("fr") == VOICE_IDS_BY_LANGUAGE["fr"]


def test_voice_id_for_english():
    assert voice_id_for_language("en") == VOICE_IDS_BY_LANGUAGE["en"]


def test_voice_id_unknown_language_falls_back_to_default():
    assert voice_id_for_language("de") == DEFAULT_VOICE_ID


def test_default_voice_is_french():
    assert DEFAULT_VOICE_ID == VOICE_IDS_BY_LANGUAGE["fr"]

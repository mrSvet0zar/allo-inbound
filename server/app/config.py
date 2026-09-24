"""Configuration centralisée du serveur temps réel Allo-IA."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # STT
    deepgram_api_key: str = ""
    deepgram_model: str = "nova-3"
    deepgram_language: str = "fr"

    # LLM (Phase 2)
    anthropic_api_key: str = ""

    # TTS (Phase 2)
    elevenlabs_api_key: str = ""

    # Base de données — vide = backends en mémoire (dev sans infra)
    database_url: str = ""

    # Numéro vers lequel transférer en cas d'escalade humaine (vide = pas de transfert)
    human_transfer_number: str = ""

    # Clé partagée protégeant l'API admin du dashboard (vide = accès ouvert, dev local)
    admin_api_key: str = ""

    # Origines autorisées à appeler l'API admin (dashboard Next.js), séparées par des virgules
    dashboard_origins: str = "http://localhost:3000"

    @property
    def dashboard_origins_list(self) -> list[str]:
        return [o.strip() for o in self.dashboard_origins.split(",") if o.strip()]

    # Serveur — URL publique (ngrok en dev, Fly.io en prod) utilisée
    # pour construire l'URL wss:// du Media Stream dans le TwiML
    public_host: str = "localhost:8000"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()

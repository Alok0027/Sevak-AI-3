"""
Central settings for SevakAI backend.

Everything the SRS calls out as an external dependency (Bhashini, the LLM,
WhatsApp) is read from environment variables here and nowhere else, so
swapping from mocks to live APIs is a one-file change (see .env.example).
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Mode switch: while True, every external call (Bhashini, LLM, WhatsApp)
    # is served by the mock clients in app/services/*_client.py.
    use_mocks: bool = True

    # Database
    database_url: str = "sqlite:///./sevakai_dev.db"

    # Auth
    jwt_secret: str = "change-me-before-any-real-deployment"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    # Speech-to-text provider: "mock" | "whisper" | "bhashini". Independent
    # of use_mocks -- lets us run real speech recognition (local Whisper)
    # while LLM extraction / WhatsApp stay mocked, e.g. while Bhashini API
    # access is still pending approval.
    stt_provider: str = "mock"
    whisper_model_size: str = "small"

    # Bhashini
    bhashini_api_key: str = ""
    bhashini_user_id: str = ""
    bhashini_pipeline_id: str = ""
    bhashini_base_url: str = "https://meity-auth.ulcacontrib.org"

    # LLM
    llm_api_key: str = ""
    llm_model: str = "gpt-4o"
    llm_base_url: str = "https://api.openai.com/v1"

    # WhatsApp
    whatsapp_api_token: str = ""
    whatsapp_phone_number_id: str = ""

    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()

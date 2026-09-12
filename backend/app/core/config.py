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

    # NFR-SC1: AES-256 key (urlsafe-base64, 32 raw bytes) for encrypting
    # patient data at rest -- see app/core/encryption.py. Generate one with
    # scripts/generate_encryption_key.py; empty is only valid until the
    # first encrypted field is touched, which raises EncryptionKeyError.
    encryption_key: str = ""

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

    # LLM provider: "mock" | "real". Independent of use_mocks, same reasoning
    # as stt_provider above -- a real LLM key (e.g. a free Groq key) can be
    # turned on without also flipping WhatsApp to the real Graph API, which
    # would need its own separate credentials.
    llm_provider: str = "mock"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o"
    llm_base_url: str = "https://api.openai.com/v1"

    # WhatsApp provider: "mock" | "meta" | "twilio_sandbox".
    #   meta           -- the real WhatsApp Business API; needs Meta approval.
    #   twilio_sandbox -- Twilio's WhatsApp sandbox. No Meta approval and
    #                     works on a free Twilio trial, so it's the one
    #                     path that delivers Agent 3's real (free-form)
    #                     message without a paid/approved account. Reuses
    #                     the TWILIO_* credentials below. Each recipient
    #                     must first send "join <code>" to the sandbox
    #                     number, and the session lapses after three days.
    whatsapp_provider: str = "mock"
    whatsapp_api_token: str = ""
    whatsapp_phone_number_id: str = ""
    # The approved template Agent 3 sends on the meta path. A follow-up
    # reminder is business-initiated -- the patient has not messaged us, so
    # there is no open 24-hour window and free-form text is refused
    # (131047). The template is what gets delivered; the LLM's fuller
    # message is still what gets stored and shown.
    #
    # Declare it in Meta with three positional blanks, in this order:
    #   {{1}} patient name   {{2}} risk level, in her language   {{3}} when
    whatsapp_template_name: str = "followup_reminder"
    whatsapp_template_language: str = "hi"
    # Only needed to create or list templates (scripts/create_whatsapp_
    # template.py). Sending uses the phone number ID above. Not a secret:
    # it identifies the business account, it does not authorise anything.
    whatsapp_business_account_id: str = ""
    # Twilio's shared sandbox sender -- the same for every account.
    twilio_whatsapp_from: str = "whatsapp:+14155238886"

    # SMS provider: "mock" | "real" (Twilio). Independent of use_mocks and
    # WhatsApp -- a real delivery channel for the same message Agent 3
    # already drafts, for teams without WhatsApp Business API access yet
    # (SRS section 11 risk register: "Use Twilio SMS as instant fallback").
    sms_provider: str = "mock"
    twilio_account_sid: str = ""
    twilio_api_key_sid: str = ""
    twilio_api_key_secret: str = ""
    twilio_phone_number: str = ""

    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""SMS client for Agent 3 patient communication (Twilio) -- a real delivery
channel for the same message Agent 3 already drafts for WhatsApp, for teams
without WhatsApp Business API access yet (SRS section 11 risk register:
"Use Twilio SMS as instant fallback"). Mirrors the LLM/WhatsApp client
pattern: mock by default, real Twilio call once SMS_PROVIDER=real and the
TWILIO_* env vars are set. Independent of USE_MOCKS and WhatsApp -- turning
this on doesn't touch either.

Worth knowing before choosing this channel for India: Twilio delivers to
Indian numbers over an international route that replaces the sender ID
with a random short code, so SMS here is one-way only -- a patient cannot
reply. A branded, two-way sender ID needs DLT registration with the Indian
operators. See TwilioWhatsAppClient for the two-way alternative.
"""
from abc import ABC, abstractmethod

from app.core.config import Settings
from app.services.twilio_rest import send_message, to_e164_in


class SmsClientBase(ABC):
    @abstractmethod
    async def send_message(self, to_phone: str, message: str) -> dict:
        ...


class MockSmsClient(SmsClientBase):
    async def send_message(self, to_phone: str, message: str) -> dict:
        return {"status": "mock_sent", "to": to_phone, "message": message}


class TwilioSmsClient(SmsClientBase):
    """Real Twilio SMS via the REST API (see app/services/twilio_rest.py,
    shared with the WhatsApp sandbox client)."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def send_message(self, to_phone: str, message: str) -> dict:
        return await send_message(
            self.settings,
            to=to_e164_in(to_phone),
            from_=self.settings.twilio_phone_number,
            body=message,
        )


def get_sms_client(settings: Settings) -> SmsClientBase:
    return TwilioSmsClient(settings) if settings.sms_provider.lower() == "real" else MockSmsClient()

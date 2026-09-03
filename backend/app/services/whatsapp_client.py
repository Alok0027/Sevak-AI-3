"""WhatsApp Business API client for Agent 3 patient communication (FR-04.2).

Mirrors the Bhashini/LLM pattern: mock by default, real Meta Business API
call once WHATSAPP_API_TOKEN / WHATSAPP_PHONE_NUMBER_ID are set and
USE_MOCKS=false. The SRS risk register (section 11) flags WhatsApp approval
delay as High likelihood -- MockWhatsAppClient lets the rest of the pipeline
(and the demo) work regardless of approval status; swap in an SMS/Twilio
fallback here if needed without touching Agent 3.
"""
from abc import ABC, abstractmethod

import httpx

from app.core.config import Settings


class WhatsAppClientBase(ABC):
    @abstractmethod
    async def send_message(self, to_phone: str, message: str) -> dict:
        ...


class MockWhatsAppClient(WhatsAppClientBase):
    async def send_message(self, to_phone: str, message: str) -> dict:
        return {"status": "mock_sent", "to": to_phone, "message": message}


class WhatsAppClient(WhatsAppClientBase):
    def __init__(self, settings: Settings):
        self.settings = settings

    async def send_message(self, to_phone: str, message: str) -> dict:
        url = f"https://graph.facebook.com/v20.0/{self.settings.whatsapp_phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.settings.whatsapp_api_token}"}
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "text",
            "text": {"body": message},
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()


def get_whatsapp_client(settings: Settings) -> WhatsAppClientBase:
    return MockWhatsAppClient() if settings.use_mocks else WhatsAppClient(settings)

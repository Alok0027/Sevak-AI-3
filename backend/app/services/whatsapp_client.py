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
from app.services.twilio_rest import send_message as send_twilio_message
from app.services.twilio_rest import to_e164_in


class WhatsAppClientBase(ABC):
    @abstractmethod
    async def send_message(self, to_phone: str, message: str) -> dict:
        ...

    async def send_template(
        self,
        to_phone: str,
        template_name: str,
        body_params: list[str] | None = None,
        language_code: str = "en_US",
    ) -> dict:
        """Send a pre-approved template.

        Necessary, not optional, for what this product actually does. A
        follow-up reminder is business-initiated: the patient has not
        messaged us, so there is no open 24-hour customer service window,
        and free-form text is refused (error 131047). Only an approved
        template gets through.

        Providers that have no template concept override this to say so
        rather than quietly sending something else.
        """
        raise NotImplementedError(
            f"{type(self).__name__} cannot send templates; "
            "set WHATSAPP_PROVIDER=meta to use them."
        )


class MockWhatsAppClient(WhatsAppClientBase):
    async def send_message(self, to_phone: str, message: str) -> dict:
        return {"status": "mock_sent", "to": to_phone, "message": message}

    async def send_template(
        self,
        to_phone: str,
        template_name: str,
        body_params: list[str] | None = None,
        language_code: str = "en_US",
    ) -> dict:
        return {
            "status": "mock_sent",
            "to": to_phone,
            "template": template_name,
            "params": body_params or [],
        }


class WhatsAppClient(WhatsAppClientBase):
    def __init__(self, settings: Settings):
        self.settings = settings

    async def send_message(self, to_phone: str, message: str) -> dict:
        url = f"https://graph.facebook.com/v20.0/{self.settings.whatsapp_phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.settings.whatsapp_api_token}"}
        payload = {
            "messaging_product": "whatsapp",
            # Meta wants the country code, and it wants it without the
            # leading "+". Every phone number in this project is stored as
            # a bare 10-digit Indian number, so sending to_phone straight
            # through silently delivers to nobody: the API returns 200 with
            # a message id, and the message never arrives.
            "to": to_e164_in(to_phone).lstrip("+"),
            "type": "text",
            "text": {"body": message},
        }
        return await self._post(payload)

    async def send_template(
        self,
        to_phone: str,
        template_name: str,
        body_params: list[str] | None = None,
        language_code: str = "en_US",
    ) -> dict:
        template: dict = {
            "name": template_name,
            "language": {"code": language_code},
        }
        if body_params:
            # Positional {{1}}, {{2}}… substitutions, in order. Meta rejects
            # the whole send if the count doesn't match what the approved
            # template declares, so the template and this list have to be
            # changed together.
            template["components"] = [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(p)} for p in body_params],
                }
            ]
        return await self._post(
            {
                "messaging_product": "whatsapp",
                "to": to_e164_in(to_phone).lstrip("+"),
                "type": "template",
                "template": template,
            }
        )

    async def _post(self, payload: dict) -> dict:
        url = f"https://graph.facebook.com/v20.0/{self.settings.whatsapp_phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.settings.whatsapp_api_token}"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                # Same reason the Twilio client does this: raise_for_status()
                # drops the body, and Meta puts the whole diagnosis there --
                # code 131030 (recipient not in the test allow-list), 131047
                # (outside the 24-hour window, needs a template), 190 (token
                # expired). Without it you get a bare "400 Bad Request" and
                # no idea which of those it was.
                raise WhatsAppError(_describe(resp))
            return resp.json()


class WhatsAppError(RuntimeError):
    """A Meta API refusal, with the reason Meta actually gave."""


def _describe(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error", {})
    except ValueError:
        return f"HTTP {resp.status_code}: {resp.text[:200]}"
    code = err.get("code")
    detail = err.get("error_user_msg") or err.get("message") or resp.text[:200]
    hint = _HINTS.get(code)
    return f"[{code}] {detail}" + (f" — {hint}" if hint else "")


# The four that account for nearly every failed send during a first
# integration. Printing the right one turns a support search into a fix.
_HINTS = {
    190: "the access token expired or was regenerated; update WHATSAPP_API_TOKEN",
    131030: "recipient is not in the app's test allow-list — add the number under "
            "WhatsApp > API Setup, or move off the test number",
    131047: "outside the 24-hour customer service window; free-form text is not "
            "allowed, send an approved template instead",
    131026: "the recipient has no WhatsApp account, or the number is malformed",
}


class TwilioWhatsAppClient(WhatsAppClientBase):
    """WhatsApp via Twilio's sandbox -- the same REST endpoint and
    credentials as TwilioSmsClient, with a "whatsapp:" prefix on both
    numbers.

    Chosen over the Meta path above because it needs no Business API
    approval and works on a free trial account, which is the difference
    between demoing a real delivered message and demoing a mock. Inside
    the 24-hour session window it accepts free-form text, so Agent 3's
    generated Hindi message goes through unchanged rather than being
    squeezed into one of the three approved templates.

    The tradeoff is opt-in: each recipient must first send "join <code>"
    to the shared sandbox number, and the session lapses after three days.
    Fine for a pilot or a demo, not a path to real patient rollout -- that
    still needs an approved WhatsApp Business sender, at which point
    WhatsAppClient above (or a registered Twilio sender) takes over with
    no change to Agent 3.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    async def send_message(self, to_phone: str, message: str) -> dict:
        return await send_twilio_message(
            self.settings,
            to=f"whatsapp:{to_e164_in(to_phone)}",
            from_=self.settings.twilio_whatsapp_from,
            body=message,
        )


def get_whatsapp_client(settings: Settings) -> WhatsAppClientBase:
    provider = settings.whatsapp_provider.lower()
    if provider == "twilio_sandbox":
        return TwilioWhatsAppClient(settings)
    if provider == "meta":
        return WhatsAppClient(settings)
    if provider == "mock":
        return MockWhatsAppClient()
    # Unset: keeps the original USE_MOCKS-driven behaviour, so a deployment
    # that never configured this one variable does not change meaning.
    return MockWhatsAppClient() if settings.use_mocks else WhatsAppClient(settings)

"""One Twilio Messages API call, shared by the SMS and WhatsApp clients.

Both channels are the same REST endpoint with the same credentials -- only
the From/To differ (a bare number for SMS, a "whatsapp:"-prefixed one for
WhatsApp) -- so the request, the auth and the error handling live here
once instead of being duplicated and drifting apart.
"""
import httpx

from app.core.config import Settings


def to_e164_in(phone: str) -> str:
    """ponytail: assumes India (+91) when no country code is present. Every
    phone number in this project's synthetic/demo data is a bare 10-digit
    Indian number, so this is correct for the data that actually exists
    today. Upgrade path: use a real E.164 parser (e.g. the `phonenumbers`
    library) before this ever has to handle a real, user-entered number
    that might not be Indian."""
    phone = phone.strip()
    return phone if phone.startswith("+") else f"+91{phone}"


async def send_message(settings: Settings, *, to: str, from_: str, body: str) -> dict:
    """POST one message. Basic Auth with an API Key SID/Secret pair, which
    is Twilio's recommended credential over the account's master Auth
    Token. Plain httpx; no twilio SDK dependency for a single endpoint."""
    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"
    auth = (settings.twilio_api_key_sid, settings.twilio_api_key_secret)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, auth=auth, data={"To": to, "From": from_, "Body": body})
        if resp.status_code >= 400:
            # raise_for_status() alone drops the body, and Twilio puts the
            # entire diagnosis there: a numeric code and a sentence naming
            # the cause (21608 unverified recipient on a trial account,
            # 21606 a From number the account doesn't own, 63015 a
            # WhatsApp recipient who never joined the sandbox). Without it
            # every failure looks like an indistinguishable HTTP 400.
            detail = resp.text[:400]
            try:
                error = resp.json()
                detail = f"{error.get('code')}: {error.get('message')} ({error.get('more_info')})"
            except Exception:  # noqa: BLE001 -- non-JSON error page, use the raw text
                pass
            raise RuntimeError(f"Twilio send failed ({resp.status_code}) to {to}: {detail}")
        return resp.json()

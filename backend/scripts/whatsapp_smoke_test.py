"""Send one WhatsApp message through the Twilio sandbox, outside the app.

Isolates the delivery channel from everything else. If this works, the
credentials, the sandbox join and the route to the handset are all good,
and any later failure is in the pipeline rather than in Twilio. If it
fails, the error names the reason (63015 means that number never sent
"join <code>" to the sandbox).

Uses the app's own Settings and client, so it exercises the same code path
a real visit would, not a parallel one that could drift.

    cd backend
    source .venv/bin/activate
    python3 scripts/whatsapp_smoke_test.py 9876543210
"""
import asyncio
import sys

sys.path.insert(0, ".")

from app.core.config import get_settings  # noqa: E402
from app.services.whatsapp_client import (  # noqa: E402
    TwilioWhatsAppClient,
    get_whatsapp_client,
)

MESSAGE = (
    "SevakAI test — नमस्ते। "
    "यह एक परीक्षण "
    "संदेश है।"
)


async def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python3 scripts/whatsapp_smoke_test.py <phone-number>")
        print("  e.g. 9876543210  (bare Indian numbers get +91 added)")
        raise SystemExit(2)

    to = sys.argv[1]
    settings = get_settings()

    print("--- config (values never printed) ---")
    print(f"  WHATSAPP_PROVIDER  : {settings.whatsapp_provider}")
    print(f"  sandbox sender     : {settings.twilio_whatsapp_from}")
    print(f"  TWILIO_ACCOUNT_SID : {len(settings.twilio_account_sid)} chars")
    print(f"  TWILIO_API_KEY_SID : {len(settings.twilio_api_key_sid)} chars")
    print(f"  API key secret     : {len(settings.twilio_api_key_secret)} chars")

    client = get_whatsapp_client(settings)
    print(f"  client             : {type(client).__name__}")
    if not isinstance(client, TwilioWhatsAppClient):
        print("\nNot using the sandbox. Set WHATSAPP_PROVIDER=twilio_sandbox in .env.")
        raise SystemExit(1)

    print(f"\nSending to {to} ...")
    try:
        result = await client.send_message(to, MESSAGE)
    except Exception as exc:  # noqa: BLE001 -- this is the diagnostic
        message = str(exc)
        print(f"\nFAILED: {message}")
        # Print only the hint that matches. An unconditional list reads as
        # a diagnosis and sends you chasing the wrong cause.
        hints = {
            "63015": "That number has not joined the sandbox. Send "
                     '"join <your-code>" to +1 415 523 8886 from its WhatsApp.',
            "21654": "WhatsApp only accepts free-form text inside the 24-hour "
                     "window that opens when the recipient last messaged you. "
                     "Outside it, Twilio demands an approved Content Template. "
                     'Re-send "join <your-code>" from that phone and retry '
                     "immediately -- that reopens the window.",
            "63016": "Outside the 24-hour messaging window -- same fix as "
                     'above: re-send "join <your-code>" and retry.',
            "20003": "Authentication failed: the API key SID or secret is "
                     "wrong, or the key was deleted in the Twilio Console.",
            "21608": "Unverified recipient on a trial account.",
        }
        for code, hint in hints.items():
            if code in message:
                print(f"\n{code}: {hint}")
                break
        raise SystemExit(1)

    print(f"  sid    : {result.get('sid')}")
    print(f"  status : {result.get('status')}")
    print("\n'queued' or 'sent' means Twilio accepted it -- check WhatsApp on that phone.")
    print("Twilio accepting a message is not the same as the handset receiving it.")


if __name__ == "__main__":
    asyncio.run(main())

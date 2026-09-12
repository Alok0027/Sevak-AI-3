"""Send one SMS through Twilio, outside the app -- the SMS twin of
whatsapp_smoke_test.py.

Worth having separately because the Messages log shows SMS from this
account already reaching an Indian number, while WhatsApp does not. If
that holds, SMS is the channel the demo can rely on today and WhatsApp is
the upgrade path.

    cd backend
    source .venv/bin/activate
    python3 scripts/sms_smoke_test.py 9876543210
"""
import asyncio
import sys

sys.path.insert(0, ".")

from app.core.config import get_settings  # noqa: E402
from app.services.sms_client import TwilioSmsClient, get_sms_client  # noqa: E402

MESSAGE = "SevakAI test — नमस्ते। यह एक परीक्षण संदेश है।"


async def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python3 scripts/sms_smoke_test.py <phone-number> [body]")
        print("  body defaults to real Hindi text (rejected on a trial account).")
        print("  Pass a trial template id to test the other path, e.g.:")
        print("    python3 scripts/sms_smoke_test.py 9876543210 sms_appointment_reminders")
        raise SystemExit(2)

    to = sys.argv[1]
    body = sys.argv[2] if len(sys.argv) > 2 else MESSAGE
    settings = get_settings()

    print("--- config (values never printed) ---")
    print(f"  SMS_PROVIDER        : {settings.sms_provider}")
    print(f"  TWILIO_PHONE_NUMBER : {settings.twilio_phone_number}")

    client = get_sms_client(settings)
    print(f"  client              : {type(client).__name__}")
    if not isinstance(client, TwilioSmsClient):
        print("\nNot the real client. Set SMS_PROVIDER=real in .env.")
        raise SystemExit(1)

    print(f"\nSending to {to}")
    print(f"  body: {body!r}")
    try:
        result = await client.send_message(to, body)
    except Exception as exc:  # noqa: BLE001 -- this is the diagnostic
        message = str(exc)
        print(f"\nFAILED: {message}")
        hints = {
            "572006": "Trial accounts cannot send custom text -- the Body "
                      "must be a template id such as sms_appointment_reminders. "
                      "Twilio then supplies its own fixed wording, so no patient "
                      "detail can appear in it. Custom text needs a paid account.",
            "21608": "Unverified recipient: a trial account can only text "
                     "numbers verified in Console -> Phone Numbers -> Verified Caller IDs.",
            "21606": "That From number can't send SMS -- check it's yours and SMS-capable.",
            "21610": "That recipient replied STOP and is unsubscribed.",
            "20003": "Authentication failed -- API key SID or secret is wrong.",
        }
        for code, hint in hints.items():
            if code in message:
                print(f"\n{code}: {hint}")
                break
        raise SystemExit(1)

    print(f"  sid    : {result.get('sid')}")
    print(f"  status : {result.get('status')}")
    print("\n'queued'/'sent' means Twilio accepted it. Check the handset to")
    print("confirm it actually arrived -- acceptance is not delivery.")


if __name__ == "__main__":
    asyncio.run(main())

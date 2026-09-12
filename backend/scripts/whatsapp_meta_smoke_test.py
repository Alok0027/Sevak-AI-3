"""Send one real WhatsApp message through Meta's Cloud API.

    cd backend && PYTHONPATH=. python scripts/whatsapp_meta_smoke_test.py 9876543210

Defaults to the `hello_world` template, which Meta pre-approves on every
new WhatsApp Business Account. That matters: it means you can prove the
whole path — token, phone number ID, allow-list, delivery — before your
own template has been through review, instead of discovering a
configuration problem and an approval delay at the same time.

    # your own template, once approved
    python scripts/whatsapp_meta_smoke_test.py 9876543210 \\
        --template followup_reminder --params "Meera Patil" "kal subah"

    # free-form text: only works if that number messaged you in the last
    # 24 hours. A patient never will, which is the point of templates.
    python scripts/whatsapp_meta_smoke_test.py 9876543210 --text "test"

The number is a positional argument, not a secret, so it is safe in shell
history. The token is read from .env and never printed.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from app.core.config import get_settings
from app.services.whatsapp_client import WhatsAppClient, WhatsAppError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phone", help="recipient, bare 10-digit Indian number or +country form")
    parser.add_argument("--template", default="hello_world")
    parser.add_argument("--params", nargs="*", default=None, help="{{1}}, {{2}}… in order")
    parser.add_argument("--language", default="en_US")
    parser.add_argument("--text", default=None, help="send free-form text instead of a template")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.whatsapp_api_token or not settings.whatsapp_phone_number_id:
        print("Set WHATSAPP_API_TOKEN and WHATSAPP_PHONE_NUMBER_ID in .env first.")
        print("Then check them with: python scripts/verify_whatsapp_token.py")
        return 1

    client = WhatsAppClient(settings)

    if args.text:
        print(f"Sending free-form text to {args.phone}…")
        coro = client.send_message(args.phone, args.text)
    else:
        shown = f" with {args.params}" if args.params else ""
        print(f"Sending template '{args.template}' ({args.language}) to {args.phone}{shown}…")
        coro = client.send_template(args.phone, args.template, args.params, args.language)

    try:
        result = asyncio.run(coro)
    except WhatsAppError as exc:
        print(f"\nFAILED: {exc}")
        return 1

    contact = (result.get("contacts") or [{}])[0]
    message = (result.get("messages") or [{}])[0]
    print("\nAccepted by Meta.")
    print(f"  wa_id      : {contact.get('wa_id', '—')}")
    print(f"  message id : {message.get('id', '—')}")
    print(
        "\nAccepted is not delivered. Meta returns 200 the moment it takes the\n"
        "message; whether it arrives is reported on the webhook, which this\n"
        "project does not run. Check the handset."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Check what a WhatsApp Cloud API token actually is, without ever
printing it.

Reads WHATSAPP_API_TOKEN and WHATSAPP_PHONE_NUMBER_ID from .env -- never
from a command-line argument, because arguments land in shell history and
in the process list where any other user on the machine can read them.
Everything it prints is redacted to the last four characters, so the
output is safe to paste into a chat or a screenshot.

    cd backend && PYTHONPATH=. python scripts/verify_whatsapp_token.py

Answers the three things that actually matter:

  * Which Meta app issued this, and is it still valid?
  * Does it expire, and when? (A 24-hour Graph Explorer token will work
    perfectly in testing and then die silently during a demo. This is the
    single most common way WhatsApp Cloud integrations fail.)
  * Does it carry whatsapp_business_messaging, and can it actually see
    the phone number ID configured next to it?
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

import httpx

from app.core.config import get_settings

GRAPH = "https://graph.facebook.com/v20.0"


def redact(secret: str) -> str:
    """Enough to tell two tokens apart, not enough to use one."""
    if not secret:
        return "(not set)"
    return f"…{secret[-4:]} ({len(secret)} chars)"


def stamp(unix_ts: int | None) -> str:
    if not unix_ts:
        # Meta reports a permanent System User token as expires_at 0.
        return "never (permanent token)"
    when = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    delta = when - datetime.now(timezone.utc)
    hours = delta.total_seconds() / 3600
    if hours < 0:
        return f"{when:%Y-%m-%d %H:%M UTC} — EXPIRED"
    if hours < 48:
        return f"{when:%Y-%m-%d %H:%M UTC} — in {hours:.0f}h  ⚠ short-lived"
    return f"{when:%Y-%m-%d %H:%M UTC} — in {hours / 24:.0f} days"


def main() -> int:
    settings = get_settings()
    token = (settings.whatsapp_api_token or "").strip()
    phone_id = (settings.whatsapp_phone_number_id or "").strip()

    print(f"WHATSAPP_API_TOKEN       {redact(token)}")
    print(f"WHATSAPP_PHONE_NUMBER_ID {phone_id or '(not set)'}\n")

    if not token:
        print("No token in .env. Add WHATSAPP_API_TOKEN=… and re-run.")
        return 1

    try:
        with httpx.Client(timeout=15) as client:
            # Self-inspection: a token may be used to debug itself.
            debug = client.get(
                f"https://graph.facebook.com/debug_token",
                params={"input_token": token, "access_token": token},
            )
            body = debug.json()

            if "error" in body:
                err = body["error"]
                print(f"REJECTED  {err.get('message', body)}")
                print("\nThe usual causes, in order of likelihood:")
                print("  1. The token was regenerated in the dashboard — copy the new one.")
                print("  2. It expired (Graph API Explorer tokens last ~1 hour).")
                print("  3. It was copied with a line break or a trailing space.")
                return 1

            data = body.get("data", {})
            print(f"Valid        {data.get('is_valid')}")
            print(f"App ID       {data.get('app_id')}")
            print(f"App name     {data.get('application')}")
            print(f"Type         {data.get('type')}")
            print(f"Expires      {stamp(data.get('expires_at'))}")

            scopes = data.get("scopes") or []
            print(f"Permissions  {', '.join(scopes) if scopes else '(none reported)'}")
            if "whatsapp_business_messaging" not in scopes:
                print("             ⚠ whatsapp_business_messaging is missing — "
                      "sending will 403 even though the token is valid.")

            if not phone_id:
                print("\nNo WHATSAPP_PHONE_NUMBER_ID set, so the number itself wasn't checked.")
                return 0

            # The token being valid says nothing about whether it can see
            # *this* number: a token for the wrong WABA fails here.
            num = client.get(f"{GRAPH}/{phone_id}", params={"access_token": token})
            nbody = num.json()
            if "error" in nbody:
                print(f"\nPhone number {phone_id}: {nbody['error'].get('message')}")
                print("The token is valid but cannot see that number — check the ID, "
                      "or that the token belongs to the same WhatsApp Business Account.")
                return 1

            print(f"\nPhone number {nbody.get('display_phone_number')} "
                  f"({nbody.get('verified_name', 'unverified')})")
            print(f"Quality      {nbody.get('quality_rating', 'n/a')}")
            print("\nReady to send.")
            return 0

    except httpx.HTTPError as exc:
        print(f"Could not reach Meta: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

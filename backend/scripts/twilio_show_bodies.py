"""Print recent Twilio messages with their FULL bodies.

The trial account refuses custom SMS text (572006) but has already
delivered at least one predefined template. The exact wording of what got
through is the only reliable specification available -- the docs decline
to list the templates -- so read it off the account rather than guess.

    python3 scripts/twilio_show_bodies.py
"""
import sys

import httpx

sys.path.insert(0, ".")

from app.core.config import get_settings  # noqa: E402

settings = get_settings()
resp = httpx.get(
    f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json",
    auth=(settings.twilio_api_key_sid, settings.twilio_api_key_secret),
    params={"PageSize": 20},
    timeout=30,
)
if resp.status_code >= 400:
    print(f"failed ({resp.status_code}): {resp.text[:300]}")
    raise SystemExit(1)

for m in resp.json().get("messages", []):
    channel = "WhatsApp" if "whatsapp" in (m.get("from") or "") else "SMS"
    direction = "IN " if "inbound" in (m.get("direction") or "") else "OUT"
    err = f"  error={m.get('error_code')}" if m.get("error_code") else ""
    print(f"--- {direction} {channel}  {m.get('status')}{err}  {m.get('date_sent')}")
    print(f"    {m.get('from')} -> {m.get('to')}")
    print(f"    body: {m.get('body')!r}")

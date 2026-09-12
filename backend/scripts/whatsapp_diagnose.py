"""Ask Twilio what it actually knows, instead of guessing from one error.

Three questions, because 21654 on a supposedly-open session window means
one of our assumptions is wrong and only the account can say which:

  1. Did the "join" message reach Twilio at all, and when? An inbound
     message from that number is the only proof the window ever opened;
     its timestamp says whether it is still open.
  2. What did our own send attempts do? Status and error code per message.
  3. What Content Templates does this account have? If free-form really
     is refused, these are what we would have to send instead.

    cd backend
    source .venv/bin/activate
    python3 scripts/whatsapp_diagnose.py
"""
import sys
from datetime import datetime, timezone

import httpx

sys.path.insert(0, ".")

from app.core.config import get_settings  # noqa: E402

settings = get_settings()
AUTH = (settings.twilio_api_key_sid, settings.twilio_api_key_secret)
BASE = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}"


def get(url: str, **params):
    resp = httpx.get(url, auth=AUTH, params=params, timeout=30)
    if resp.status_code >= 400:
        print(f"  request failed ({resp.status_code}): {resp.text[:300]}")
        return None
    return resp.json()


print("=== 1. account ===")
if account := get(f"{BASE}.json"):
    print(f"  status : {account.get('status')}")
    print(f"  type   : {account.get('type')}   (trial vs full)")

print("\n=== 2. recent messages (newest first) ===")
data = get(f"{BASE}/Messages.json", PageSize=20)
if data:
    messages = data.get("messages", [])
    if not messages:
        print("  none at all -- no join message ever reached this account")
    now = datetime.now(timezone.utc)
    for m in messages:
        direction = m.get("direction", "")
        arrow = "IN " if "inbound" in direction else "OUT"
        body = (m.get("body") or "").replace("\n", " ")[:45]
        err = f"  error={m.get('error_code')}" if m.get("error_code") else ""
        sent = m.get("date_sent") or m.get("date_created") or ""
        age = ""
        try:
            when = datetime.strptime(sent, "%a, %d %b %Y %H:%M:%S %z")
            hours = (now - when).total_seconds() / 3600
            age = f"  ({hours:.1f}h ago)"
        except Exception:
            pass
        print(f"  {arrow} {m.get('from','?'):24} -> {m.get('to','?'):24} {m.get('status','?'):11}{err}")
        print(f"      {sent}{age}  {body!r}")

print("\n=== 3. content templates on this account ===")
resp = httpx.get("https://content.twilio.com/v1/Content", auth=AUTH, timeout=30)
if resp.status_code >= 400:
    print(f"  request failed ({resp.status_code}): {resp.text[:300]}")
else:
    contents = resp.json().get("contents", [])
    if not contents:
        print("  none -- nothing to send with if free-form is refused")
    for c in contents:
        print(f"  {c.get('sid')}  {c.get('friendly_name')}  lang={c.get('language')}")
        for name in (c.get("types") or {}):
            print(f"      type: {name}")

print("\nThe inbound 'join' in section 2 is the thing to look for: if it is")
print("missing, the window never opened and 21654 is the honest answer.")

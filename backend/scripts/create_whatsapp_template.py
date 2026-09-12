"""Create (or inspect) the follow-up reminder template in Meta.

    cd backend && PYTHONPATH=. python scripts/create_whatsapp_template.py --list
    cd backend && PYTHONPATH=. python scripts/create_whatsapp_template.py

Doing this through the API rather than the dashboard form for one reason:
the three blanks have to be declared in the same order Agent 3 fills them
(name, risk, when), and a template whose blanks are in a different order
is approved perfectly happily and then puts the risk level where the name
should be. Declaring it from the same source of truth that sends it means
they cannot drift.

Category UTILITY, not MARKETING: this is a health follow-up a patient has
a reason to expect, and MARKETING templates are both rate-limited and
more likely to be rejected.

Approval is usually quick, but can take up to 24 hours if the business is
not verified -- so run this well before you need it, not the night before.
"""
from __future__ import annotations

import argparse
import sys

import httpx

from app.core.config import get_settings

GRAPH = "https://graph.facebook.com/v20.0"

# {{1}} patient name · {{2}} risk level in her language · {{3}} when.
# Agent 3 fills these in exactly this order (_deliver_whatsapp).
BODY_HI = (
    "नमस्ते {{1}} जी। आपकी हाल की जाँच में {{2}} पाया गया है। "
    "कृपया {{3}} अपनी आशा कार्यकर्ता से मिलें।"
)

# Meta requires a worked example for every variable before it will review
# a template. These are the strings Agent 3 actually produces.
EXAMPLE = [["मीरा पाटील", "उच्च जोखिम", "दो दिन के अंदर"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="show existing templates and their status")
    args = parser.parse_args()

    s = get_settings()
    if not s.whatsapp_api_token:
        print("WHATSAPP_API_TOKEN is empty. Set it in .env first (see README).")
        return 1
    if not s.whatsapp_business_account_id:
        print("WHATSAPP_BUSINESS_ACCOUNT_ID is empty. It is on the API Setup page,")
        print("labelled 'WhatsApp Business Account ID'. Not a secret.")
        return 1

    url = f"{GRAPH}/{s.whatsapp_business_account_id}/message_templates"
    auth = {"Authorization": f"Bearer {s.whatsapp_api_token}"}

    with httpx.Client(timeout=20) as client:
        if args.list:
            resp = client.get(url, headers=auth, params={"limit": 50})
            body = resp.json()
            if "error" in body:
                print(f"FAILED: {body['error'].get('message')}")
                return 1
            rows = body.get("data", [])
            if not rows:
                print("No templates on this account yet.")
                return 0
            print(f"{'NAME':30} {'LANG':6} {'CATEGORY':12} STATUS")
            for t in rows:
                print(f"{t.get('name', ''):30} {t.get('language', ''):6} "
                      f"{t.get('category', ''):12} {t.get('status', '')}")
            print("\nOnly APPROVED templates can be sent.")
            return 0

        payload = {
            "name": s.whatsapp_template_name,
            "language": s.whatsapp_template_language,
            "category": "UTILITY",
            "components": [
                {"type": "BODY", "text": BODY_HI, "example": {"body_text": EXAMPLE}}
            ],
        }
        print(f"Creating '{s.whatsapp_template_name}' ({s.whatsapp_template_language}, UTILITY)…")
        print(f"\n  {BODY_HI}\n")

        resp = client.post(url, headers=auth, json=payload)
        body = resp.json()
        if "error" in body:
            err = body["error"]
            print(f"FAILED [{err.get('code')}]: {err.get('error_user_msg') or err.get('message')}")
            if err.get("code") == 100 and "already exists" in str(err).lower():
                print("\nA template with this name and language already exists. "
                      "Run with --list to see its approval status.")
            return 1

        print(f"Submitted. id={body.get('id')}  status={body.get('status')}")
        print("\nIt cannot be sent until status is APPROVED. Check with:")
        print("  python scripts/create_whatsapp_template.py --list")
        return 0


if __name__ == "__main__":
    sys.exit(main())

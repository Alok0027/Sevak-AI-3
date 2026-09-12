#!/usr/bin/env bash
# Collect the Twilio credentials through native macOS dialogs and append
# them to backend/.env, so the secret never passes through shell history,
# terminal scrollback, or a chat window.
#
#   bash scripts/setup_twilio_env.sh
#
# Written as a script rather than a pasted one-liner because pasting a
# multi-line command that also switches shells races the new shell's
# startup -- the tail of the paste is swallowed and nothing runs.
set -euo pipefail

cd "$(dirname "$0")/.."

ask() {
  local prompt="$1" hidden="${2:-}"
  if [ "$hidden" = "hidden" ]; then
    osascript -e "text returned of (display dialog \"$prompt\" default answer \"\" with hidden answer)"
  else
    osascript -e "text returned of (display dialog \"$prompt\" default answer \"\")"
  fi
}

SID=$(ask "Twilio Account SID (starts with AC)")
KEYSID=$(ask "NEW API Key SID (starts with SK)")
SECRET=$(ask "NEW API Key Secret (shown only once, at creation)" hidden)

if [ -z "$SID" ] || [ -z "$KEYSID" ] || [ -z "$SECRET" ]; then
  echo "One of the values came back empty -- nothing written to .env." >&2
  exit 1
fi

# Warn rather than refuse: the shapes are stable enough to catch a paste
# slip (secret pasted into the SID box is the common one), but not worth
# blocking a legitimate value over.
case "$SID" in AC*) ;; *) echo "warning: Account SID usually starts with 'AC'." >&2 ;; esac
case "$KEYSID" in SK*) ;; *) echo "warning: API Key SID usually starts with 'SK'." >&2 ;; esac

{
  echo ""
  echo "# Twilio WhatsApp sandbox -- added by scripts/setup_twilio_env.sh"
  echo "WHATSAPP_PROVIDER=twilio_sandbox"
  echo "TWILIO_ACCOUNT_SID=$SID"
  echo "TWILIO_API_KEY_SID=$KEYSID"
  echo "TWILIO_API_KEY_SECRET=$SECRET"
} >> .env

echo "Wrote to .env (lengths only, values not shown):"
echo "  WHATSAPP_PROVIDER      = twilio_sandbox"
echo "  TWILIO_ACCOUNT_SID     ${#SID} chars"
echo "  TWILIO_API_KEY_SID     ${#KEYSID} chars"
echo "  TWILIO_API_KEY_SECRET  ${#SECRET} chars"

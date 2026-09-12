"""Generate a fresh AES-256 key for ENCRYPTION_KEY (NFR-SC1) and print it --
paste the output into backend/.env as ENCRYPTION_KEY=<value>.

Run this once per environment (each dev machine/deployment gets its own key
-- that's normal, not a bug). Losing this key after data has been encrypted
with it makes that data unrecoverable, so treat .env like a secret and back
it up before rotating keys.
"""
import base64
import os

if __name__ == "__main__":
    key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    print(key)

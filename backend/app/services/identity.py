"""Formal identifiers, and the normalisation that makes them mean anything.

Three problems this file exists to fix, all of them the same problem in
different clothes: the system had no way to say that two things are the
same thing.

1. A worker was a UUID. Correct for a database, useless on a referral slip
   or in a block meeting, where somebody has to read an identifier aloud.

2. A patient was a UUID too, and the real health system does not think in
   UUIDs -- it thinks in RCH numbers, which is what is written on the MCP
   card a mother carries in her own handbag.

3. "Wagholi", "wagholi" and " Wagholi " were three villages to the
   heatmap, because village was free text that nothing ever normalised.
"""
from __future__ import annotations

import hashlib
import hmac
import re

from app.core.config import get_settings

# ── Worker codes ────────────────────────────────────────────────────────
#
# ASHA-PUNE-01-007 reads aloud over a bad phone line, which is the only
# interface that matters when an ANM is trying to work out which of her
# workers filed a referral. A UUID does not.
#
# Shaped after the sub-centre ids already in use (SC-PUNE-01), because an
# identifier that looks unrelated to the one beside it on the same form is
# an identifier people transcribe wrongly.

_ROLE_PREFIX = {"asha": "ASHA", "anm": "ANM", "bmo": "BMO", "admin": "ADMIN"}


def _slug(value: str | None) -> str:
    """Upper-case, punctuation to hyphens, no runs, no edges."""
    if not value:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").upper()
    return re.sub(r"-{2,}", "-", cleaned)


def worker_code(role: str, sub_centre_id: str | None, serial: int) -> str:
    """A readable code for one member of staff.

    The serial is per (role, sub-centre), not global: ASHA-PUNE-01-007 is
    the seventh ASHA in that sub-centre, which is a fact somebody can
    check against a register. A global running number would be an
    identifier whose value depends on the order rows happened to be
    inserted, which tells nobody anything.

    A BMO and an admin cover a district rather than a sub-centre, so they
    get the short form -- BMO-001 -- rather than a made-up area.
    """
    prefix = _ROLE_PREFIX.get((role or "").lower(), "STAFF")
    # "SC-PUNE-01" -> "PUNE-01". The SC- says "sub-centre", which the code
    # already implies by position.
    area = _slug(sub_centre_id)
    if area.startswith("SC-"):
        area = area[3:]
    return f"{prefix}-{area}-{serial:03d}" if area else f"{prefix}-{serial:03d}"


# ── PHC name ────────────────────────────────────────────────────────────


def phc_name(sub_centre_id: str | None, default: str = "Primary Health Centre") -> str:
    """The Primary Health Centre a sub-centre's HIGH-risk referrals go to
    (FR-04.1).

    Derived from the sub-centre id with the same convention worker_code()
    above already uses ("SC-PUNE-01" -> "PUNE-01" -> "Pune"), because
    there is no facility registry in this schema yet (see the deployment
    section of the top-level README). SC-PUNE-01 -> "Pune PHC", which is
    also the name the SRS demo script (section 9) already uses for that
    exact sub-centre -- so this is recovering a fact the project already
    has, not inventing one.

    Falls back to `default` when there is no sub-centre to key off (a
    worker or patient with none set) rather than guessing.
    """
    area = _slug(sub_centre_id)
    if area.startswith("SC-"):
        area = area[3:]
    # "PUNE-01" -> "PUNE": the serial suffix tells you which sub-centre in
    # the area, not which facility -- several sub-centres in one area
    # share a PHC in a real deployment, and "Pune-01 PHC" would invent a
    # distinction the health system doesn't draw.
    area = re.sub(r"-\d+$", "", area)
    if not area:
        return default
    words = area.replace("-", " ").split()
    return f"{' '.join(w.capitalize() for w in words)} PHC"


# ── Villages ────────────────────────────────────────────────────────────


def village_code(name: str | None) -> str | None:
    """The canonical key for a village name.

    Case and spacing only. Deliberately NOT clever: "Wagholi" and
    "wagholi" are the same place and should collapse, but "Wagholi (Kh)"
    and "Wagholi (Bk)" are two real villages -- khurd and budruk, the
    smaller and larger of a pair, a naming convention across Maharashtra
    -- and an algorithm that tried to be helpful about brackets would
    silently merge two populations into one row on a district heatmap.

    Display keeps the name the ASHA typed. This is only ever the key.
    """
    if not name or not name.strip():
        return None
    return _slug(name)


# ── Blind index for the phone number ────────────────────────────────────
#
# Patient.phone is AES-GCM encrypted with a random nonce, so the same
# number never produces the same ciphertext twice and `WHERE phone = ?`
# can never match. That is the correct property for confidentiality and it
# is exactly why two ASHAs in neighbouring hamlets could both register the
# same pregnant woman and nothing would notice -- which is how duplicates
# get into HMIS in real life.
#
# A keyed hash gives equality back without giving plaintext back. It is
# deterministic, so an attacker holding the database *and* the key could
# confirm a guessed number -- but they could decrypt the column outright
# at that point, so it adds no exposure that was not already there.
#
# Keyed off the encryption key via HKDF-ish derivation rather than used
# directly, so the hash and the ciphertext are not produced from the same
# bytes.


def _index_key() -> bytes:
    settings = get_settings()
    if not settings.encryption_key:
        raise RuntimeError("ENCRYPTION_KEY is not set; cannot build a blind index")
    return hashlib.sha256(
        settings.encryption_key.encode() + b"|sevakai-phone-blind-index-v1"
    ).digest()


def normalise_phone(phone: str | None) -> str | None:
    """Digits only, and the last ten of them.

    An ASHA may type 9876543210, +91 98765 43210, or 09876543210 for the
    same woman. Comparing those as typed would mean the duplicate check
    finds nothing, which is worse than not having one -- it would look
    like it worked.
    """
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 10:
        return None
    return digits[-10:]


def phone_index(phone: str | None) -> str | None:
    """A lookup key for a phone number that is not the phone number."""
    normalised = normalise_phone(phone)
    if normalised is None:
        return None
    return hmac.new(_index_key(), normalised.encode(), hashlib.sha256).hexdigest()


# ── RCH number ──────────────────────────────────────────────────────────
#
# The identifier the real system uses for a pregnant woman or a child,
# issued on registration and printed on the Mother and Child Protection
# card she keeps herself. Twelve digits.
#
# Optional, and that is deliberate: an ASHA meeting a woman at her door
# before she has been registered at the sub-centre has no RCH number to
# type, and refusing to record the visit until she does would push the
# work back onto paper -- the exact failure this product exists to remove.

RCH_LENGTH = 12


class InvalidRchNumber(ValueError):
    pass


def normalise_rch(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) != RCH_LENGTH:
        raise InvalidRchNumber(f"An RCH number is {RCH_LENGTH} digits")
    return digits

"""Spoken Hindi numbers -> integers.

Bhashini's ASR writes numbers the way they are said, not as digits: an
ASHA saying "उम्र बत्तीस साल" gets back the *word* बत्तीस, and a phone
number comes back as ten separate digit words ("एक दो तीन चार..."), never
as 1234567890. Every extraction pattern in this codebase was written
against digits, so without this module they all silently miss on real
speech.

Hindi number names below 100 are irregular (there's no "twenty-two"
pattern -- 22 is बाईस, 32 is बत्तीस, 42 is बयालीस), so this is a lookup
table rather than a composition rule. Common spelling variants are
included as extra keys because ASR output is not consistent about
nukta/anusvara (पांच vs पाँच, छह vs छः).
"""
import re

_UNITS = {
    "शून्य": 0, "जीरो": 0,
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 5, "पांच": 5,
    "छह": 6, "छः": 6, "छ": 6, "सात": 7, "आठ": 8, "नौ": 9,
}

_TEENS_AND_TENS = {
    "दस": 10, "ग्यारह": 11, "बारह": 12, "तेरह": 13, "चौदह": 14,
    "पंद्रह": 15, "पन्द्रह": 15, "सोलह": 16, "सत्रह": 17, "अठारह": 18,
    "उन्नीस": 19, "बीस": 20,
    "इक्कीस": 21, "बाईस": 22, "तेईस": 23, "चौबीस": 24, "पच्चीस": 25,
    "छब्बीस": 26, "सत्ताईस": 27, "अट्ठाईस": 28, "अठाईस": 28, "उनतीस": 29, "तीस": 30,
    "इकतीस": 31, "बत्तीस": 32, "तैंतीस": 33, "चौंतीस": 34, "पैंतीस": 35,
    "छत्तीस": 36, "सैंतीस": 37, "अड़तीस": 38, "उनतालीस": 39, "चालीस": 40,
    "इकतालीस": 41, "बयालीस": 42, "तैंतालीस": 43, "चौवालीस": 44, "पैंतालीस": 45,
    "छियालीस": 46, "सैंतालीस": 47, "अड़तालीस": 48, "उनचास": 49, "पचास": 50,
    "इक्यावन": 51, "बावन": 52, "तिरेपन": 53, "तिरपन": 53, "चौवन": 54, "पचपन": 55,
    "छप्पन": 56, "सत्तावन": 57, "अट्ठावन": 58, "उनसठ": 59, "साठ": 60,
    "इकसठ": 61, "बासठ": 62, "तिरसठ": 63, "चौंसठ": 64, "पैंसठ": 65,
    "छियासठ": 66, "सड़सठ": 67, "अड़सठ": 68, "उनहत्तर": 69, "सत्तर": 70,
    "इकहत्तर": 71, "बहत्तर": 72, "तिहत्तर": 73, "चौहत्तर": 74, "पचहत्तर": 75,
    "छिहत्तर": 76, "सतहत्तर": 77, "अठहत्तर": 78, "उनासी": 79, "अस्सी": 80,
    "इक्यासी": 81, "बयासी": 82, "तिरासी": 83, "चौरासी": 84, "पचासी": 85,
    "छियासी": 86, "सतासी": 87, "अठासी": 88, "नवासी": 89, "नब्बे": 90,
    "इक्यानवे": 91, "बानवे": 92, "तिरानवे": 93, "चौरानवे": 94, "पचानवे": 95,
    "छियानवे": 96, "सत्तानवे": 97, "अट्ठानवे": 98, "निन्यानवे": 99, "सौ": 100,
    # ASR spelling variants seen in real Bhashini output. Cheap to accept,
    # and a missing one doesn't merely lose the number -- it lets the
    # surrounding pattern backtrack into a different, wrong reading.
    "पंचानवे": 95, "पंचानबे": 95, "इक्यानबे": 91, "नब्बै": 90,
    "पन्द्रह": 15, "अठ्ठाईस": 28, "उन्तीस": 29, "इक्कावन": 51,
    "पिचहत्तर": 75, "सतहतर": 77, "पैतीस": 35, "पैतालीस": 45,
}

WORD_TO_NUMBER: dict[str, int] = {**_UNITS, **_TEENS_AND_TENS}

# Longest-first so "छब्बीस" is never matched as "छ" followed by junk.
NUMBER_WORD_PATTERN = "|".join(sorted(WORD_TO_NUMBER, key=len, reverse=True))

_DIGIT_WORD_RE = re.compile(rf"(?:{'|'.join(sorted(_UNITS, key=len, reverse=True))})")
_TOKEN_RE = re.compile(r"[^\s,.।]+")


def word_to_int(word: str) -> int | None:
    """A single spoken Hindi number word as an integer, or None."""
    return WORD_TO_NUMBER.get(word.strip(" ,.।"))


def parse_number(token: str) -> int | None:
    """Either a digit form ("32", "३२") or a spoken word ("बत्तीस")."""
    token = token.strip(" ,.।")
    if not token:
        return None
    try:
        return int(token)  # int() already understands Devanagari digits
    except ValueError:
        return word_to_int(token)


_UNIT_WORD_PATTERN = "|".join(sorted(_UNITS, key=len, reverse=True))
# Readings above 100 are said as compounds -- "एक सौ चालीस" (one hundred
# forty) for 140. Matched before the bare-word alternative so the phrase
# is read whole; matching just "एक" there would turn a BP of 140 into 1.
SPOKEN_NUMBER_PATTERN = (
    rf"(?:(?:{_UNIT_WORD_PATTERN})\s+)?सौ(?:\s+(?:{NUMBER_WORD_PATTERN}))?"
    rf"|{NUMBER_WORD_PATTERN}"
    rf"|\d{{1,3}}"
)


def parse_spoken_number(text: str) -> int | None:
    """A number written as digits, one word, or a "X सौ Y" compound."""
    text = text.strip(" ,.।")
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        pass

    tokens = text.split()
    if "सौ" in tokens:
        at = tokens.index("सौ")
        before, after = tokens[:at], tokens[at + 1:]
        hundreds = WORD_TO_NUMBER.get(before[-1], 1) if before else 1
        remainder = WORD_TO_NUMBER.get(after[0], 0) if after else 0
        return hundreds * 100 + remainder
    return word_to_int(text)


def spoken_digits_to_phone(text: str, length: int = 10) -> str | None:
    """A phone number dictated digit by digit ("एक दो तीन ...") as a string.

    Only returns a value when a run of exactly `length` consecutive digit
    words is found, so a stray "दो" elsewhere in the sentence can never be
    mistaken for part of a number. Digits already written as digits are
    handled by the caller's own numeric pattern.
    """
    run: list[str] = []
    for token in _TOKEN_RE.findall(text):
        if token in _UNITS:
            run.append(str(_UNITS[token]))
            if len(run) == length:
                return "".join(run)
        else:
            run = []
    return None

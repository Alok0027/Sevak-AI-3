"""
Agent 1 -- Voice Comprehension & Entity Extraction (FR-02).

Takes the Bhashini transcript and pulls out: patient identity, clinical
vitals, medication compliance, and social risk factors, then emits the
structured JSON record FR-02.5 requires.

The extractor below is a deterministic, regex-based parser tuned to the
Hinglish phrasing used in the SRS's own demo script (section 9.1) and
common ASHA-worker speech patterns ("28 saal", "BP 140 over 90", "iron
tablets nahi li", "pati bahar gaya hua hai"). It runs with zero external
calls, which is what makes `USE_MOCKS=true` fully offline.

`extract_with_llm()` is what the pipeline actually calls (see graph.py).
LLM_PROVIDER=real sends the transcript to the real LLM with a clinical NER
prompt in JSON mode; LLM_PROVIDER=mock (default) and any real-call failure
(timeout, bad JSON, unexpected shape) both fall back to this same regex
`extract()` -- same fallback discipline Agent 3 uses, and required by
FR-01.3 / NFR-P1 (the pipeline must not silently hang or fail a visit just
because a model call stalled or misbehaved).
"""
import json
import re

from app.schemas.visit import ExtractedFields
from app.services.hindi_numbers import NUMBER_WORD_PATTERN, parse_number
from app.services.llm_client import LLMClientBase, MockLLMClient
from app.services.vitals_parsing import find_blood_sugar, find_bp

# Bhashini's real Hindi ASR returns Devanagari ("बीपी 140 बटा 90, बुखार 101,
# आयरन की गोली नहीं ली"), while the mock/demo transcripts are romanized
# Hinglish. Both reach this parser, so every clinical keyword accepts
# either script -- otherwise a real spoken visit extracts nothing and the
# risk score below is computed from an empty record, which reads as a
# healthy patient rather than an unassessed one.
_AGE_UNIT = (
    r"saal|years?|yrs?|साल|बरस|वर्ष"
    r"|বছর|বয়স"          # Bengali: bochor (year), boyosh (age)
    r"|வயது|ஆண்டு|வருடம்"  # Tamil: vayathu (age), aandu/varudam (year)
    r"|సంవత్సరం|ఏళ్ళు|ఏళ్లు|వయసు"  # Telugu: samvatsaram/ellu (year), vayasu (age)
)
# Devanagari letters and matras only -- the full "ऀ-ॿ" block also contains
# the danda (U+0964) and the Devanagari digits, so a name built on it runs
# straight through sentence breaks and ages.
#
# Bengali, Tamil and Telugu are included on the same terms: consonant and
# vowel ranges plus their matras, and deliberately NOT each script's digit
# block (\u09E6-\u09EF, \u0BE6-\u0BEF, \u0C66-\u0C6F), for exactly the
# reason the Devanagari comment above gives. The app offers these three
# languages in its UI, so a transcript can arrive in any of them.
_LETTER = (
    r"A-Za-z"
    r"ऀ-ॣॱ-ॿ"                      # Devanagari (Hindi, Marathi)
    r"\u0985-\u09B9\u09BE-\u09CC\u09CE\u09DC-\u09DF"   # Bengali
    r"\u0B85-\u0BB9\u0BBE-\u0BCD"                        # Tamil
    r"\u0C05-\u0C39\u0C3E-\u0C4D"                        # Telugu
)

# Ages and gestational ages are routinely spoken as words rather than
# digits ("बत्तीस साल", "छ महीना"), and gestational age drives the
# pregnancy risk rules, so both accept either form via the shared table.
_NUMBER = rf"\d{{1,3}}|{NUMBER_WORD_PATTERN}"
_NAME_AGE_RE = re.compile(
    rf"([{_LETTER}][{_LETTER} .]*?),?\s*({_NUMBER})\s*(?:{_AGE_UNIT})", re.IGNORECASE
)
_MONTH_WORD = (
    r"mahine|mahina|month|महीने|महीना|माह"
    r"|মাস"        # Bengali: mash
    r"|மாதம்"      # Tamil: maadham
    r"|నెల|నెలల"    # Telugu: nela
)
_PREGNANCY_RE = re.compile(rf"({_NUMBER})\s*(?:{_MONTH_WORD})s?", re.IGNORECASE)

# Violence and injury. Deliberately its own category rather than another
# social risk factor: those adjust the score, this escalates the visit.
# Biased towards catching it -- a false positive costs the ASHA one tap to
# override, while a miss silently files a reported assault as routine.
_VIOLENCE_RULES = [
    (
        re.compile(
            r"मारपीट|लात\s*मार|पीट[ाी]|मारा|हिंसा|घरेलू\s*हिंसा|गला\s*दबा"
            r"|beat(?:en|ing)?\b|assault|domestic\s*violence|hit\s+her",
            re.IGNORECASE,
        ),
        "physical violence",
    ),
    (
        re.compile(
            r"चोट|फूट\s*गई|टूट\s*गय[ाी]|फट\s*गय[ाी]|फ्रैक्चर|खून\s*बह|घाव|जल\s*गई"
            r"|fracture|bleeding|wound|injur(?:y|ed)|burn(?:t|ed)",
            re.IGNORECASE,
        ),
        "injury reported",
    ),
]
_TEMP_RE = re.compile(
    r"(?:temperature|bukhar|fever|बुखार|तापमान|জ্বর|காய்ச்சல்|జ్వరం)\D{0,12}(\d{2,3}(?:\.\d)?)", re.IGNORECASE
)
# "101 डिग्री बुखार" puts the number before the word, which _TEMP_RE can't see.
_TEMP_BEFORE_RE = re.compile(r"(\d{2,3}(?:\.\d)?)\s*(?:degrees?|डिग्री)", re.IGNORECASE)
_WEIGHT_RE = re.compile(r"(\d{2,3}(?:\.\d)?)\s*(?:kg|kilo|किलो|के\.?\s?जी\.?|কেজি|கிலோ|కిలో)", re.IGNORECASE)
_DURATION_RE = re.compile(
    r"(pichle|last|पिछले|पिछला)\s*(\d+)\s*(hafte|din|week|day|हफ्ते|हफ्ता|दिन)s?", re.IGNORECASE
)

_MED_KEYWORDS = [
    "iron tablet", "tablet", "medicine", "dawai", "dawaai",
    "आयरन", "गोली", "गोलियां", "दवा", "दवाई", "टैबलेट",
    # Bengali: tabletting/oshudh/bori (tablet, medicine, pill)
    "ট্যাবলেট", "ওষুধ", "বড়ি", "আয়রন",
    # Tamil: maathirai (tablet), marundhu (medicine), irumbu (iron)
    "மாத்திரை", "மருந்து", "இரும்பு",
    # Telugu: maatra (tablet), mandu (medicine), inumu (iron)
    "మాత్ర", "మందు", "ఇనుము",
]
_NON_COMPLIANCE_MARKERS = [
    "nahi li", "nahi liya", "not taken", "skipped", "missed",
    "नहीं ली", "नहीं लिया", "नहीं खाई", "नहीं लेती", "नहीं ले",
    # Bengali: khayni / neyni / khaccche na (has not eaten/taken it)
    "খায়নি", "নেয়নি", "খাচ্ছে না", "নেননি",
    # Tamil: edukkavillai / saappidavillai (did not take / did not eat)
    "எடுக்கவில்லை", "சாப்பிடவில்லை", "போடவில்லை",
    # Telugu: teesukoledu / vesukoledu (did not take)
    "తీసుకోలేదు", "వేసుకోలేదు", "తినలేదు",
]

_SOCIAL_RISK_RULES = [
    (
        re.compile(r"pati\s+bahar|husband\s+(is\s+)?(away|absent)|पति\s+बाहर|पति\s+नहीं"
                   r"|স্বামী\s*(বাইরে|নেই)|கணவர்\s*(வெளியே|இல்லை)|భర్త\s*(బయట|లేడు)", re.IGNORECASE),
        "absent spouse",
    ),
    (
        re.compile(r"akel[ai]|isolated|alone at home|अकेली|अकेला"
                   r"|একা|তনিযা|தனியாக|தனியே|ఒంటరిగా|ఒక్కతే", re.IGNORECASE),
        "household isolation",
    ),
    (
        re.compile(r"paisa\s*nahi|no money|can'?t afford|gareeb|पैसा\s*नहीं|पैसे\s*नहीं|गरीब"
                   r"|টাকা\s*নেই|গরিব|பணம்\s*இல்லை|ஏழை|డబ్బు\s*లేదు|పేద", re.IGNORECASE),
        "economic stress",
    ),
]


# nhm_corpus/antenatal_care.md, "Danger signs in pregnancy requiring
# immediate referral". Matched here rather than left to the classifier,
# because the classifier only ever sees extracted fields -- and until this
# existed, these words never became one.
#
# Hindi and Devanagari alongside English throughout: the ASHA dictates in
# her own language, and an English-only pattern would catch the danger
# sign only for the workers least likely to need the help.
_DANGER_SIGN_RULES = [
    (
        re.compile(r"severe\s+headache|tez\s+(sir\s*)?dard|sir\s+(mein\s+)?dard|"
                   r"মাথা\s*ব্যথা|মাথা\s*যন্ত্রণা|தலைவலி|తలనొప్పి|"
                   r"सिर\s*(में)?\s*(तेज़?\s*)?दर्द", re.IGNORECASE),
        "Severe headache, with or without blurred vision",
    ),
    (
        re.compile(r"blurr?(ed|y)\s+vision|dhundla|dikhai\s+nahi|धुंधला|दिखाई\s*नहीं|"
                   r"ঝাপসা|চোখে\s*দেখ|மங்கலா|கண்\s*மங்|మసక|కళ్లు\s*మసక",
                   re.IGNORECASE),
        "Blurred vision",
    ),
    (
        re.compile(r"convuls|seizure|fits?\b|unconscious|behosh|daura|दौरा|बेहोश|"
                   r"খিঁচুনি|অজ্ঞান|வலிப்பு|மயக்கம்|మూర్ఛ|స్పృహ\s*కోల్పో",
                   re.IGNORECASE),
        "Convulsions or loss of consciousness",
    ),
    (
        re.compile(r"bleeding|blood\s+loss|khoon\s*(aa|beh)|रक्तस्राव|खून\s*आ|"
                   r"রক্তপাত|রক্ত\s*যাচ্ছে|ரத்தப்போக்கு|இரத்தப்\s*போக்கு|రక్తస్రావం|రక్తం\s*పోతు",
                   re.IGNORECASE),
        "Bleeding during pregnancy",
    ),
    (
        re.compile(r"severe\s+abdominal\s+pain|continuous\s+abdominal|pet\s+(mein\s+)?tez\s+dard|"
                   r"পেটে\s*ব্যথা|வயிற்று\s*வலி|కడుపు\s*నొప్పి|"
                   r"पेट\s*(में)?\s*तेज़?\s*दर्द", re.IGNORECASE),
        "Continuous severe abdominal pain",
    ),
    (
        re.compile(r"water\s+broke|rupture[d]?\s+membrane|leaking\s+(water|fluid)|"
                   r"पानी\s*(की\s*)?थैली", re.IGNORECASE),
        "Rupture of membranes",
    ),
    (
        re.compile(r"preterm|premature\s+labou?r|early\s+labou?r|समय\s*से\s*पहले",
                   re.IGNORECASE),
        "Preterm labour",
    ),
]


def extract(transcript: str) -> ExtractedFields:
    fields = ExtractedFields()
    confidence: dict[str, float] = {}

    if m := _NAME_AGE_RE.search(transcript):
        fields.patient_name = m.group(1).strip().rstrip(",।").strip()
        fields.age = parse_number(m.group(2))
        confidence["patient_name"] = 0.9
        confidence["age"] = 0.95

    if m := _PREGNANCY_RE.search(transcript):
        if (months := parse_number(m.group(1))) is not None:
            fields.pregnancy_stage = f"{months} months"
            confidence["pregnancy_stage"] = 0.9

    if bp := find_bp(transcript):
        fields.bp_systolic, fields.bp_diastolic = bp
        confidence["bp_systolic"] = 0.95
        confidence["bp_diastolic"] = 0.95

    fasting, random_sugar = find_blood_sugar(transcript)
    if fasting is not None:
        fields.blood_sugar_fasting = fasting
        confidence["blood_sugar_fasting"] = 0.85
    if random_sugar is not None:
        fields.blood_sugar_random = random_sugar
        confidence["blood_sugar_random"] = 0.85

    if m := (_TEMP_RE.search(transcript) or _TEMP_BEFORE_RE.search(transcript)):
        fields.temperature_c = float(m.group(1))
        confidence["temperature_c"] = 0.85

    if m := _WEIGHT_RE.search(transcript):
        fields.weight_kg = float(m.group(1))
        confidence["weight_kg"] = 0.85

    lowered = transcript.lower()
    mentioned_med = next((kw for kw in _MED_KEYWORDS if kw in lowered), None)
    if mentioned_med:
        non_compliant = any(marker in lowered for marker in _NON_COMPLIANCE_MARKERS)
        fields.medication_compliance = "non_compliant" if non_compliant else "compliant"
        duration = ""
        if d := _DURATION_RE.search(transcript):
            duration = f" for {d.group(2)} {d.group(3)}"
        fields.medication_compliance_detail = f"{mentioned_med}{duration}".strip()
        confidence["medication_compliance"] = 0.85
    else:
        fields.medication_compliance = "unknown"

    social_risks = []
    for pattern, label in _SOCIAL_RISK_RULES:
        if pattern.search(transcript):
            social_risks.append(label)
    fields.social_risk_factors = social_risks
    if social_risks:
        confidence["social_risk_factors"] = 0.8

    violence = [label for pattern, label in _VIOLENCE_RULES if pattern.search(transcript)]
    fields.violence_or_injury = violence
    if violence:
        confidence["violence_or_injury"] = 0.75

    danger = [label for pattern, label in _DANGER_SIGN_RULES if pattern.search(transcript)]
    fields.danger_signs = danger
    if danger:
        # Lower than the vitals, higher than nothing. A keyword match on
        # dictated speech will occasionally fire on "no headache", and the
        # review screen is where the ASHA corrects that. Erring towards a
        # needless referral is the right direction to err in.
        confidence["danger_signs"] = 0.7

    fields.confidence_scores = confidence
    return fields


_NER_SYSTEM_PROMPT = (
    "You are a clinical NER system extracting structured data from an ASHA "
    "(Indian community health worker)'s spoken home-visit observation, "
    "transcribed from Hindi/Hinglish. Extract only facts actually stated -- "
    "never infer or guess a value that isn't in the text. "
    "Respond with ONLY a raw JSON object (no markdown fences, no commentary) "
    "with exactly these keys, using null for anything not mentioned: "
    "patient_name (string), age (integer), pregnancy_stage (string, e.g. "
    "'7 months'), bp_systolic (integer), bp_diastolic (integer), "
    "weight_kg (number), temperature_c (number), "
    "medication_compliance (one of \"compliant\", \"non_compliant\", \"unknown\"), "
    "medication_compliance_detail (short string), "
    "blood_sugar_fasting (integer, mg/dL, only if stated as a fasting or "
    "empty-stomach reading), blood_sugar_random (integer, mg/dL, any other "
    "blood sugar reading), "
    "social_risk_factors (array of short strings, e.g. \"absent spouse\", "
    "\"household isolation\", \"economic stress\"), "
    "violence_or_injury (array; include \"physical violence\" if any "
    "assault, beating or domestic violence is described, and \"injury "
    "reported\" if any wound, fracture, burn or bleeding is described)."
)


async def extract_with_llm(transcript: str, llm_client: LLMClientBase) -> ExtractedFields:
    """FR-02.5 entry point used by the pipeline. Mock client -> identical
    regex-based `extract()` output (keeps the demo deterministic and
    offline). Real client -> LLM clinical NER, falling back to `extract()`
    on any failure to parse/validate its response."""
    if isinstance(llm_client, MockLLMClient):
        return extract(transcript)

    try:
        raw = await llm_client.complete(_NER_SYSTEM_PROMPT, transcript)
        data = json.loads(raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
        return ExtractedFields.model_validate(data)
    except Exception:  # noqa: BLE001 -- any bad/malformed LLM response falls back, never breaks the visit
        return extract(transcript)

# SevakAI — Evidence Register

Every quantitative claim SevakAI makes, with the method that produced it,
the date it was measured, and the raw output. A reviewer should be able
to check any number here without asking us a question.

**This document also records what has *not* been measured.** A claim with
no evidence is listed as such rather than left out, because the gap
itself is the honest answer to "does this actually work".

Last updated: 19 September 2026

---

## 1. Impact and ROI claims

### 1.1 Status: two headline figures do not survive checking

The evaluation table in the SRS claims:

> 10 lakh workers. **₹1,964 Cr net saving. 14,000 maternal lives per
> year.** NHM alignment.

Neither money figure carries a citation anywhere in the document. We
checked both against published national data.

#### "14,000 maternal lives per year" — **withdraw this number**

India's maternal mortality ratio is **88 per 100,000 live births**
(SRS Special Bulletin on Maternal Mortality 2021–23), which works out to
roughly **22,500 maternal deaths nationally per year**.

A claim of 14,000 lives saved per year is therefore a claim to prevent
**62% of all maternal deaths in India**. No health intervention in the
world does this, and a documentation tool certainly does not. A reviewer
who knows the MMR figure — and a Deloitte health-sector judge will —
will spot this immediately, and it will cast doubt on the figures that
*are* real.

**Recommendation:** remove it. Replace with a mechanism claim, not an
outcome claim (see 1.2).

#### "₹1,964 Cr net saving" — **no published basis found**

We could not find any NHM, MoHFW or published source for this figure.

Reverse-engineering it: ₹1,964 Cr ÷ 10,00,000 ASHAs = **₹19,640 per ASHA
per year**. At a ₹10,000/month honorarium that is about **16% of her
annual honorarium** — i.e. the figure is consistent with "SevakAI returns
roughly a sixth of an ASHA's working time, valued at her honorarium
rate".

If that *is* the derivation, it can be defended — but only by showing the
arithmetic and labelling every assumption. If it is not, the number
should go.

Two further cautions on that derivation:

- NHM classifies ASHAs as **volunteers on task-based incentives**, not
  salaried staff. Valuing their time at an hourly wage is contestable,
  and a reviewer may challenge it.
- The "16% of time" input is currently an assumption, not a measurement.
  See 1.3.

### 1.2 What we *can* defend, with sources

| Claim | Figure | Source |
|---|---|---|
| ASHA workforce size | ~10 lakh (9.2 lakh rural + 79,900 urban, 2022–23) | MoHFW / NHM figures as reported by [Drishti IAS](https://www.drishtiias.com/daily-updates/daily-news-analysis/asha-workers-in-india); [PIB/News on AIR](https://www.newsonair.gov.in/govt-says-10-lakh-asha-workers-playing-significant-role-in-improving-child-health-in-country/) |
| India's MMR | 88 per 100,000 live births (2021–23) | [SRS Special Bulletin on Maternal Mortality 2021–23](https://www.dataforindia.com/maternal-mortality/) |
| Maternal deaths per year | ~22,500 | Derived from the SRS MMR above |
| ASHA honorarium | ₹5,000–15,000/month, varies by state, often delayed | [Drishti IAS](https://www.drishtiias.com/daily-updates/daily-news-analysis/asha-workers-in-india) |
| Documentation is a major time cost for ASHAs | Qualitative, not quantified — see caution below | [Time-motion study, MJAFI 2023](https://pubmed.ncbi.nlm.nih.gov/38144633/) |

**Caution on the last row.** The time-motion study (17 ASHAs, two PHCs in
central India, observed over four months, published *Medical Journal
Armed Forces India* Vol 79 Supp 1, 2023) concludes that ASHAs work seven
days a week and that *"most of the time is being spent on supporting
tasks such as traveling, documentation, and record maintenance"*, with
register maintenance among the top three time consumers. It supports the
existence of the burden. **It does not publish a percentage**, so we
cannot cite a number from it. Anyone claiming "ASHAs spend X% of their
time on paperwork" needs a different source or their own measurement.

### 1.3 Recommended replacement framing

State the mechanism and the arithmetic, and let the reviewer supply their
own judgement on the assumption:

> SevakAI removes the post-visit write-up from an ASHA's day. NHM records
> ~10 lakh ASHAs nationally. **If** documentation costs each worker 30
> minutes a day — an assumption, not a measurement — and SevakAI removes
> two-thirds of it, that is 20 minutes per worker per day. Across 10 lakh
> workers and 365 days, that is 10,00,000 × 20 ÷ 60 × 365 ≈ **12.17 crore
> hours a year returned to home visits** across the workforce.

This is honest: one clearly-labelled assumption, arithmetic anyone can
redo, and no claim about lives saved. It is also stronger in a viva,
because the assumption is the thing you invite the judge to argue with —
rather than the number itself.

For the clinical side, claim the mechanism rather than the outcome:

> Every HIGH-risk case gets a 48-hour follow-up deadline set
> automatically (NHM protocol), and any case that passes it escalates to
> the ANM and BMO without anyone having to notice. Today that depends on
> an ASHA remembering, and a supervisor reading a paper register.

**Open action:** decide with the mentor whether to (a) show the ₹1,964 Cr
arithmetic with assumptions exposed, or (b) drop the rupee figure and
lead with hours returned. Either is defensible. The current
uncited-number-in-a-table is not.

---

## 2. Speech recognition accuracy

**Status: running on real Bhashini. Accuracy NOT MEASURED.**

Keep those two apart — they are different claims and only one of them is
in trouble.

**The integration is real.** `backend/.env` sets `STT_PROVIDER=bhashini`
with a populated `BHASHINI_API_KEY`, `BHASHINI_USER_ID` and
`BHASHINI_PIPELINE_ID` against `https://meity-auth.ulcacontrib.org`. The
client performs the genuine two-step ULCA flow — `getModelsPipeline` to
obtain the ASR `serviceId` and a per-call inference key, then the
returned `callbackUrl` for the transcript. Two other providers exist
behind the same interface and are selected by one environment variable:
local Whisper (`faster-whisper`, no network once weights are cached) and
a deterministic mock used by the test suite.

An earlier revision of this document said the system "defaults to mock".
That was read off a stale copy of `.env` and was wrong about the
deployment. `"mock"` is the *code* default in `config.py`, for tests; the
configured provider is Bhashini.

**The accuracy figure is what does not exist.** No word error rate has
been computed against any reference transcript, on any provider. The
SRS's ≥85% is a **target, not a result**, and must be labelled that way
until a measurement replaces it.

To close it: 20–30 clips from several speakers — different accents, some
with background noise, ideally some recorded on a low-end handset rather
than a laptop — each with a human reference transcript, and WER computed
against them. This is the single longest-lead item in this document,
because it needs people, not code.

---

## 3. Latency

**Status: instrument built, real-provider run outstanding.**

`backend/scripts/measure_latency.py` times each pipeline stage over N
runs and reports p50/p95/min/max. It times the agent graph directly
(no database involved -- the graph reads its state dict and writes nothing).

It **refuses to issue a pass/fail verdict when any provider is mocked**,
and prints `NOT A VALID MEASUREMENT` instead. An earlier version happily
reported `p95 = 0.00s (PASS)` against a mock STT and a mock LLM — a real
number for the speed of a base64 decode, and worthless. That figure is
exactly the kind that walks into a slide.

A real STT provider is handed the clip as audio, so the script
**requires `--audio`** when one is configured, and refuses to run
without it. The default payload is base64 of Hindi text — the mock
decodes it straight back, and a real provider cannot, so a timing taken
that way would be the speed of an error rather than a latency.

To produce the number for the deck:

```bash
cd backend
source .venv/bin/activate
python -m scripts.measure_latency --runs 30 --audio path/to/clip.m4a
```

Use a clip of roughly 60 seconds, because NFR-P2 is written about a 60s
clip. `.env` already selects Bhashini and a real LLM, so no overrides are
needed.

NFR-P1 ("<30s end-to-end") and NFR-P2 ("<5s for a 60s clip") remain
**targets** until that output is pasted here.

---

## 4. Load and concurrency

**Status: instrument built, run outstanding.**

`backend/scripts/measure_load.py` fires concurrent requests at a deployed
instance and reports p50/p95/p99, throughput and an error breakdown by
status code. It measures the free-tier cold start separately rather than
letting it poison the sample, and it prints the **error rate before any
timing** — a run where half the requests 502 and the rest return in 80ms
has a beautiful p50 and is a failure.

```bash
cd backend
python -m scripts.measure_load --concurrency 50 --requests 200
```

Must run from a machine that can reach the deployment. Note in advance
that Render's free tier is expected to be the limiting factor; that is
itself an honest finding and should be reported, not hidden.

---

## 5. Risk classification conformance

**Status: MEASURED. 20 of 20 (100%) — after fixing a safety bug the eval
found.**

`backend/tests/test_risk_conformance.py`. Every case carries the sentence
from `backend/nhm_corpus` that decides its expected label.

```
  SevakAI risk engine — NHM threshold conformance
  20 of 20 cases classified as the NHM guidance specifies (100.0%)

  Confusion matrix (rows = expected, columns = predicted)
                       HIGH      MEDIUM         LOW  UNASSESSED
  HIGH                    8           .           .           .
  MEDIUM                  .           7           .           .
  LOW                     .           .           4           .
  UNASSESSED              .           .           .           1

  HIGH         precision  1.00   recall  1.00   (n=8)
  MEDIUM       precision  1.00   recall  1.00   (n=7)
  LOW          precision  1.00   recall  1.00   (n=4)
  UNASSESSED   precision  1.00   recall  1.00   (n=1)
```

**Read the 100% correctly.** This is a *conformance* result: the labels
come from the same NHM corpus that `classify()`'s thresholds come from,
so it proves the code implements the protocol it cites. It does **not**
prove the protocol catches every woman at risk. Clinical validation needs
a clinician labelling real visits, and this project has not done that.

### 5.1 What the eval found on its first run — a real safety bug

The first run scored **18 of 20**, and both failures were the same root
cause:

> `ExtractedFields` had **no field for a reported symptom at all.** Agent 1
> extracted BP, weight, temperature, blood sugar, medication compliance,
> social risk factors and violence — and dropped everything the woman
> actually said about how she felt.

The consequence, reproduced before the fix:

```
normal BP (118/76) + "severe headache with blurred vision"
  →  LOW
  →  driver: "No abnormal findings recorded — within normal NHM range"
```

`nhm_corpus/antenatal_care.md` lists "Severe headache with blurred
vision" under **danger signs requiring immediate referral**, and states
that these signs *"are urgent whatever the blood pressure reading happens
to be"*. The system was reading the one number the guidance tells you to
disregard, and issuing an assurance on the strength of it.

This is worse than a miss. A miss is silence; this was a green badge and
the words "no abnormal findings recorded", for a woman showing the
presenting signs of imminent eclampsia.

**Fixed in three layers:**

1. `ExtractedFields.danger_signs` — a new field, kept separate from
   `social_risk_factors` for the same reason `violence_or_injury` is
   separate: these escalate outright rather than nudging a score.
2. Agent 1 `_DANGER_SIGN_RULES` — the seven immediate-referral signs from
   the corpus, matched in English, romanised Hindi and Devanagari.
   English-only patterns would have caught the danger sign for exactly
   the workers least likely to need the help.
3. `classify()` — a danger sign scores 1.0 on its own and is counted as
   clinical signal, so a normal BP on the same visit cannot average it
   away, and a visit reporting nothing else cannot come back UNASSESSED.

Verified after the fix, in both languages:

```
"सिर में तेज़ दर्द और धुंधला दिख रहा है" + BP 118/76   →  HIGH
"severe headache and blurred vision"  + BP 118/76      →  HIGH
"feeling fine, taking iron tablets"   + BP 118/76      →  LOW
"khoon aa raha hai since morning"                      →  HIGH
```

Full suite: **341 passed**, no regressions (as of this update -- count moves as tests are added; re-run `pytest -q` for the current figure before quoting it).

**This is the honest version of "our tests pass".** A suite that only ever
goes green tells you what the author thought of. This eval was written
against the guideline text instead of against the code, and it found
something real on its first run.

---

## 6. Field validation

**Status: NOT DONE.**

No usability testing has been carried out with practising ASHA workers.
The app's design is informed by published literature on ASHA workload
and by NHM protocol documents, not by observed use.

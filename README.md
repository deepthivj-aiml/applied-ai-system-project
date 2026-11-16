# 🐾 PawPal Reunite — Lost & Found Pet Matcher

**PawPal Reunite** matches lost pets with found pets. Upload a photo, share an
approximate location, and get ranked possible matches — each with a score,
human-readable reasons, and the sources it came from. A match is **never** a
confirmation of identity: always verify in person with photos and vet records.

## Original project

The original project is **PawPal+ (Module 2)**, from
https://github.com/codepath/ai110-module2show-pawpal-starter — a Streamlit
pet-care daily planner skeleton. It let an owner enter pet info and tasks
(duration + priority) and was supposed to generate a daily schedule, but the
"Generate schedule" button was not implemented: it only showed "Not implemented
yet." There was no scheduling logic, no tests, and no AI feature.

This final project **extends PawPal+ into a different job — reuniting lost and
found pets — instead of a daily plan.** It keeps the Streamlit UI and the
owner/pet form idea, and adds: Roboflow computer vision, keyword retrieval
(RAG-lite) over breed/search guidance, a weighted matcher, an agentic workflow
with a human-in-the-loop verifier, fuzzed location sharing with a map,
guardrails, an anonymous-reward system, and a test harness. Nothing from the
starter's daily-plan logic is reused, because there was none to reuse.

## What it does

- **Report Lost / Found** — pet attributes, optional photo, opt-in location
  (preset Bay Area place, lat/lon entry, or pasted "my location" coordinates).
  Exact coordinates are stored only for matching; the public display is fuzzed
  to ~500 m and never shows a home address. No phone/email is shown publicly.
- **Find Matches** — agent flow: Intake → Vision → Retriever/Matcher →
  Verifier (you confirm/correct vision attributes) → Notifier (draft message
  only, nothing is sent). Scores: ≥70 likely, 50–69 possible, <50 not shown.
- **Map** — all reports on a map using fuzzed locations only.
- **Rewards & Anonymous Hints** — see below.
- **How It Works / Testing** — architecture, scoring weights, live test output.

## Computer vision (Roboflow)

`vision.py` uses the Roboflow Inference SDK (`inference-sdk`,
`InferenceHTTPClient`). Model ID comes from `ROBOFLOW_MODEL_ID`
(default: public Universe pets model `pets-64nid-kbcey/1`); the API key comes
from `ROBOFLOW_API_KEY`. **No API key was available for this build, so no live
Roboflow call was made or claimed.** Without a key (or if the call fails), the
app uses a clearly-labelled **DEMO fallback**: attributes come from your manual
entry, `mode="demo"`, `confidence=None`, and the UI says "DEMO fallback — not
a model prediction." A breed is only reported when a live model actually
returned that label. Bounding boxes are drawn with PIL when a live prediction
returns them.

## Rewards & anonymous hints — no money moves in this app

- When reporting a **lost** pet, the owner may optionally pledge a reward
  ($0–$500, $0 = no reward). A pledge is a promise only. **The app moves NO
  money and takes NO payment details.**
- Anyone with a hint submits it **anonymously by case ID only**: hint text +
  optional location + optional photo. No name, phone, or email is collected
  or shown. The owner sees hints under the case ID, never who sent them.
- The owner can mark a hint "helpful". Only a hint marked **"led to reunion"**
  by the owner, after the owner confirms the pet is reunited, becomes
  reward-eligible. **Only ONE reward per case** — the first eligible hint only.
- On eligibility the app generates a one-time claim code
  (`RWD-<case>-<6 random chars>`), shown to the owner and to the anonymous
  hint-submitter on their submission receipt screen. **The submitter must save
  it — there is no contact channel to send it later.** The owner honours it
  outside the app by their chosen method, then marks it claimed
  (pledged → eligible → claimed). No payment details, no cash handover
  arranged in the app, no direct messaging.

## Architecture

See `diagrams/architecture.mmd` (Mermaid source) and `diagrams/uml.mmd`.

```
User (Streamlit) → Intake → Vision (Roboflow / demo) → Verifier (human-in-the-loop)
                 → Retriever (keyword RAG over data/knowledge + profiles)
                 → Matcher (weighted 0–100) → Ranked matches + fuzzed map
                 → Notifier (draft only) + Rewards & Anonymous Hints
                 → Logging (logs/app.log) + agent trace (ai_interactions.md)
```

Matching weights (max 100): species must match (else 0), breed +30, colour
+20, size +10, sex +5, markings overlap +15 (5 per shared keyword, cap 15),
date within 7 days +5, distance ≤2 km +15, 2–5 km +10, 5–15 km +5, >15 km 0.

## Setup

```bash
git clone <your-repo-url> applied-ai-system-final
cd applied-ai-system-final
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# optional, for live Roboflow vision:
cp .env.example .env   # then set ROBOFLOW_API_KEY
streamlit run app.py
```

Open http://localhost:8501. Without a key the app runs fully in demo vision mode.

## Sample interactions (real outputs)

### 1. Find a match — lost Golden Retriever (Biscuit, LF-001)

Input: dog, golden retriever, golden, large, male, markings "white chest
patch", 2026-11-10, Central Park, Fremont (37.5515, -121.9678).

```
PASS | Golden retriever lost -> found LF-002 | top=LF-002 score=100 expected=LF-002
```

Top match LF-002, score **100/100**, reasons: "Breed matches: golden
retriever", "Colour matches: golden", "Size matches: large", "Sex matches:
male", "Markings overlap (15 pts): chest, patch, white", "Dates within 7
days (2026-11-10 vs 2026-11-11)", "Found 0.9 km from last seen (within 2 km)".
Warning shown: "Likely match — please verify in person with photos, vet
records, and distinctive markings before claiming. This system does not
confirm identity." Retrieved source: `data/knowledge/breed_profiles.md`.

### 2. No match — species mismatch

Input: cat described as a golden retriever. Output: score **0**, reason
"Species does not match — cannot be the same pet." No matches shown.

### 3. Anonymous hint + reward-eligible

```
Pledge:  LF-001, $100, status=pledged
Hint:    HINT-XXXXXX — "Saw a golden near Lake Elizabeth at dusk" (anonymous, no identity stored)
Reunion: owner marks hint "led to reunion" -> reward_eligible=True
Claim code: RWD-LF-001-XXXXXX   (format RWD-<case>-<6 chars>, shown to owner and on the submitter's receipt)
Status:  pledged -> eligible -> claimed (owner marks claimed after honouring it outside the app)
```

(Exact hint IDs / claim codes are random per run; the format and flow above
were verified by the unit tests in `tests/test_pawpal.py`.)

## Testing summary

```
$ python -m pytest -q
.................  [100%]
17 passed in 0.22s

$ python eval/evaluate.py
PASS | Golden retriever lost -> found LF-002 | top=LF-002 score=100 expected=LF-002
PASS | Tabby cat lost -> found LF-004 | top=LF-004 score=95 expected=LF-004
PASS | Beagle lost -> found LF-006 | top=LF-006 score=95 expected=LF-006
PASS | Black lab lost in Union City -> LF-008 surfaces at 75 despite sex/distance mismatch (KNOWN LIMIT: sex is only 5 pts) | top=LF-008 score=75 expected=LF-008
PASS | Species mismatch -> no match | top=None score=0 expected=None
PASS | Orange tabby found -> lost? none in DB (no lost orange tabby) | top=None score=0 expected=None
SUMMARY: 6/6 passed
```

**What the tests cover (17 pytest tests):** haversine distance (same point = 0, Fremont–San Jose ~20–30 km), location fuzzing (exact coordinates never in the display string), species mismatch = 0, full match = 100, breed-only = 30, date proximity (±5 pts), low-confidence guardrail wording, `safe_display` removing contact details and exact location, vision demo fallback labelling, retrieval returning sources, `find_matches` filtering (<50 hidden, lost matches found only). **Rewards (5 tests):** $0 pledge can never become eligible, $500 cap enforced, only one eligible hint per case, claim-code format `RWD-<case>-<6 chars>` and uniqueness, hints carry no identity fields.

**What did not work / known limits:** the Black Lab eval case exposed a real weakness — a male lost dog in Union City still scores 75 against a female found dog in San Jose, because sex is worth only 5 points and breed+colour+size+markings dominate. The score is honest, but it means "likely" can include a sex mismatch; the UI's verify-in-person warning is the mitigation, and raising the sex weight is the obvious next fix. The demo vision fallback is also a limit, not a feature: without a Roboflow API key there is no live prediction to evaluate.

## Design decisions & trade-offs

- **No paid LLM API.** Retrieval is keyword-based over curated local docs and
  the profile database, so the app runs offline and reproducibly. Trade-off:
  it cannot understand synonyms ("golden" vs "blonde") — matching is exact on
  normalised attributes, which is honest about its limits.
- **Public Roboflow model, demo fallback.** A public breed model only covers
  a few breeds, so we never claim a breed the model did not return, and the
  demo fallback is labelled, not dressed up as a prediction.
- **Location fuzzing over precision.** Exact coordinates would match better,
  but a lost-pet app that publishes home addresses is unsafe. We accept
  ~500 m fuzzing and use exact coordinates only internally for distance.
- **Human-in-the-loop verifier.** Vision and matching are fallible; the user
  confirms attributes before matching, and every match carries a
  verify-in-person warning.
- **Anonymous hints, no messaging.** No contact channel means no harassment
  vector and no identity leak — at the cost that a hint-submitter who loses
  their claim code cannot be reached.

## Existing apps vs PawPal Reunite

Commercial apps do pieces of this separately: **Pettify** and **Patter** are
breed/age care planners with an AI assistant; **Pawly** tracks medical records
and care plans; **FurID** and Pet Breed Scanner identify breeds from a photo;
**Puppii** and **Sniffy** scan food/photos for toxic items. None of them
combines, in one open, runnable project: lost/found matching + Roboflow vision
+ retrieval with shown sources + fuzzed location sharing + anonymous hints
with a reward claim code + guardrails + a test harness with published
pass/fail results. They are also closed, paid apps; PawPal Reunite is open
source and its reliability is checkable from the repo.

## Reproducible execution evidence

```bash
python -m pytest -q
python eval/evaluate.py
streamlit run app.py --server.headless true   # then open http://localhost:8501
```

See "Testing summary" above and `eval/results.txt` for the real outputs.

## Reflection (portfolio)

This project says about me as an AI engineer: I can take a thin starter and
turn it into a complete, responsible system — retrieval, vision, an agentic
flow, location privacy, and reliability testing — without pretending the AI is
more certain than it is. The interesting work was not the model, it was the
guardrails: fuzzing locations, labelling demo results, refusing to confirm an
identity, and making anonymity and "no money moves here" real in the code,
not just in the copy. See `model_card.md` for the full reflection.

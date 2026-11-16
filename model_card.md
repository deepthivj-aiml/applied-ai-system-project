# Model Card — PawPal Reunite

## What the system is
Lost & Found pet matcher (Streamlit). Vision via Roboflow Inference SDK
(live only with `ROBOFLOW_API_KEY`; otherwise a labelled demo fallback),
keyword retrieval over local docs, weighted matching (0–100), an agentic
flow with human-in-the-loop verification, fuzzed location sharing, and an
anonymous-hint reward system in which **no money moves in the app**.

## Limitations / biases

- **Vision is narrow and often absent.** The default public Roboflow pets
  model covers few breeds; without an API key there is no live prediction at
  all — the demo fallback just echoes the user's manual entry. A breed is
  never claimed unless a live model returned it.
- **Matching is exact-keyword based.** "Golden" vs "blonde", "tabby" vs
  "striped", and typos do not match. The 10-profile sample database is
  Fremont/Bay Area only and is illustrative, not a real lost-pet registry.
- **Sample images are labelled PIL illustrations**, not real pet photos.
  They exist so the UI can be demoed; they prove nothing about vision accuracy.
- **Sex is worth only 5 points.** In the eval harness a male lost Black Lab in Union City scores 75 against a female found Black Lab in San Jose — breed, colour, size and markings dominate. 'Likely' can therefore include a sex mismatch; verify-in-person is the mitigation and raising the sex weight is the next fix.
- **Location fuzzing (~500 m) trades precision for safety** and can change
  which distance band a match falls in near a boundary.
- **No identity verification.** The system cannot tell whether two similar
  pets are the same animal, whether a hint is true, or whether a person
  claiming a pet is its owner. That is why every match says "verify in
  person with photos and vet records."

## Could the AI be misused, and how would you prevent that?

- **False claims / pet theft:** someone could claim a found pet that is not
  theirs. Prevention: the app never confirms identity, always shows the
  verify-in-person warning, and never hands over contact details — contact
  is by case ID with a draft message only.
- **Reward fraud:** someone could submit a false hint to collect a reward,
  or an owner could promise a reward and not pay. Prevention (limited, and
  stated honestly): **owner verification is the only anti-fraud control.**
  Only the owner can mark a hint as leading to a reunion, only one reward
  per case, and the claim code is one-time. The app cannot verify a hint is
  true, cannot enforce payment, and moves no money — the README and UI say
  so plainly. Low-quality/spam hints can be hidden by the owner.
- **Location stalking / doxxing:** exact locations and home addresses could
  be misused. Prevention: exact lat/lon are used only internally for
  distance; public display is fuzzed to ~500 m with a neighbourhood label,
  location sharing is opt-in, and no phone/email/address is ever shown.
- **Photo misuse:** uploaded photos are used only for the current match
  attempt and are not published with contact details.

## What surprised you while testing your AI's reliability?

Two things. First, how much of the score comes from the distance band and
markings: the "perfect" Golden Retriever match scored 100 only because
every field lined up — change the colour and the same dog drops to 80, change
the location to San Jose and it drops further, so the ranking is honest but
brittle to how carefully the reporter filled in the form. Second, the
species gate is the most valuable line of code in the project: without it,
a cat described with dog attributes could surface as a "possible match";
with it, it scores exactly 0. Small guardrails beat clever scoring.

## AI collaboration

- **One suggestion I accepted:** weighted scoring with human-readable
  reasons for every point (breed +30, colour +20, …). An AI assistant
  suggested it during this build; I kept it because it makes every match
  explainable and testable — the tests assert the exact scores, and the UI
  shows the reasons. It is the reason the eval harness can print pass/fail
  instead of a black-box number.
- **One suggestion I rejected / revised:** claiming a breed from the public
  Roboflow model as if it worked for any breed. The first design treated the
  model label as a breed identification. I scoped it down: the model only
  covers a few breeds, so a breed is reported only when the live model
  actually returned a known breed label, and without an API key the app
  uses a clearly-labelled demo fallback that echoes manual entry instead of
  pretending to predict. The revision cost a flashier demo and bought honesty.

## Evaluation (parseable)

| Test input | Evaluation criteria | Result |
|---|---|---|
| Golden retriever lost (LF-001) | Top match LF-002, score ≥ 70 | See eval/results.txt |
| Tabby cat lost (LF-003) | Top match LF-004, score ≥ 70 | See eval/results.txt |
| Beagle lost (LF-005) | Top match LF-006, score ≥ 70 | See eval/results.txt |
| Black lab, Union City | No likely match claimed | See eval/results.txt |
| Species mismatch (cat as dog) | Score 0, no match | See eval/results.txt |
| Orange tabby found, no lost match | No match shown | See eval/results.txt |
| Reward $0 pledge | No eligibility possible | Pass (unit test) |
| Reward $100, two hints | Only one eligible hint | Pass (unit test) |
| Claim code | Format RWD-<case>-<6 chars>, unique | Pass (unit test) |
| Location display | Exact coords never shown | Pass (unit test) |

Run `python -m pytest -q` and `python eval/evaluate.py` for the measured numbers.

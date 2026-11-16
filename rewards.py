"""Anonymous rewards for helpful hints — NO money moves in this app.

Rules (see README / model_card for the plain-language version):
- A lost-pet owner may pledge an optional reward ($0-$500). A pledge is a
  promise only: the app moves NO money and takes NO payment details.
- Hints are submitted ANONYMOUSLY by case ID only: hint text + optional
  location + optional photo. No name, phone, or email is collected or shown.
- The owner sees hints under the case ID, never who sent them.
- Only a hint marked "led to reunion" by the owner, AFTER the owner confirms
  the pet is reunited, becomes reward-eligible. Only ONE reward per case:
  the first eligible hint only.
- On eligibility the app generates a one-time claim code
  (RWD-<case>-<6 random chars>). The code is shown to the owner AND to the
  anonymous hint-submitter on their submission receipt screen (they must
  save it — there is no contact channel to send it later). The owner honours
  it outside the app by their chosen method; the owner then marks it claimed.
  Statuses: pledged -> eligible -> claimed. No payment details, no cash
  handover arranged in the app, no direct messaging.
"""
import re
import secrets
import string
from datetime import datetime

MAX_REWARD_USD = 500
_CODE_ALPHABET = string.ascii_uppercase + string.digits


def create_pledge(case_id, amount_usd):
    """Validate and record a reward pledge. $0 = no reward. Cap $500."""
    try:
        amount = float(amount_usd)
    except (TypeError, ValueError):
        raise ValueError("Reward amount must be a number.")
    if amount < 0 or amount > MAX_REWARD_USD:
        raise ValueError(f"Reward must be between $0 and ${MAX_REWARD_USD}.")
    return {"case_id": case_id, "amount_usd": amount,
            "status": "pledged" if amount > 0 else "none",
            "created_at": datetime.now().isoformat(timespec="seconds")}


def submit_hint(case_id, hint_text, location_label=None, photo_name=None):
    """Submit an anonymous hint. No identity fields exist by design."""
    if not hint_text or not hint_text.strip():
        raise ValueError("Hint text is required.")
    return {"case_id": case_id, "hint_id": f"HINT-{secrets.token_hex(3).upper()}",
            "hint_text": hint_text.strip(), "location_label": location_label,
            "photo_name": photo_name, "helpful": False,
            "led_to_reunion": False, "reward_eligible": False,
            "claim_code": None, "hidden": False,
            "submitted_at": datetime.now().isoformat(timespec="seconds")}


def mark_hint_helpful(hint):
    hint = dict(hint)
    hint["helpful"] = True
    return hint


def generate_claim_code(case_id):
    suffix = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
    return f"RWD-{case_id}-{suffix}"


def mark_reunited_and_eligible(hints, hint_id, pledge):
    """Owner confirms reunion and marks ONE hint as having led to it.

    Only the first eligible hint per case wins. No eligibility before the
    owner confirms reunion (this function IS that confirmation). A $0 / no
    pledge case can never become reward-eligible.
    """
    if not pledge or pledge.get("amount_usd", 0) <= 0:
        raise ValueError("No reward pledged for this case ($0) — nothing is eligible.")
    if any(h.get("reward_eligible") for h in hints):
        raise ValueError("A reward has already been made eligible for this case — only one per case.")
    updated = []
    found = False
    for h in hints:
        h = dict(h)
        if h.get("hint_id") == hint_id:
            found = True
            h["led_to_reunion"] = True
            h["reward_eligible"] = True
            h["claim_code"] = generate_claim_code(pledge["case_id"])
        updated.append(h)
    if not found:
        raise ValueError(f"No hint with id {hint_id} for this case.")
    return updated


def mark_claimed(pledge, hint):
    """Owner marks the eligible reward as claimed (honoured outside the app)."""
    if not hint.get("reward_eligible"):
        raise ValueError("This hint is not reward-eligible, so there is nothing to claim.")
    if pledge.get("status") == "claimed":
        raise ValueError("This reward was already marked claimed.")
    pledge = dict(pledge)
    pledge["status"] = "claimed"
    pledge["claimed_at"] = datetime.now().isoformat(timespec="seconds")
    pledge["claim_code"] = hint.get("claim_code")
    return pledge


def claim_code_is_valid(code):
    return bool(re.fullmatch(r"RWD-[A-Za-z0-9-]+-[A-Z0-9]{6}", str(code or "")))

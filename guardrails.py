"""Guardrails for PawPal Reunite.

The system never claims a definite identity, never diagnoses health,
and never exposes exact locations or private contact details.
"""
from location import display_location

LIKELY_MIN = 70
POSSIBLE_MIN = 50


def verdict_for_score(score):
    if score >= LIKELY_MIN:
        return "likely"
    if score >= POSSIBLE_MIN:
        return "possible"
    return "unlikely"


def match_warning(score):
    verdict = verdict_for_score(score)
    if verdict == "likely":
        return ("Likely match — please verify in person with photos, "
                "vet records, and distinctive markings before claiming. "
                "This system does not confirm identity.")
    if verdict == "possible":
        return ("Possible match — verify in person with photos and vet "
                "records. Do not rely on this score alone.")
    return ("Not shown as a match. Score below the display threshold; "
            "verify in person if you still think it could be your pet.")


def safe_display(profile):
    """Public-safe copy of a profile: fuzzed location, no contact details."""
    p = dict(profile)
    if "lat" in p and "lon" in p:
        p["location_display"] = display_location(p["lat"], p["lon"], p.get("place_label", ""))
        p.pop("lat", None)
        p.pop("lon", None)
    for key in ("owner_name", "phone", "email", "address"):
        p.pop(key, None)
    return p


def contact_message(case_id, species, breed):
    return (f"Hello, I am writing about case {case_id} "
            f"({species}, {breed}). I think this may be my pet / a pet I found. "
            "Could we arrange to verify in person with photos and vet records? "
            "Please reply through PawPal Reunite using this case ID — "
            "do not share your phone or home address here.")


def check_low_confidence(score, vision_mode=None):
    """Return a warning string when a result should not be trusted, else ''."""
    if vision_mode == "demo":
        return ("Vision result is a DEMO fallback, not a model prediction. "
                "Attributes below came from your manual entry — please confirm them.")
    if score is not None and score < POSSIBLE_MIN:
        return "Low confidence — treat as unverified and check in person."
    return ""

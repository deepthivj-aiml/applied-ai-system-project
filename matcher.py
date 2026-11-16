"""Weighted matching for PawPal Reunite.

Weights (max 100):
  species must match, else 0 | breed +30 | colour +20 | size +10
  sex +5 | markings keyword overlap +15 (5 per shared keyword, cap 15)
  date within 7 days +5 | distance <=2km +15, 2-5km +10, 5-15km +5, >15km 0
Thresholds: >=70 likely, 50-69 possible, <50 not shown as a match.
"""
from datetime import date, datetime

from location import distance_band_km, haversine_km


def _parse_date(value):
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%d").date()
    return None


def _norm(text):
    return str(text or "").strip().lower()


def _markings_overlap(a, b):
    def words(profile):
        raw = profile.get("markings", "") or ""
        return {w.strip().lower() for w in raw.replace(",", " ").split() if w.strip()}
    shared = words(a) & words(b)
    return shared, min(15, 5 * len(shared))


def score_match(query, candidate):
    """Return (score 0-100, reasons list). Species mismatch -> (0, [reason])."""
    if _norm(query.get("species")) != _norm(candidate.get("species")):
        return 0, ["Species does not match — cannot be the same pet."]
    score, reasons = 0, []
    if _norm(query.get("breed")) and _norm(query.get("breed")) == _norm(candidate.get("breed")):
        score += 30
        reasons.append(f"Breed matches: {candidate.get('breed')}")
    if _norm(query.get("colour")) and _norm(query.get("colour")) == _norm(candidate.get("colour")):
        score += 20
        reasons.append(f"Colour matches: {candidate.get('colour')}")
    if _norm(query.get("size")) and _norm(query.get("size")) == _norm(candidate.get("size")):
        score += 10
        reasons.append(f"Size matches: {candidate.get('size')}")
    if _norm(query.get("sex")) and _norm(query.get("sex")) == _norm(candidate.get("sex")):
        score += 5
        reasons.append(f"Sex matches: {candidate.get('sex')}")
    shared, pts = _markings_overlap(query, candidate)
    if pts:
        score += pts
        reasons.append(f"Markings overlap ({pts} pts): {', '.join(sorted(shared))}")
    qd, cd = _parse_date(query.get("date")), _parse_date(candidate.get("date"))
    if qd and cd and abs((qd - cd).days) <= 7:
        score += 5
        reasons.append(f"Dates within 7 days ({qd} vs {cd})")
    try:
        dist = haversine_km(float(query["lat"]), float(query["lon"]),
                            float(candidate["lat"]), float(candidate["lon"]))
        pts, band = distance_band_km(dist)
        score += pts
        reasons.append(f"Found {dist:.1f} km from last seen ({band})")
    except (KeyError, TypeError, ValueError):
        reasons.append("Location missing — distance not scored.")
    return min(100, score), reasons


def find_matches(query, candidates, min_score=50):
    """Ranked matches >= min_score, highest first, each with score/reasons."""
    results = []
    for cand in candidates:
        if cand.get("status") == query.get("status"):
            continue  # lost matches found, found matches lost -- never same side
        score, reasons = score_match(query, cand)
        if score >= min_score:
            results.append({"profile": cand, "score": score, "reasons": reasons})
    return sorted(results, key=lambda r: r["score"], reverse=True)

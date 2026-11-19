"""Rank dog reports using VLM photo recognition, details, and distance."""
from location import haversine_km

_FEATURE_WEIGHTS = {
    "breed": 0.32,
    "colour": 0.23,
    "size": 0.15,
    "sex": 0.08,
    "markings": 0.22,
}
PHOTO_WEIGHT = 0.90
FEATURE_WEIGHT = 0.07
LOCATION_WEIGHT = 0.03


def _text(value):
    return " ".join(str(value or "").strip().lower().split())


def _tokens(value):
    return {part for part in _text(value).replace(",", " ").split() if part}


def _jaccard(left, right):
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return None
    return 100.0 * len(a & b) / len(a | b)


def feature_similarity(query, candidate):
    """Compare known dog attributes, ignoring fields missing on either report."""
    scores = []
    for field, weight in _FEATURE_WEIGHTS.items():
        query_value = _text(query.get(field))
        candidate_value = _text(candidate.get(field))
        if not query_value or not candidate_value:
            continue
        if field == "sex" and (query_value == "unknown" or candidate_value == "unknown"):
            continue
        if field in ("size", "sex"):
            similarity = 100.0 if query_value == candidate_value else 0.0
        else:
            similarity = _jaccard(query_value, candidate_value) or 0.0
        scores.append((similarity, weight))
    if not scores:
        return None
    return sum(score * weight for score, weight in scores) / sum(weight for _, weight in scores)


def _distance(query, candidate):
    try:
        return haversine_km(
            float(query["lat"]), float(query["lon"]),
            float(candidate["lat"]), float(candidate["lon"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def location_points(distance_km):
    """Return secondary location points (max 3) for distance from lost location."""
    if distance_km is None:
        return 0, "Location unavailable"
    if distance_km <= 2:
        return 3, "within 2 km"
    if distance_km <= 5:
        return 2, "2–5 km"
    if distance_km <= 10:
        return 1, "5–10 km"
    return 0, "more than 10 km"


def score_match_details(query, candidate, photo_similarity=None):
    """Compute a 0–100 weighted match and return its components.

    When a VLM photo score is available it contributes 90%, dog attributes 7%,
    and distance 3%. Missing components are excluded and the available weights
    are normalized so the displayed score remains a percentage.
    """
    if _text(query.get("species", "dog")) != _text(candidate.get("species", "dog")):
        return {
            "score": 0, "feature_score": None, "photo_score": None,
            "distance_km": None, "location_points": 0,
            "reasons": ["Species does not match."],
        }

    feature_score = feature_similarity(query, candidate)
    distance = _distance(query, candidate)
    points, band = location_points(distance)
    components = []

    if photo_similarity is not None:
        photo_score = max(0.0, min(100.0, float(photo_similarity)))
        components.append((photo_score, PHOTO_WEIGHT, "photo"))
    else:
        photo_score = None

    if feature_score is not None:
        components.append((feature_score, FEATURE_WEIGHT, "features"))

    if distance is not None:
        location_percent = points / 3 * 100
        components.append((location_percent, LOCATION_WEIGHT, "location"))

    if not components:
        return {
            "score": 0, "feature_score": feature_score, "photo_score": photo_score,
            "distance_km": distance, "location_points": points,
            "reasons": ["No dog features, photo score, or location available to compare."],
        }

    total_weight = sum(weight for _, weight, _ in components)
    score = round(sum(value * weight for value, weight, _ in components) / total_weight)
    reasons = []
    for value, weight, component in components:
        effective_weight = 100 * weight / total_weight
        if component == "photo":
            reasons.append(
                f"VLM photo similarity: {value:.0f}% ({effective_weight:.0f}% of score)"
            )
        elif component == "features":
            reasons.append(
                f"Dog features: {value:.0f}% ({effective_weight:.0f}% of score; missing fields skipped)"
            )
        else:
            reasons.append(
                f"Distance from lost report location: {distance:.1f} km "
                f"({band}; +{points}/3 location points; {effective_weight:.0f}% of score)"
            )
    return {
        "score": score,
        "feature_score": round(feature_score) if feature_score is not None else None,
        "photo_score": round(photo_score) if photo_score is not None else None,
        "distance_km": round(distance, 1) if distance is not None else None,
        "location_points": points,
        "reasons": reasons,
    }


def score_match(query, candidate, photo_similarity=None):
    """Backwards-compatible (score, reasons) result for one report pair."""
    details = score_match_details(query, candidate, photo_similarity)
    return details["score"], details["reasons"]


def find_matches(query, candidates, photo_scores=None, photo_reasons=None):
    """Return opposite-status dog reports ranked by the available evidence."""
    if _text(query.get("species", "dog")) != "dog":
        return []
    photo_scores = photo_scores or {}
    photo_reasons = photo_reasons or {}
    query_id = str(query.get("case_id", "")).upper()
    query_status = _text(query.get("status"))
    results = []
    for candidate in candidates:
        candidate_id = str(candidate.get("case_id", "")).upper()
        candidate_status = _text(candidate.get("status"))
        if candidate_id == query_id or candidate_status == query_status:
            continue
        if candidate_status not in {"lost", "found"}:
            continue
        if _text(candidate.get("species", "dog")) != "dog":
            continue

        feature_score = feature_similarity(query, candidate)
        photo_score = photo_scores.get(candidate_id)
        if feature_score is None and photo_score is None and _distance(query, candidate) is None:
            continue

        details = score_match_details(
            query, candidate, photo_similarity=photo_score
        )
        if photo_reasons.get(candidate_id):
            details["reasons"].append(f"VLM visual note: {photo_reasons[candidate_id]}")
        results.append({"profile": candidate, **details})

    return sorted(
        results,
        key=lambda result: (result["score"], result["feature_score"] or 0),
        reverse=True,
    )

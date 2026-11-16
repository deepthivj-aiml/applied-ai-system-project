import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from location import haversine_km, fuzz_latlon, display_location
from matcher import score_match, find_matches
from guardrails import match_warning, safe_display, check_low_confidence
from retrieval import retrieve, load_profiles
from vision import analyse_image
from rewards import create_pledge, submit_hint, mark_reunited_and_eligible, generate_claim_code, mark_claimed, claim_code_is_valid
import pytest

Q = {"species":"dog","breed":"golden retriever","colour":"golden","size":"large","sex":"male","markings":"white chest patch","date":"2026-11-10","lat":37.5515,"lon":-121.9678,"status":"lost"}
C = {"case_id":"LF-002","species":"dog","breed":"golden retriever","colour":"golden","size":"large","sex":"male","markings":"white chest patch floppy ears","date":"2026-11-11","lat":37.5470,"lon":-121.9600,"status":"found"}

def test_haversine_same_point_zero():
    assert haversine_km(37.5,-121.9,37.5,-121.9) == 0.0

def test_haversine_fremont_to_sanjose_about_20km():
    d = haversine_km(37.5515,-121.9678,37.3382,-121.8863)
    assert 20 < d < 30, d

def test_fuzzing_never_shows_exact_coords():
    s = display_location(37.5515,-121.9678,"Central Park")
    assert "37.5515" not in s and "-121.9678" not in s and "500 m" in s
    flat, flon = fuzz_latlon(37.5515,-121.9678)
    assert abs(flat-37.5515) <= 0.005 and abs(flon+121.9678) <= 0.005

def test_species_mismatch_scores_zero():
    q = dict(Q, species="cat")
    score, reasons = score_match(q, C)
    assert score == 0

def test_full_match_scores_100():
    score, reasons = score_match(Q, C)
    assert score == 100, (score, reasons)
    assert any("Breed matches" in r for r in reasons)

def test_scoring_weights_breed_only():
    c = dict(C, colour="black", size="small", sex="female", markings="none", date="2026-01-01", lat=37.0, lon=-122.5)
    score, _ = score_match(Q, c)
    assert score == 30, score  # breed only

def test_date_proximity():
    c = dict(C, date="2026-11-20")  # 10 days away, same other fields
    score_far, _ = score_match(Q, c)
    score_near, _ = score_match(Q, C)
    assert score_near - score_far == 5

def test_low_confidence_guardrail_wording():
    w = match_warning(55)
    assert "verify in person" in w.lower()
    assert "does not confirm" in match_warning(85).lower() or "verify in person" in match_warning(85).lower()

def test_safe_display_removes_contact_and_exact_location():
    p = dict(C, phone="555-1234", email="a@b.com", lat=37.5470, lon=-121.96)
    s = safe_display(p)
    assert "phone" not in s and "email" not in s and "lat" not in s
    assert "37.547" not in s.get("location_display","")

def test_vision_demo_fallback_labelled():
    v = analyse_image("/tmp/nonexistent.png", manual={"species":"dog","breed":"beagle"})
    assert v["mode"] == "demo" and v["confidence"] is None
    assert "DEMO" in v["note"] and "not a model prediction" in v["note"]

def test_retrieval_returns_sources():
    res = retrieve("golden retriever exercise lost dog")
    assert res and all("source" in r for r in res)

def test_find_matches_filters_below_threshold_and_same_status():
    profiles = load_profiles()
    assert len(profiles) == 10
    matches = find_matches(Q, profiles)
    assert matches and matches[0]["profile"]["case_id"] == "LF-002"
    assert all(m["score"] >= 50 for m in matches)
    assert all(m["profile"]["status"] == "found" for m in matches)

# --- Rewards (4+ required) ---
def test_reward_zero_means_no_reward():
    p = create_pledge("LF-001", 0)
    assert p["status"] == "none" and p["amount_usd"] == 0
    h = submit_hint("LF-001", "Saw a golden near the lake")
    with pytest.raises(ValueError):
        mark_reunited_and_eligible([h], h["hint_id"], p)

def test_reward_cap_500():
    with pytest.raises(ValueError):
        create_pledge("LF-001", 501)
    assert create_pledge("LF-001", 500)["amount_usd"] == 500

def test_only_one_eligible_hint():
    p = create_pledge("LF-001", 100)
    h1, h2 = submit_hint("LF-001","hint one"), submit_hint("LF-001","hint two")
    out = mark_reunited_and_eligible([h1,h2], h1["hint_id"], p)
    assert sum(1 for h in out if h["reward_eligible"]) == 1
    with pytest.raises(ValueError):
        mark_reunited_and_eligible(out, h2["hint_id"], p)

def test_no_eligibility_before_reunion_and_claim_code_format():
    p = create_pledge("LF-001", 100)
    h = submit_hint("LF-001","hint")
    assert not h["reward_eligible"] and h["claim_code"] is None
    out = mark_reunited_and_eligible([h], h["hint_id"], p)
    code = out[0]["claim_code"]
    assert claim_code_is_valid(code)
    assert generate_claim_code("LF-001") != generate_claim_code("LF-001")  # unique (random suffix)
    claimed = mark_claimed(p, out[0])
    assert claimed["status"] == "claimed"

def test_hint_is_anonymous_no_identity_fields():
    h = submit_hint("LF-001","Saw dog at park", location_label="Lake Elizabeth")
    assert "phone" not in h and "email" not in h and "name" not in h

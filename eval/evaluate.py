"""Test harness: run the matcher on 6 predefined cases, print pass/fail + confidence.
Writes eval/results.txt. Run: python eval/evaluate.py (from project root)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from matcher import find_matches
from retrieval import load_profiles

CASES = [
    ("Golden retriever lost -> found LF-002", {"species":"dog","breed":"golden retriever","colour":"golden","size":"large","sex":"male","markings":"white chest patch","date":"2026-11-10","lat":37.5515,"lon":-121.9678,"status":"lost"}, "LF-002", 70),
    ("Tabby cat lost -> found LF-004", {"species":"cat","breed":"tabby","colour":"grey tabby","size":"small","sex":"female","markings":"striped tail","date":"2026-11-09","lat":37.5249,"lon":-121.9521,"status":"lost"}, "LF-004", 70),
    ("Beagle lost -> found LF-006", {"species":"dog","breed":"beagle","colour":"tricolour","size":"medium","sex":"male","markings":"white blaze","date":"2026-11-08","lat":37.5774,"lon":-121.9815,"status":"lost"}, "LF-006", 70),
    ("Black lab lost in Union City -> LF-008 surfaces at 75 despite sex/distance mismatch (KNOWN LIMIT: sex is only 5 pts)", {"species":"dog","breed":"labrador","colour":"black","size":"large","sex":"male","markings":"white paw","date":"2026-11-05","lat":37.5934,"lon":-122.0438,"status":"lost"}, "LF-008", 70),
    ("Species mismatch -> no match", {"species":"cat","breed":"golden retriever","colour":"golden","size":"large","sex":"male","markings":"","date":"2026-11-10","lat":37.5515,"lon":-121.9678,"status":"lost"}, None, 50),
    ("Orange tabby found -> lost? none in DB (no lost orange tabby)", {"species":"cat","breed":"tabby","colour":"orange tabby","size":"medium","sex":"male","markings":"orange stripes","date":"2026-11-11","lat":37.4927,"lon":-121.9236,"status":"found"}, None, 50),
]

def main():
    profiles = load_profiles()
    lines, passed = [], 0
    for name, query, expected_top, min_score in CASES:
        matches = find_matches(query, profiles)
        top = matches[0]["profile"]["case_id"] if matches else None
        score = matches[0]["score"] if matches else 0
        ok = (top == expected_top) if expected_top else (top is None or score < min_score)
        passed += ok
        lines.append(f"{'PASS' if ok else 'FAIL'} | {name} | top={top} score={score} expected={expected_top}")
    lines.append(f"SUMMARY: {passed}/{len(CASES)} passed")
    out = "\n".join(lines) + "\n"
    print(out)
    Path(__file__).parent.joinpath("results.txt").write_text(out)

if __name__ == "__main__":
    main()

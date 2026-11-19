"""Run a small offline check of the sample dog match rankings."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from matcher import find_matches
from retrieval import load_profiles


CASES = [
    ("Golden retriever near Lake Elizabeth", "LF-001", "LF-002"),
    ("Beagle near Niles", "LF-005", "LF-006"),
    ("Black lab near Union City", "LF-009", "LF-008"),
]


def main():
    profiles = load_profiles()
    lines = []
    passed = 0
    for label, case_id, expected in CASES:
        query = next(profile for profile in profiles if profile["case_id"] == case_id)
        matches = find_matches(query, profiles)
        actual = matches[0]["profile"]["case_id"] if matches else None
        score = matches[0]["score"] if matches else 0
        ok = actual == expected
        passed += ok
        lines.append(f"{'PASS' if ok else 'FAIL'} | {label} | top={actual} score={score} expected={expected}")
    lines.append(f"SUMMARY: {passed}/{len(CASES)} passed")
    output = "\n".join(lines) + "\n"
    print(output)
    Path(__file__).with_name("results.txt").write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()

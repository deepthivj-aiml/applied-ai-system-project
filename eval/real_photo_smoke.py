"""Compare real dog photo fixtures and print match components for inspection."""
import json
import sys
from pathlib import Path

from PIL import Image

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from matcher import find_matches
from vlm_matcher import compare_report_photos


def main():
    reports = json.loads(
        (BASE_DIR / "data" / "real_photo_test_reports.json").read_text(encoding="utf-8")
    )
    query = next(item for item in reports if item["case_id"] == "PHOTO-LOST-01")
    candidates = [item for item in reports if item["status"] == "found"]
    for report in [query, *candidates]:
        photo_path = BASE_DIR / report["photo"]
        with Image.open(photo_path) as image:
            image.verify()
        with Image.open(photo_path) as image:
            print(f"Photo: {photo_path.name} | {image.format} | {image.width}x{image.height}")
    vlm_result = compare_report_photos(query, candidates)

    photo_scores = vlm_result.get("scores", {})
    photo_reasons = vlm_result.get("reasons", {})
    matches = find_matches(
        query, candidates,
        photo_scores=photo_scores,
        photo_reasons=photo_reasons,
    )

    print(f"Query: {query['case_id']} | {query['breed']} | {query['place_label']}")
    print(f"Photo comparison: {vlm_result['status']}")
    if vlm_result.get("model"):
        print(f"Model: {vlm_result['model']} | photos compared: {vlm_result['compared']}")
    if vlm_result["status"] == "not_configured":
        print("VLM skipped: set OPENAI_API_KEY in .env to run the live image comparison.")
    for item in matches:
        profile = item["profile"]
        print(json.dumps({
            "case_id": profile["case_id"],
            "photo": Path(profile["photo"]).name,
            "score": item["score"],
            "photo_score": item["photo_score"],
            "feature_score": item["feature_score"],
            "distance_km": item["distance_km"],
            "location_points": item["location_points"],
            "reasons": item["reasons"],
            "test_note": profile.get("test_note"),
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()

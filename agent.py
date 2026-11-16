"""Agentic workflow for PawPal Reunite.

Steps: Intake -> Vision -> Retriever/Matcher -> Verifier (human-in-the-loop:
the user confirms/corrects vision attributes before matching) -> Notifier
(draft message only -- nothing is sent).
Every run appends a structured trace to ai_interactions.md and logs to logs/app.log.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from guardrails import match_warning, safe_display
from matcher import find_matches
from retrieval import load_knowledge, load_profiles, retrieve
from vision import analyse_image

BASE = Path(__file__).parent
LOG_PATH = BASE / "logs" / "app.log"
TRACE_PATH = BASE / "ai_interactions.md"

logging.basicConfig(filename=str(LOG_PATH), level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("pawpal-reunite")


def _append_trace(trace):
    TRACE_PATH.parent.mkdir(exist_ok=True)
    with open(TRACE_PATH, "a", encoding="utf-8") as f:
        f.write("\n## Agent Trace — " + trace["started_at"] + "\n\n")
        f.write("```json\n" + json.dumps(trace, indent=2, default=str) + "\n```\n")


def run_match_flow(query, image_path=None, human_confirmed=None,
                   candidates=None, knowledge=None):
    """Run Intake -> Vision -> Retriever/Matcher -> Verifier -> Notifier.

    query: dict with species/breed/colour/size/sex/markings/date/lat/lon/status.
    human_confirmed: dict of attributes the user confirmed/corrected after
    seeing the vision result. If given, it overrides vision attributes.
    Returns a dict with vision, matches, sources, notifier draft, trace.
    """
    trace = {"started_at": datetime.now().isoformat(timespec="seconds"),
             "steps": [], "query": {k: v for k, v in query.items()}}
    trace["steps"].append({"step": "1-intake", "status": query.get("status"),
                           "species": query.get("species"),
                           "place": query.get("place_label")})
    vision = None
    if image_path:
        vision = analyse_image(image_path, manual=query)
        trace["steps"].append({"step": "2-vision", "mode": vision["mode"],
                               "model_id": vision["model_id"],
                               "confidence": vision["confidence"],
                               "species": vision["species"], "breed": vision["breed"],
                               "note": vision["note"]})
    else:
        trace["steps"].append({"step": "2-vision", "mode": "skipped",
                               "note": "No photo uploaded."})
    # Verifier: human confirmation overrides vision before matching.
    effective = dict(query)
    if human_confirmed:
        for key in ("species", "breed", "colour", "size", "sex"):
            if human_confirmed.get(key):
                effective[key] = human_confirmed[key]
        trace["steps"].append({"step": "3-verifier-human-in-the-loop",
                               "confirmed": human_confirmed})
    elif vision and vision["mode"] == "live" and vision.get("species"):
        effective["species"] = vision["species"]
        if vision.get("breed"):
            effective["breed"] = vision["breed"]
        trace["steps"].append({"step": "3-verifier",
                               "note": "Live vision attributes used; user did not correct them."})
    else:
        trace["steps"].append({"step": "3-verifier",
                               "note": "Manual attributes used (demo mode or no photo)."})
    sources = retrieve(
        f"{effective.get('species')} {effective.get('breed')} {effective.get('colour')} lost pet search",
        docs=knowledge or load_knowledge())
    trace["steps"].append({"step": "4-retriever",
                           "sources": [s["source"] for s in sources]})
    matches = find_matches(effective, candidates or load_profiles())
    trace["steps"].append({"step": "5-matcher",
                           "matches": [{"case_id": m["profile"]["case_id"],
                                        "score": m["score"]} for m in matches]})
    for m in matches:
        m["warning"] = match_warning(m["score"])
        m["public_profile"] = safe_display(m["profile"])
    notifier = None
    if matches:
        top = matches[0]
        from guardrails import contact_message
        notifier = {"draft_only_not_sent": True,
                    "message": contact_message(top["profile"]["case_id"],
                                               top["profile"]["species"],
                                               top["profile"]["breed"])}
    trace["steps"].append({"step": "6-notifier",
                           "draft_created": bool(notifier),
                           "note": "Draft only. Nothing is sent by the app."})
    logger.info("match flow: %s -> %d matches", query.get("case_id", "query"), len(matches))
    _append_trace(trace)
    return {"vision": vision, "effective_query": effective, "matches": matches,
            "sources": sources, "notifier": notifier, "trace": trace}

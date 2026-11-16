"""Vision module for PawPal Reunite.

Live mode: Roboflow Inference SDK (inference-sdk, InferenceHTTPClient),
model_id from env ROBOFLOW_MODEL_ID (default: public Universe pets model
pets-64nid-kbcey/1), API key from env ROBOFLOW_API_KEY.
Demo mode: no key / no network / call fails -> attributes come ONLY from
the user's manual confirmations, mode="demo", confidence=None.
The demo result is NEVER presented as a model prediction, and a breed is
only reported when the live model actually returned that label.
"""
import os
from PIL import Image, ImageDraw

DEFAULT_MODEL_ID = "pets-64nid-kbcey/1"

# Labels a live model may return that we are willing to treat as a breed.
# Public Universe breed models only cover a few breeds -- anything outside
# this list is reported as a generic detection, not a breed.
KNOWN_BREEDS = {
    "beagle", "bulldog", "corgi", "golden retriever", "labrador",
    "german shepherd", "poodle", "chihuahua", "french bulldog",
    "siberian husky", "tabby", "siamese", "persian",
}
SPECIES_LABELS = {"dog", "cat", "puppy", "kitten"}


def _parse_predictions(payload):
    """Normalise a Roboflow inference payload into detections."""
    detections = []
    preds = []
    if isinstance(payload, dict):
        preds = payload.get("predictions", []) or []
    for p in preds:
        if not isinstance(p, dict):
            continue
        label = str(p.get("class", p.get("label", ""))).strip().lower()
        if not label:
            continue
        try:
            conf = float(p.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            conf = 0.0
        detections.append({
            "label": label,
            "confidence": round(conf, 3),
            "bbox": {
                "x": p.get("x"), "y": p.get("y"),
                "width": p.get("width"), "height": p.get("height"),
            },
        })
    return detections


def _attributes_from_detections(detections):
    species = None
    breed = None
    best_conf = None
    for d in detections:
        label = d["label"]
        if label in SPECIES_LABELS and species is None:
            species = "dog" if label in {"dog", "puppy"} else "cat"
            best_conf = d["confidence"]
        if label in KNOWN_BREEDS and breed is None:
            breed = label
            best_conf = d["confidence"]
    return species, breed, best_conf


def analyse_image(image_path, manual=None, model_id=None, api_key=None):
    """Analyse one image. Returns a dict with mode live|demo.

    manual: dict of user-entered attributes (species/breed/colour/size)
    used ONLY in demo mode, and labelled as such.
    """
    manual = manual or {}
    model_id = model_id or os.environ.get("ROBOFLOW_MODEL_ID", DEFAULT_MODEL_ID)
    api_key = api_key if api_key is not None else os.environ.get("ROBOFLOW_API_KEY")

    def demo(reason):
        return {
            "mode": "demo",
            "model_id": model_id,
            "confidence": None,
            "species": (manual.get("species") or "").lower() or None,
            "breed": (manual.get("breed") or "").lower() or None,
            "colour": manual.get("colour"),
            "size": manual.get("size"),
            "detections": [],
            "note": ("DEMO fallback — not a model prediction. " + reason +
                     " Attributes below are from your manual entry; please confirm them."),
        }

    if not api_key:
        return demo("No ROBOFLOW_API_KEY set.")
    try:
        from inference_sdk import InferenceHTTPClient
        client = InferenceHTTPClient(
            api_url="https://serverless.roboflow.com", api_key=api_key)
        payload = client.infer(image_path, model_id=model_id)
    except Exception as exc:  # noqa: BLE001 - any failure -> honest demo fallback
        return demo(f"Live Roboflow call failed ({type(exc).__name__}: {exc}).")
    detections = _parse_predictions(payload)
    if not detections:
        return demo("Live model returned no detections.")
    species, breed, conf = _attributes_from_detections(detections)
    return {
        "mode": "live",
        "model_id": model_id,
        "confidence": conf,
        "species": species,
        "breed": breed,
        "colour": manual.get("colour"),
        "size": manual.get("size"),
        "detections": detections,
        "note": f"Live Roboflow prediction from model {model_id}.",
    }


def draw_boxes(image_path, detections, out_path):
    """Draw bounding boxes on a copy of the image. Returns out_path."""
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.size
    for d in detections:
        b = d.get("bbox") or {}
        try:
            cx, cy = float(b["x"]), float(b["y"])
            bw, bh = float(b["width"]), float(b["height"])
        except (TypeError, ValueError):
            continue
        x0, y0 = (cx - bw / 2) / 100 * w, (cy - bh / 2) / 100 * h
        x1, y1 = (cx + bw / 2) / 100 * w, (cy + bh / 2) / 100 * h
        draw.rectangle([x0, y0, x1, y1], outline=(220, 38, 38), width=3)
        draw.text((x0 + 2, y0 + 2), f"{d['label']} {d['confidence']:.2f}", fill=(220, 38, 38))
    img.save(out_path)
    return out_path

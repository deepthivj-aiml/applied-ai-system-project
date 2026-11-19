"""One-request, batched VLM comparisons for dog report photos."""
import base64
from collections import OrderedDict
import hashlib
import io
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, ImageOps

BASE_DIR = Path(__file__).parent
DEFAULT_MODEL = "gpt-6.1-terra"
MAX_CANDIDATE_PHOTOS = 12
_CACHE = OrderedDict()
_CACHE_LIMIT = 64


def _load_local_env():
    env_path = BASE_DIR / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def configured():
    _load_local_env()
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def _resolve_photo(value):
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path if path.is_file() else None


def _data_url(path):
    """Downsize/re-encode photos to a consistent JPEG data URL for the VLM."""
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((1024, 1024))
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=82, optimize=True)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _cache_key(model, query_path, candidates):
    paths = [query_path, *(path for _, path in candidates)]
    file_versions = []
    for path in paths:
        stat = path.stat()
        file_versions.append((str(path), stat.st_mtime_ns, stat.st_size))
    value = (model, tuple(file_versions), tuple(case_id for case_id, _ in candidates))
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()


def _extract_output_text(response_json):
    for item in response_json.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return content.get("text", "")
    raise ValueError("The VLM returned no structured photo comparison.")


def _request_photo_scores(query_data_url, labeled_candidates, api_key, model):
    content = [{
        "type": "input_text",
        "text": (
            "Compare the first image (the query dog) with each labeled candidate dog photo. "
            "Estimate visual identity similarity from the same individual dog's stable visible "
            "details: face and muzzle shape, ears, coat pattern, distinctive markings, scars, "
            "and body features. Do not score breed or generic coat color as strong identity "
            "evidence by itself. Return 100 for a very strong same-dog visual match and 0 for "
            "clearly different dogs. This is a visual similarity estimate, not a probability "
            "or confirmation. Return one result for every candidate case ID."
        ),
    }, {
        "type": "input_text",
        "text": "Query report photo:",
    }, {
        "type": "input_image",
        "image_url": query_data_url,
        "detail": "auto",
    }]
    for case_id, image_data_url in labeled_candidates:
        content.extend((
            {"type": "input_text", "text": f"Candidate case ID {case_id} photo:"},
            {"type": "input_image", "image_url": image_data_url, "detail": "auto"},
        ))

    schema = {
        "type": "object",
        "properties": {
            "matches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "case_id": {"type": "string"},
                        "photo_similarity_percent": {
                            "type": "integer", "minimum": 0, "maximum": 100,
                        },
                        "visual_reason": {"type": "string"},
                    },
                    "required": ["case_id", "photo_similarity_percent", "visual_reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["matches"],
        "additionalProperties": False,
    }
    body = {
        "model": model,
        "input": [{"role": "user", "content": content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "dog_photo_match_scores",
                "strict": True,
                "schema": schema,
            },
        },
        "max_output_tokens": 1200,
        "reasoning": {"effort": "low"},
        "store": False,
    }
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        response_data = json.loads(response.read().decode("utf-8"))
    model_text = _extract_output_text(response_data)
    parsed = json.loads(model_text)

    allowed_ids = {case_id for case_id, _ in labeled_candidates}
    scores = {}
    reasons = {}
    for result in parsed.get("matches", []):
        case_id = str(result.get("case_id", "")).upper()
        if case_id not in allowed_ids:
            continue
        try:
            score = max(0, min(100, int(result["photo_similarity_percent"])))
        except (KeyError, TypeError, ValueError):
            continue
        scores[case_id] = score
        reasons[case_id] = str(result.get("visual_reason", "")).strip()[:240]
    return scores, reasons


def compare_report_photos(query, candidates, *, api_key=None, model=None):
    """Compare up to 12 candidate photos in one VLM request, returning score metadata."""
    _load_local_env()
    api_key = api_key or os.getenv("OPENAI_API_KEY", "").strip()
    model = model or os.getenv("OPENAI_VLM_MODEL", DEFAULT_MODEL).strip()
    if not api_key:
        return {"status": "not_configured", "scores": {}, "reasons": {}, "compared": 0}

    query_path = _resolve_photo(query.get("photo"))
    if not query_path:
        return {"status": "missing_query_photo", "scores": {}, "reasons": {}, "compared": 0}

    candidates_with_photos = []
    for candidate in candidates:
        path = _resolve_photo(candidate.get("photo"))
        if path:
            candidates_with_photos.append((str(candidate.get("case_id", "")).upper(), path))
    if not candidates_with_photos:
        return {"status": "no_candidate_photos", "scores": {}, "reasons": {}, "compared": 0}

    compared_candidates = candidates_with_photos[:MAX_CANDIDATE_PHOTOS]
    omitted = max(0, len(candidates_with_photos) - len(compared_candidates))
    try:
        key = _cache_key(model, query_path, compared_candidates)
        if key in _CACHE:
            cached = dict(_CACHE[key])
            _CACHE.move_to_end(key)
            cached["status"] = "cached"
            cached["omitted"] = omitted
            return cached

        query_url = _data_url(query_path)
        candidate_urls = [
            (case_id, _data_url(path)) for case_id, path in compared_candidates
        ]
        scores, reasons = _request_photo_scores(query_url, candidate_urls, api_key, model)
    except HTTPError as exc:
        return {
            "status": "error", "scores": {}, "reasons": {}, "compared": 0,
            "message": f"VLM request failed (HTTP {exc.code}).",
        }
    except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "error", "scores": {}, "reasons": {}, "compared": 0,
            "message": f"Could not complete VLM photo matching ({type(exc).__name__}).",
        }
    except Exception as exc:  # keep search usable if VLM or response parsing fails
        return {
            "status": "error", "scores": {}, "reasons": {}, "compared": 0,
            "message": f"Could not complete VLM photo matching ({type(exc).__name__}).",
        }

    result = {
        "status": "ok", "scores": scores, "reasons": reasons,
        "compared": len(compared_candidates), "omitted": omitted, "model": model,
    }
    _CACHE[key] = dict(result)
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_LIMIT:
        _CACHE.popitem(last=False)
    return result

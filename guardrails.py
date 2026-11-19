"""Privacy, input, and AI-output guardrails for PawPal Reunite."""
from io import BytesIO
from pathlib import Path
import re

from PIL import Image, ImageOps, UnidentifiedImageError

from location import display_location, valid_latlon

LIKELY_MIN = 70
POSSIBLE_MIN = 50
MAX_REPORT_PHOTO_BYTES = 10 * 1024 * 1024
MAX_REPORT_PHOTO_PIXELS = 20_000_000

_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_PHONE_RE = re.compile(r"(?<!\w)\+?\d(?:[\s().-]*\d){8,14}(?!\w)")
_COORDINATE_RE = re.compile(
    r"(?<![\w.])[-+]?\d{1,2}\.\d{3,}\s*,\s*[-+]?\d{1,3}\.\d{3,}(?!\w)"
)
_STREET_ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+(?:[A-Z0-9.'-]+\s+){0,5}"
    r"(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|"
    r"court|ct|way|place|pl|terrace|ter)\b\.?"
    r"(?:\s+(?:apt|apartment|unit|suite|#)\s*[A-Z0-9-]+)?",
    re.IGNORECASE,
)
_PRIVATE_PROFILE_KEYS = {
    "email", "contact_email", "owner_email", "sender_email", "recipient_email",
    "private_email", "phone", "address", "street_address", "lat", "lon",
}


class GuardrailError(ValueError):
    """User content or uploaded media failed a PawPal safety check."""


def redact_private_info(value):
    """Redact emails, phone numbers, street addresses, and exact coordinate pairs."""
    text = str(value or "")
    for pattern in (_EMAIL_RE, _COORDINATE_RE, _PHONE_RE, _STREET_ADDRESS_RE):
        text = pattern.sub("[private info removed]", text)
    return " ".join(text.split())


def safe_public_text(value, max_length=None):
    """Return bounded text with common private contact/location data removed."""
    text = redact_private_info(value).strip()
    return text[:max_length] if max_length is not None else text


def normalize_report_photo(raw):
    """Validate a report photo, strip metadata, and return a bounded JPEG."""
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise GuardrailError("Choose a non-empty JPG, PNG, or WEBP dog photo.")
    if len(raw) > MAX_REPORT_PHOTO_BYTES:
        raise GuardrailError("Dog photos must be 10 MB or smaller.")

    try:
        with Image.open(BytesIO(raw)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise GuardrailError("Upload a valid JPG, PNG, or WEBP image.")
            if getattr(source, "n_frames", 1) != 1:
                raise GuardrailError("Animated images are not accepted as dog photos.")
            if source.width * source.height > MAX_REPORT_PHOTO_PIXELS:
                raise GuardrailError("Dog photos must be 20 megapixels or smaller.")
            source.verify()

        with Image.open(BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((2048, 2048))
            output = BytesIO()
            image.save(output, format="JPEG", quality=88, optimize=True)
            return output.getvalue()
    except GuardrailError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as exc:
        raise GuardrailError("The uploaded file is not a readable dog photo.") from exc


def resolve_report_photo(value, base_dir):
    """Resolve only existing photos inside the app's assets or user-upload folder."""
    if not value:
        return None
    base = Path(base_dir).resolve()
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    allowed_roots = ((base / "assets").resolve(), (base / "data" / "uploads").resolve())
    if not path.is_file() or not any(root == path or root in path.parents for root in allowed_roots):
        return None
    return path


def verdict_for_score(score):
    if score >= LIKELY_MIN:
        return "likely"
    if score >= POSSIBLE_MIN:
        return "possible"
    return "unlikely"


def match_warning(score):
    verdict = verdict_for_score(score)
    if verdict == "likely":
        return ("Higher-ranked possible match - verify in person with photos, "
                "vet records, and distinctive markings before claiming. "
                "This system does not confirm identity.")
    if verdict == "possible":
        return ("Possible lead - verify in person with photos and vet "
                "records. Do not rely on this score alone.")
    return ("Low-similarity lead - do not rely on this result. "
            "Use other evidence and verify in person before taking action.")


def safe_display(profile):
    """Public-safe profile copy: fuzzed location, redacted text, no contact data."""
    p = dict(profile)
    label = safe_public_text(p.get("place_label", ""), max_length=120)
    if valid_latlon(p.get("lat"), p.get("lon")):
        p["location_display"] = display_location(p["lat"], p["lon"], label)
    elif label:
        p["location_display"] = label
    p.pop("place_label", None)

    for key in list(p):
        lowered = key.lower()
        if (lowered in _PRIVATE_PROFILE_KEYS or lowered.endswith("_email")
                or "email" in lowered or lowered in {"phone_number", "home_address"}):
            p.pop(key, None)
    for key in ("owner_name", "breed", "colour", "size", "sex", "markings"):
        if key in p:
            p[key] = safe_public_text(p[key], max_length=500)
    return p


def contact_message(case_id, species, breed):
    message = (f"Hello, I am writing about case {safe_public_text(case_id, 32)} "
               f"({safe_public_text(species, 24)}, {safe_public_text(breed, 80)}). "
               "I think this may be my pet / a pet I found. "
               "Could we arrange to verify in person with photos and vet records? "
               "Please reply through PawPal Reunite using this case ID - "
               "do not share your phone or home address here.")
    return redact_private_info(message)


def check_low_confidence(score, vision_mode=None):
    """Return a warning string when a result should not be trusted, else an empty string."""
    if vision_mode == "demo":
        return ("Vision result is a DEMO fallback, not a model prediction. "
                "Attributes below came from your manual entry - please confirm them.")
    if score is not None and score < POSSIBLE_MIN:
        return "Low confidence - treat as unverified and check in person."
    return ""

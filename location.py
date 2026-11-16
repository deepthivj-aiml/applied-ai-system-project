"""Location helpers for PawPal Reunite.

Privacy rule: exact lat/lon are stored internally ONLY for matching.
Anything displayed to another user must go through fuzz_location() /
display_location() -- never a home address, never exact coordinates.
"""
import math

# Bay Area presets (public places, not home addresses)
PRESET_LOCATIONS = {
    "Central Park / Lake Elizabeth, Fremont": (37.5515, -121.9678),
    "Irvington, Fremont": (37.5249, -121.9521),
    "Mission San Jose, Fremont": (37.5319, -121.9196),
    "Niles, Fremont": (37.5774, -121.9815),
    "Warm Springs, Fremont": (37.4927, -121.9236),
    "Downtown San Jose": (37.3382, -121.8863),
    "Union City": (37.5934, -122.0438),
    "Newark, CA": (37.5297, -122.0402),
    "Milpitas": (37.4323, -121.8996),
    "Hayward": (37.6688, -122.0808),
}

FUZZ_GRID_DEG = 0.005  # ~500 m


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km between two lat/lon points."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def fuzz_latlon(lat, lon):
    """Snap coordinates to a ~500 m grid. Returns (fuzzed_lat, fuzzed_lon)."""
    return (round(lat / FUZZ_GRID_DEG) * FUZZ_GRID_DEG,
            round(lon / FUZZ_GRID_DEG) * FUZZ_GRID_DEG)


def display_location(lat, lon, place_label=""):
    """Public display string. NEVER contains exact coordinates."""
    flat, flon = fuzz_latlon(lat, lon)
    label = place_label or "Bay Area"
    return f"Near {label} (within ~500 m of {flat:.3f}, {flon:.3f})"


def distance_band_km(distance_km):
    if distance_km <= 2:
        return 15, "within 2 km"
    if distance_km <= 5:
        return 10, "2-5 km away"
    if distance_km <= 15:
        return 5, "5-15 km away"
    return 0, "more than 15 km away"


def valid_latlon(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    return -90 <= lat <= 90 and -180 <= lon <= 180

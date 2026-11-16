"""Keyword retrieval (RAG-lite) over local knowledge docs and pet profiles.

No external LLM is used: retrieval is keyword overlap over the curated
docs in data/knowledge/ and the profiles in data/lost_found_db.json.
Every answer cites the source file it came from.
"""
import json
import re
from pathlib import Path

BASE = Path(__file__).parent
DATA = BASE / "data"


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def load_knowledge():
    docs = []
    for path in sorted((DATA / "knowledge").glob("*.md")):
        docs.append({"source": f"data/knowledge/{path.name}",
                     "title": path.stem.replace("_", " ").title(),
                     "text": path.read_text(encoding="utf-8")})
    return docs


def load_profiles():
    with open(DATA / "lost_found_db.json", encoding="utf-8") as f:
        return json.load(f)


def retrieve(query, docs=None, top_k=3):
    """Return top_k docs ranked by keyword overlap with the query."""
    docs = docs if docs is not None else load_knowledge()
    qtok = _tokens(query)
    scored = []
    for doc in docs:
        overlap = qtok & _tokens(doc["text"] + " " + doc["title"])
        if overlap:
            scored.append({"source": doc["source"], "title": doc["title"],
                           "overlap": sorted(overlap),
                           "snippet": doc["text"][:400]})
    return sorted(scored, key=lambda d: len(d["overlap"]), reverse=True)[:top_k]


def retrieve_profiles(query_text, profiles=None, top_k=5):
    """Keyword retrieval over lost/found profiles (used for the Find tab)."""
    profiles = profiles if profiles is not None else load_profiles()
    qtok = _tokens(query_text)
    scored = []
    for p in profiles:
        hay = " ".join(str(p.get(k, "")) for k in
                       ("species", "breed", "colour", "size", "sex", "markings", "place_label"))
        overlap = qtok & _tokens(hay)
        if overlap:
            scored.append({"profile": p, "overlap": sorted(overlap)})
    return sorted(scored, key=lambda d: len(d["overlap"]), reverse=True)[:top_k]

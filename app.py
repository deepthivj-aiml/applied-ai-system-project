"""PawPal Reunite - Lost & Found Pet Matcher (Streamlit UI).
Tabs: Report Lost / Found | Find Matches | Map | Rewards & Anonymous Hints | How It Works / Testing
No money moves in this app. No phone/email is shown publicly.
"""
import sys
from pathlib import Path
import streamlit as st
sys.path.insert(0, str(Path(__file__).parent))
from agent import run_match_flow
from guardrails import match_warning
from location import PRESET_LOCATIONS, display_location, valid_latlon, fuzz_latlon
from retrieval import load_profiles
from rewards import create_pledge, mark_claimed, mark_hint_helpful, mark_reunited_and_eligible, submit_hint
from vision import analyse_image

st.set_page_config(page_title="PawPal Reunite", page_icon="🐾", layout="wide")
st.title("🐾 PawPal Reunite — Lost & Found Pet Matcher")
st.markdown("Upload a photo, share an **approximate** location, and get ranked possible matches with reasons and sources. **A match is never a confirmation of identity — always verify in person with photos and vet records.** No phone or email is shown publicly, and **no money moves in this app**.")
if "profiles" not in st.session_state:
    st.session_state.profiles = load_profiles()
if "hints" not in st.session_state:
    st.session_state.hints = {}
if "pledges" not in st.session_state:
    st.session_state.pledges = {}

def location_picker(prefix):
    st.markdown("#### 📍 Location (opt-in)")
    share = st.checkbox("Share approximate location publicly", value=True, key=prefix+"_share", help="Only a fuzzed location (~500 m) is ever displayed. Exact coordinates are used only for matching.")
    method = st.radio("How to set the location", ["Preset place", "Enter lat / lon", "Use my location (paste lat/lon)"], key=prefix+"_method", horizontal=True)
    if method == "Preset place":
        place = st.selectbox("Place", list(PRESET_LOCATIONS), key=prefix+"_preset")
        lat, lon = PRESET_LOCATIONS[place]
    else:
        st.caption("Find your coordinates in your phone's maps app (long-press a pin), then paste them here.")
        place = st.text_input("Place label (e.g. 'Near Lake Elizabeth')", "Near Lake Elizabeth", key=prefix+"_label")
        c1, c2 = st.columns(2)
        lat = c1.number_input("Latitude", value=37.5515, format="%.4f", key=prefix+"_lat")
        lon = c2.number_input("Longitude", value=-121.9678, format="%.4f", key=prefix+"_lon")
    st.caption(f"Public display would be: {display_location(lat, lon, place)}" if share else "Not shared publicly.")
    return lat, lon, place, share

def pet_form(prefix, status):
    c1, c2 = st.columns(2)
    species = c1.selectbox("Species", ["dog", "cat"], key=prefix+"_species")
    breed = c2.text_input("Breed (e.g. golden retriever)", "golden retriever", key=prefix+"_breed")
    colour = c1.text_input("Colour", "golden", key=prefix+"_colour")
    size = c2.selectbox("Size", ["small", "medium", "large"], key=prefix+"_size")
    sex = c1.selectbox("Sex", ["male", "female", "unknown"], key=prefix+"_sex")
    markings = c2.text_input("Distinctive markings (keywords)", "white chest patch", key=prefix+"_markings")
    date = c1.date_input("Date lost / found", key=prefix+"_date")
    name = c2.text_input("Pet name (or 'Unknown' if found)", "Biscuit", key=prefix+"_name")
    photo = st.file_uploader("Photo (optional)", type=["png", "jpg", "jpeg"], key=prefix+"_photo")
    lat, lon, place, share = location_picker(prefix)
    reward = None
    if status == "lost":
        amount = st.number_input("Optional reward pledge (USD, $0 = no reward, max $500)", min_value=0.0, max_value=500.0, value=0.0, step=10.0, key=prefix+"_reward")
        st.caption("A pledge is a promise only. The app moves NO money and takes NO payment details.")
        reward = amount
    return {"status": status, "name": name, "species": species, "breed": breed.lower(), "colour": colour.lower(), "size": size, "sex": sex, "markings": markings, "date": str(date), "lat": lat, "lon": lon, "place_label": place, "share_location": share, "photo": photo, "reward_pledge": reward}

def show_matches(result):
    if result["vision"]:
        v = result["vision"]
        st.subheader("🔍 Vision result")
        st.write(f"Mode: **{v['mode']}** | Model: {v['model_id']} | Confidence: {v['confidence']}")
        st.info(v["note"])
    st.subheader("📚 Retrieved guidance (sources shown)")
    for s in result["sources"]:
        st.write(f"- **{s['title']}** — {s['source']} (keywords: {', '.join(s['overlap'])})")
    st.subheader("🏆 Matches")
    if not result["matches"]:
        st.warning("No matches at or above 50. Try widening the search area or checking the attributes.")
        return
    for m in result["matches"]:
        p = m["profile"]
        with st.expander(f"{p['case_id']} — {p['breed']} — score {m['score']}/100"):
            st.write(f"**Status:** {p['status']} | **Colour:** {p['colour']} | **Size:** {p['size']} | **Sex:** {p['sex']}")
            st.write(f"**Location (public):** {m['public_profile'].get('location_display')}")
            st.write("**Why this matched:**")
            for r in m["reasons"]:
                st.write(f"- {r}")
            st.warning(match_warning(m["score"]))
            img = Path(__file__).parent / p.get("photo", "")
            if img.exists():
                st.image(str(img), caption=f"{p['case_id']} — sample illustration", width=240)
    if result["notifier"]:
        st.subheader("✉️ Draft contact message (not sent)")
        st.code(result["notifier"]["message"])

tabs = st.tabs(["Report Lost / Found", "Find Matches", "Map", "Rewards & Anonymous Hints", "How It Works / Testing"])
with tabs[0]:
    st.header("Report a lost or found pet")
    status = st.radio("This pet is:", ["lost", "found"], horizontal=True)
    form = pet_form("report", status)
    if st.button("Save report"):
        if not valid_latlon(form["lat"], form["lon"]):
            st.error("Invalid latitude/longitude.")
        else:
            new_id = f"LF-{len(st.session_state.profiles)+1:03d}"
            profile = {k: form[k] for k in ("status","name","species","breed","colour","size","sex","markings","date","lat","lon","place_label")}
            profile["case_id"] = new_id; profile["photo"] = ""
            st.session_state.profiles.append(profile)
            if status == "lost":
                st.session_state.pledges[new_id] = create_pledge(new_id, form["reward_pledge"] or 0)
            st.success(f"Saved as case **{new_id}**. Share only the case ID, never your phone or address.")
            st.write(f"Public location: {display_location(form['lat'], form['lon'], form['place_label'])}")
with tabs[1]:
    st.header("Find matches")
    st.write("Describe the pet you lost (or found) and upload a photo. The agent runs Intake → Vision → Retriever/Matcher → Human verification → Draft message.")
    query = pet_form("find", "lost")
    if st.button("Find matches"):
        img_path = None
        if query["photo"] is not None:
            img_path = f"/tmp/pawpal_upload_{query['photo'].name}"
            Path(img_path).write_bytes(query["photo"].getvalue())
            st.image(img_path, caption="Uploaded photo", width=240)
            v = analyse_image(img_path, manual=query)
            st.info(f"Vision: mode={v['mode']}, {v['note']}")
        result = run_match_flow(query, image_path=img_path, candidates=st.session_state.profiles)
        show_matches(result)
with tabs[2]:
    st.header("Map — fuzzed locations only")
    st.caption("Map pins use fuzzed locations (~500 m). Exact coordinates are never displayed.")
    import pandas as pd
    rows = []
    for p in st.session_state.profiles:
        flat, flon = fuzz_latlon(p["lat"], p["lon"])
        rows.append({"lat": flat, "lon": flon, "case_id": p["case_id"], "status": p["status"]})
    st.map(pd.DataFrame(rows))
    for p in st.session_state.profiles:
        st.write(f"- **{p['case_id']}** ({p['status']}, {p['species']}, {p['breed']}): {display_location(p['lat'], p['lon'], p['place_label'])}")
with tabs[3]:
    st.header("Rewards & Anonymous Hints")
    st.markdown("**No money moves in this app.** A reward is a pledge only — the owner honours it outside the app by their chosen method. Hints are anonymous: no name, phone, or email is collected or shown. The hint-submitter must save their claim code — there is no contact channel to send it later.")
    st.subheader("Submit an anonymous hint")
    case_id = st.text_input("Lost pet case ID (e.g. LF-001)", "LF-001")
    hint_text = st.text_area("Hint — where / when did you see this pet?")
    hint_loc = st.text_input("Hint location (optional)", "")
    if st.button("Submit hint anonymously"):
        try:
            hint = submit_hint(case_id, hint_text, location_label=hint_loc or None)
            st.session_state.hints.setdefault(case_id, []).append(hint)
            st.success(f"Hint submitted anonymously. Your hint ID is **{hint['hint_id']}**. Save it — if the owner marks it as leading to a reunion, the claim code will be shown with that hint ID.")
            st.code(f"Hint ID: {hint['hint_id']}")
        except ValueError as e:
            st.error(str(e))
    st.subheader("Hints for a case (owner view — no sender identity shown)")
    view_case = st.text_input("Case ID to view hints for", "LF-001", key="view_case")
    hints = st.session_state.hints.get(view_case, [])
    pledge = st.session_state.pledges.get(view_case)
    if pledge:
        st.write(f"Reward pledge for {view_case}: **${pledge['amount_usd']:.0f}** — status: {pledge['status']}")
    if not hints:
        st.info("No hints yet for this case.")
    for h in hints:
        with st.expander(f"{h['hint_id']} — helpful: {h['helpful']} — reward eligible: {h['reward_eligible']}"):
            st.write(h["hint_text"])
            if h.get("location_label"):
                st.write(f"Location: {h['location_label']}")
            st.write(f"Submitted: {h['submitted_at']}")
            if h.get("claim_code"):
                st.code(f"Claim code: {h['claim_code']} (save this code)")
            c1, c2, c3 = st.columns(3)
            if c1.button("Mark helpful", key="help_"+h["hint_id"]):
                h.update(mark_hint_helpful(h)); st.success("Marked helpful.")
            if c2.button("Confirm reunion — this hint led to it", key="reun_"+h["hint_id"]):
                try:
                    st.session_state.hints[view_case] = mark_reunited_and_eligible(hints, h["hint_id"], pledge)
                    st.success("Reward eligible! The claim code is shown on this hint. The owner honours it outside the app.")
                except ValueError as e:
                    st.error(str(e))
            if c3.button("Mark reward claimed", key="claim_"+h["hint_id"]):
                try:
                    st.session_state.pledges[view_case] = mark_claimed(pledge, h); st.success("Marked claimed.")
                except ValueError as e:
                    st.error(str(e))
with tabs[4]:
    st.header("How it works")
    st.markdown("1. **Intake** — pet attributes + opt-in approximate location.\n2. **Vision** — Roboflow (live, if `ROBOFLOW_API_KEY` is set) or a clearly-labelled demo fallback.\n3. **Retriever** — keyword retrieval over local breed / search guidance docs, with sources.\n4. **Matcher** — weighted score (species must match; breed 30, colour 20, size 10, sex 5, markings 15, date 5, distance 15). ≥70 likely, 50–69 possible, <50 not shown.\n5. **Verifier** — you confirm or correct the vision attributes before matching.\n6. **Notifier** — a draft contact message only. Nothing is sent.\n\n**Rewards:** optional $0–$500 pledge, anonymous hints by case ID only, one reward per case, claim code shown to both sides, honoured outside the app.")
    st.subheader("Testing")
    st.write("Run `python -m pytest -q` and `python eval/evaluate.py` — see README.md and eval/results.txt for the real outputs.")
    res = Path(__file__).parent / "eval" / "results.txt"
    if res.exists():
        st.code(res.read_text())

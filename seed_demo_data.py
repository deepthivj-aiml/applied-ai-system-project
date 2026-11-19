"""Seed one private-email lost/found dog pair and one private message for a demo.

Set PAWPAL_DEMO_LOST_EMAIL and PAWPAL_DEMO_FOUND_EMAIL in .env, then run:
    python seed_demo_data.py
The seed is idempotent. If SMTP is configured, it emails both demo addresses.
"""
import os
from pathlib import Path
import json
from urllib.parse import parse_qs, urlsplit

from email_service import relay_url, send_relay_notification
from location import PRESET_LOCATIONS
from message_store import create_thread, demo_thread_exists, get_thread, reply_to_thread
from report_store import ReportStoreError, _database_reports, _load_local_env, create_report, update_report_photo
from user_store import DEMO_USERS, ensure_demo_users

BASE_DIR = Path(__file__).parent
DEMO_LINKS_PATH = BASE_DIR / ".demo-message-links.json"

DEMO_REPORTS = [
    {
        "status": "lost", "breed": "golden retriever", "colour": "golden",
        "size": "large", "sex": "female",
        "markings": "white chest patch, blue collar",
        "place_label": "Central Park / Lake Elizabeth, Fremont",
        "photo": "assets/sample_pets/LF-001.png",
    },
    {
        "status": "found", "breed": "golden retriever", "colour": "golden",
        "size": "large", "sex": "female",
        "markings": "white chest patch, blue collar",
        "place_label": "Irvington, Fremont",
        "photo": "assets/sample_pets/LF-002.png",
    },
]


def seed_login_demo_data():
    """Create two local demo accounts, their complete reports, and a private sample chat."""
    ensure_demo_users()
    existing = _database_reports()
    account_data = [
        {
            "account": DEMO_USERS[0], "status": "lost",
            "breed": "golden retriever", "colour": "golden", "size": "large", "sex": "female",
            "markings": "white chest patch, blue collar",
            "place_label": "Central Park / Lake Elizabeth, Fremont",
            "photo": "assets/sample_pets/LF-001.png",
        },
        {
            "account": DEMO_USERS[1], "status": "found",
            "breed": "golden retriever", "colour": "golden", "size": "large", "sex": "female",
            "markings": "white chest patch, blue collar",
            "place_label": "Irvington, Fremont",
            "photo": "assets/sample_pets/LF-002.png",
        },
    ]
    cases = {}
    by_email = {str(item.get("contact_email", "")).lower(): item for item in existing}
    for entry in account_data:
        account = entry["account"]
        report = by_email.get(account["email"].lower())
        if report:
            cases[entry["status"]] = report["case_id"]
            continue
        latitude, longitude = PRESET_LOCATIONS[entry["place_label"]]
        report = create_report({
            **entry, "owner_name": account["username"], "contact_email": account["email"],
            "lat": latitude, "lon": longitude, "is_demo": True,
        })
        update_report_photo(report["case_id"], entry["photo"])
        cases[entry["status"]] = report["case_id"]

    lost_case, found_case = cases["lost"], cases["found"]
    if not demo_thread_exists(lost_case):
        thread = create_thread(
            lost_case, DEMO_USERS[1]["email"], DEMO_USERS[0]["email"],
            f"I found a golden retriever that may match lost report {lost_case}. "
            f"Please compare the white chest marking with found report {found_case}.",
            source_case_id=found_case, is_demo=True,
        )
        reply_to_thread(
            thread["recipient_token"],
            "Thanks. I will compare the blue collar and chest marking with my dog.",
        )
    return cases


def seed_demo_data():
    _load_local_env()
    lost_email = os.getenv("PAWPAL_DEMO_LOST_EMAIL", "").strip()
    found_email = os.getenv("PAWPAL_DEMO_FOUND_EMAIL", "").strip()
    if not lost_email or not found_email:
        raise ReportStoreError(
            "Set PAWPAL_DEMO_LOST_EMAIL and PAWPAL_DEMO_FOUND_EMAIL in .env before seeding."
        )

    existing = [report for report in _database_reports() if report.get("is_demo")]
    by_status = {report.get("status"): report for report in existing}
    seeded = {}
    emails = {"lost": lost_email, "found": found_email}
    for details in DEMO_REPORTS:
        status = details["status"]
        if status in by_status:
            seeded[status] = by_status[status]["case_id"]
            continue
        latitude, longitude = PRESET_LOCATIONS[details["place_label"]]
        report = create_report({
            **details,
            "species": "dog",
            "lat": latitude,
            "lon": longitude,
            "contact_email": emails[status],
            "is_demo": True,
        })
        update_report_photo(report["case_id"], details["photo"])
        seeded[status] = report["case_id"]

    lost_case = seeded["lost"]
    found_case = seeded["found"]
    if not demo_thread_exists(lost_case):
        thread = create_thread(
            lost_case, found_email, lost_email,
            f"[DEMO] I found a golden retriever that may match your lost report {lost_case}. "
            f"Please compare it with my found report {found_case}.",
            is_demo=True,
        )
        DEMO_LINKS_PATH.write_text(json.dumps({
            "lost_owner_url": relay_url(thread["recipient_token"]),
            "found_reporter_url": relay_url(thread["sender_token"]),
            "lost_notification_sent": False,
            "found_notification_sent": False,
        }, indent=2), encoding="utf-8")
    if DEMO_LINKS_PATH.is_file():
        links = json.loads(DEMO_LINKS_PATH.read_text(encoding="utf-8"))
        lost_token = parse_qs(urlsplit(links["lost_owner_url"]).query)["relay"][0]
        found_token = parse_qs(urlsplit(links["found_reporter_url"]).query)["relay"][0]
        thread_view = get_thread(lost_token)
        if thread_view and len(thread_view["messages"]) < 2:
            reply_to_thread(
                lost_token,
                "[DEMO] Thanks, I will compare the collar and chest marking with my lost report.",
            )
            thread_view = get_thread(lost_token)
        first_message = thread_view["messages"][0]["body"] if thread_view else "[DEMO] PawPal private message demo."

        if not links.get("lost_notification_sent"):
            result = send_relay_notification(
                lost_email, lost_case, first_message, lost_token,
            )
            links["lost_notification_sent"] = result["sent"]
        if not links.get("found_notification_sent"):
            result = send_relay_notification(
                found_email, lost_case, first_message, found_token,
                is_confirmation=True,
            )
            links["found_notification_sent"] = result["sent"]
        DEMO_LINKS_PATH.write_text(json.dumps(links, indent=2), encoding="utf-8")
        notifications_sent = (
            links["lost_notification_sent"] and links["found_notification_sent"]
        )
    else:
        notifications_sent = None

    return {"cases": seeded, "notifications_sent": notifications_sent}


if __name__ == "__main__":
    result = seed_demo_data()
    print("Demo lost case:", result["cases"]["lost"])
    print("Demo found case:", result["cases"]["found"])
    if result["notifications_sent"]:
        print("Private demo notifications were sent to both addresses.")
    elif result["notifications_sent"] is False:
        print("Demo message was saved locally; configure SMTP to email the demo participants.")
    else:
        print("Demo conversation already exists; its two views are available in the app.")
    print("Local private conversation links: available in the demo report UI.")

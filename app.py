"""Simple lost and found dog reports with case-ID based matching."""
from pathlib import Path
import sys
import time
import uuid

import streamlit as st

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from location import PRESET_LOCATIONS
from guardrails import (
    GuardrailError, match_warning, normalize_report_photo, resolve_report_photo,
    safe_display, safe_public_text,
)
from matcher import feature_similarity, find_matches
from report_store import (
    ReportStoreError, create_report, delete_owned_report, get_owned_report, get_report,
    list_reports, update_owned_report, update_report_photo,
)
from vlm_matcher import compare_report_photos
from email_service import (
    email_configured, relay_url, send_account_registration_otp, send_case_id_email, send_listing_otp,
    send_relay_notification,
)
from message_store import MessageStoreError, create_thread, get_thread, reply_to_thread
from message_drafts import generate_message_draft
from listing_otp_store import (
    ListingOtpError, invalidate_listing_otp, issue_listing_otp, verify_listing_otp,
)
from user_store import (
    DEMO_USERS, UserStoreError, authenticate, begin_registration, complete_registration,
    ensure_demo_users, invalidate_registration, username_for_email,
)
from seed_demo_data import seed_login_demo_data
from message_store import (
    issue_account_thread_token, list_threads_for_email, prune_expired_messages,
)


st.set_page_config(page_title="PawPal | Lost and found dogs", page_icon="🐾", layout="centered")
st.title("🐾 PawPal")
st.caption("Report a lost or found dog, or check for a possible match using its case ID.")


def _activate_user(user):
    st.session_state["auth_user"] = user
    st.session_state["account_chat_tokens"] = {}
    st.session_state.pop("teams_selected_chat", None)
    st.session_state.pop("signup_pending", None)


def auth_screen():
    st.subheader("Log in or register")
    st.caption("Each account has its own reports and private chat list.")
    mode = st.radio("Account", ["Log in", "Register"], horizontal=True, key="auth_mode")

    if mode == "Log in":
        with st.form("account_login", clear_on_submit=False):
            email = st.text_input("Email", type="email", key="login_email")
            password = st.text_input("Password", type="password", key="login_password")
            login = st.form_submit_button("Log in", type="primary")
        if login:
            try:
                user = authenticate(email, password)
                if user:
                    _activate_user(user)
                    st.rerun()
                st.error("Email or password did not match.")
            except UserStoreError as exc:
                st.error(str(exc))

        with st.expander("Local demo logins"):
            st.caption("Use either demo account to try the preloaded sample reports and chat.")
            demo_cols = st.columns(2)
            for index, demo_user in enumerate(DEMO_USERS):
                with demo_cols[index]:
                    st.markdown(f"**{demo_user['username']}**")
                    st.code(f"{demo_user['email']}\n{demo_user['password']}")
                    if st.button(f"Login as {demo_user['username']}", key=f"demo_login_{index}"):
                        try:
                            user = authenticate(demo_user["email"], demo_user["password"])
                            if user:
                                _activate_user(user)
                                st.rerun()
                            st.error("The local demo account could not be verified.")
                        except UserStoreError as exc:
                            st.error(str(exc))
    else:
        with st.form("account_register"):
            email = st.text_input("Email", type="email", key="register_email")
            username = st.text_input("Username", max_chars=40, key="register_username")
            password = st.text_input("Password (at least 10 characters)", type="password", key="register_password")
            confirmation = st.text_input("Confirm password", type="password", key="register_password_confirm")
            register = st.form_submit_button("Send verification code", type="primary")
        if register:
            if password != confirmation:
                st.error("The passwords do not match.")
            elif not email_configured():
                st.error("Registration needs email delivery to verify your address. Configure SMTP first.")
            else:
                try:
                    challenge = begin_registration(email, username, password)
                    delivery = send_account_registration_otp(email.strip(), challenge["code"])
                    if delivery["sent"]:
                        st.session_state["signup_pending"] = {
                            "email": email.strip().lower(), "otp_id": challenge["otp_id"],
                        }
                        st.success("A registration code was sent. It expires in 10 minutes.")
                    else:
                        invalidate_registration(challenge["otp_id"])
                        st.error(delivery["message"])
                except UserStoreError as exc:
                    st.error(str(exc))

        pending = st.session_state.get("signup_pending")
        if pending:
            with st.form("account_register_verify"):
                code = st.text_input("Six-digit email code", type="password", max_chars=6)
                verify = st.form_submit_button("Verify and create account", type="primary")
            if verify:
                try:
                    user = complete_registration(pending["email"], code)
                    if user:
                        _activate_user(user)
                        st.rerun()
                    st.error("The code is incorrect, expired, or already used.")
                except UserStoreError as exc:
                    st.error(str(exc))


def _current_user():
    return st.session_state.get("auth_user", {})


def _logout_user():
    for key in (
        "auth_user", "account_chat_tokens", "account_chat_owner",
        "teams_selected_chat", "active_message_report_id", "active_message_source_id",
        "active_message_origin", "listing_manage_verified", "listing_otp_pending",
        "communication_pair",
    ):
        st.session_state.pop(key, None)


def show_report(report, *, show_status=True):
    private_report = report
    report = safe_display(report)
    report["place_label"] = report.pop("location_display", "")
    photo_path = resolve_report_photo(report.get("photo"), BASE_DIR)
    photo = str(photo_path) if photo_path else None
    columns = st.columns([1, 2]) if photo else [None, None]
    if photo:
        with columns[0]:
            st.image(photo, width=300)
    with columns[1] if photo else st.container():
        title = f"{report.get('case_id', 'Report')}"
        if show_status:
            title += f" · {report.get('status', '').title()}"
        if report.get("is_demo"):
            title += " · Demo"
        st.markdown(f"**{title}**")
        details = [report.get("breed"), report.get("colour"), report.get("size")]
        details = [str(value).strip() for value in details if value]
        if report.get("sex"):
            details.append(f"{str(report['sex']).title()}")
        if details:
            st.text(" · ".join(details))
        if report.get("markings"):
            st.text(f"Markings: {report['markings']}")
        if report.get("place_label"):
            st.text(f"Location: {report['place_label']}")
        if report.get("photo_credit") and report.get("photo_source_url"):
            st.caption(f"Photo: [{report['photo_credit']}]({report['photo_source_url']}) · {report.get('photo_license', 'source license')}")
        if not photo:
            st.caption("No photo attached")
        owner_name = "Sample owner" if report.get("is_sample") else (
            report.get("owner_name") or username_for_email(private_report.get("contact_email"))
        )
        if not owner_name:
            owner_name = "Sample owner" if report.get("is_sample") else "Report owner"
        owner_name = safe_public_text(owner_name, 40) or "Report owner"
        st.text(f"Listed by {owner_name}")


def _persist_report_photo(case_id, normalized_bytes):
    """Store a validated, metadata-free JPEG under a generated local filename."""
    upload_dir = BASE_DIR / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{case_id}-" if case_id else "new-"
    destination = upload_dir / f"{prefix}{uuid.uuid4().hex}.jpg"
    try:
        destination.write_bytes(normalized_bytes)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise ReportStoreError("The photo could not be stored on this server.") from exc
    return str(destination.relative_to(BASE_DIR))


def add_report_tab():
    st.subheader("Add a dog report")
    account = _current_user()
    st.caption(
        "Your account email stays private. Reports will be saved under "
        f"{safe_public_text(account.get('username'), 40) or 'your account'}."
    )
    with st.form("add_dog_report", clear_on_submit=True):
        status = st.radio("Report type", ["Lost", "Found"], horizontal=True, key="new_report_status")
        breed = st.text_input("Breed or best guess", max_chars=80)
        colour = st.text_input("Colour", max_chars=80)
        size = st.selectbox("Size", ["Small", "Medium", "Large", "Unknown"])
        sex = st.selectbox("Sex", ["Unknown", "Female", "Male"])
        markings = st.text_input("Distinctive markings", max_chars=500)
        place = st.selectbox("Nearest public location", ["Choose a location"] + list(PRESET_LOCATIONS))
        photo_upload = st.file_uploader(
            "Dog photo (optional)", type=["jpg", "jpeg", "png", "webp"],
            help="Up to 10 MB. Use an image focused on the dog; photo metadata is removed before saving.",
        )
        submitted = st.form_submit_button("Save report", type="primary")

    if submitted:
        if not breed.strip() and not colour.strip() and not markings.strip() and not photo_upload:
            st.error("Add at least one dog detail or a photo.")
            return
        if place == "Choose a location":
            st.error("Choose the nearest public location so reports can be compared by location.")
            return
        email = str(account.get("email", "")).strip()
        if not email:
            st.error("Log in to add a report.")
            return

        photo_bytes = None
        if photo_upload:
            try:
                photo_bytes = normalize_report_photo(photo_upload.getvalue())
            except GuardrailError as exc:
                st.error(str(exc))
                return

        latitude, longitude = PRESET_LOCATIONS[place]
        report = {
            "status": status.lower(), "species": "dog", "breed": breed.strip(),
            "colour": colour.strip(), "size": size.lower(), "sex": sex.lower(),
            "markings": markings.strip(), "lat": latitude, "lon": longitude,
            "place_label": place, "contact_email": email,
            "owner_name": account.get("username", "PawPal member"),
        }
        photo_path = None
        try:
            if photo_bytes:
                photo_path = _persist_report_photo(None, photo_bytes)
            saved = create_report(report)
            if photo_path:
                saved["photo"] = photo_path
                update_report_photo(saved["case_id"], photo_path)
            st.success(f"Report saved. Your case ID is **{saved['case_id']}**. Keep it to check for matches.")
            if status.lower() == "lost" and email:
                email_result = send_case_id_email(email, saved["case_id"])
                if email_result["sent"]:
                    st.success(f"We emailed your case ID {saved['case_id']}.")
                else:
                    st.info(f"Email not sent: {email_result['message']}")
            show_report(saved)
        except (ReportStoreError, OSError) as exc:
            if photo_path:
                _remove_uploaded_photo(photo_path)
            st.error(str(exc))


def _save_private_attachment(upload):
    """Persist a user-selected, size-limited attachment in private local storage."""
    if upload is None:
        return None, None
    raw = upload.getvalue()
    if len(raw) > 5 * 1024 * 1024:
        raise MessageStoreError("Attachments must be 5 MB or smaller.")
    suffix = Path(upload.name).suffix.lower()
    signatures = {
        ".pdf": raw.startswith(b"%PDF-"),
        ".jpg": raw.startswith(b"\xff\xd8\xff"),
        ".jpeg": raw.startswith(b"\xff\xd8\xff"),
        ".png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
    }
    if suffix not in signatures or not signatures[suffix]:
        raise MessageStoreError("Attach a valid PDF, JPG, JPEG, or PNG file.")
    filename_stem = safe_public_text(Path(upload.name).stem, 100) or "attachment"
    if suffix in {".jpg", ".jpeg", ".png"}:
        try:
            raw = normalize_report_photo(raw)
        except GuardrailError as exc:
            raise MessageStoreError(str(exc)) from exc
        suffix = ".jpg"
        safe_name = f"{filename_stem}.jpg"
    else:
        safe_name = f"{filename_stem}{suffix}"
    directory = BASE_DIR / "data" / "uploads" / "private-messages"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{uuid.uuid4().hex}{suffix}"
    destination.write_bytes(raw)
    return str(destination.relative_to(BASE_DIR)), safe_public_text(safe_name, 128)


def _resolve_private_attachment(value):
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    path = path.resolve()
    private_dir = (BASE_DIR / "data" / "uploads" / "private-messages").resolve()
    return path if private_dir in path.parents and path.is_file() else None


def private_message_form(report, key_suffix, source_report=None):
    """Offer a private, editable message composer without showing report emails."""
    recipient_email = str(report.get("contact_email") or "").strip()
    sender = _current_user()
    sender_email = str(sender.get("email") or "").strip()
    if not recipient_email:
        st.caption("Private messaging is unavailable for this report because no contact email was provided.")
        return
    if not sender_email:
        st.caption("Log in to send a private message.")
        return

    with st.expander("Send a private message"):
        st.caption(
            f"Sending as {safe_public_text(sender.get('username'), 40) or 'your account'}. "
            "Emails stay private."
        )
        intent = st.selectbox(
            "Message type", ["Possible match", "Thank you / reunited"],
            key=f"message_intent_{key_suffix}",
        )
        attachment = st.file_uploader(
            "Optional attachment (PDF, JPG, or PNG; up to 5 MB)",
            type=["pdf", "jpg", "jpeg", "png"], key=f"message_file_{key_suffix}",
            help="Nothing is attached unless you choose a file here.",
        )
        body_key = f"message_body_{key_suffix}"
        if st.button("Generate editable draft", key=f"message_draft_{key_suffix}"):
            draft = generate_message_draft(
                intent, source_report=source_report, target_report=report,
                has_attachment=attachment is not None,
            )
            st.session_state[body_key] = draft["text"]
            st.session_state[f"message_draft_status_{key_suffix}"] = draft["generated"]
        if f"message_draft_status_{key_suffix}" in st.session_state:
            if st.session_state[f"message_draft_status_{key_suffix}"]:
                st.caption("AI draft generated. Edit it before sending.")
            else:
                st.caption("AI is unavailable without OPENAI_API_KEY; an editable sample draft was added.")
        with st.form(f"private_message_{key_suffix}"):
            message_body = st.text_area(
                "Message (up to 2,000 characters)", max_chars=2000, key=body_key,
            )
            sent = st.form_submit_button("Send privately", type="primary")

        if sent:
            attachment_path = attachment_name = None
            try:
                if source_report and source_report.get("contact_email") and not source_report.get("is_sample"):
                    owner = get_owned_report(source_report.get("case_id"), sender_email)
                    if not owner:
                        raise MessageStoreError(
                            "Enter the private email saved with your source report to message its owner."
                        )
                attachment_path, attachment_name = _save_private_attachment(attachment)
                thread = create_thread(
                    report.get("case_id"), sender_email, recipient_email, message_body,
                    source_case_id=(source_report or {}).get("case_id"),
                    attachment_path=attachment_path, attachment_name=attachment_name,
                )
            except MessageStoreError as exc:
                if attachment_path:
                    _remove_private_attachment(attachment_path)
                st.error(str(exc))
                return

            recipient_notice = send_relay_notification(
                thread["recipient_email"], thread["target_case_id"], thread["body"],
                thread["recipient_token"], attachment_path=thread["attachment_path"],
                attachment_name=thread["attachment_name"],
            )
            sender_notice = send_relay_notification(
                sender_email.strip(), thread["target_case_id"], thread["body"],
                thread["sender_token"], is_confirmation=True,
                attachment_path=thread["attachment_path"],
                attachment_name=thread["attachment_name"],
            )
            if recipient_notice["sent"]:
                st.success("Message sent to the report owner. Your email remains private.")
            else:
                st.warning("Message saved, but the report owner was not emailed. Configure SMTP to deliver it.")
            if sender_notice["sent"]:
                st.caption("A private conversation link was also sent to your email.")
            st.link_button("Open private conversation", relay_url(thread["sender_token"]))


def _remove_private_attachment(value):
    path = _resolve_private_attachment(value)
    if path:
        path.unlink()


def find_match_tab():
    st.subheader("Find a possible match")
    user_email = str(_current_user().get("email") or "").casefold()
    try:
        own_reports = [
            item for item in list_reports()
            if not item.get("is_sample")
            and str(item.get("contact_email") or "").casefold() == user_email
        ]
    except ReportStoreError as exc:
        st.error(str(exc))
        return
    if not own_reports:
        st.info("Add a lost or found report first. Its case ID will appear here for matching.")
        return

    def _report_option(item):
        return f"{item['case_id']} · {item['status'].title()} · {item.get('breed') or 'Dog'}"

    st.caption("Select your case ID. PawPal searches all opposite-type listings by dog features, photo, and location.")
    with st.form("find_by_case_id"):
        case_id = st.selectbox(
            "Your case ID", own_reports, format_func=_report_option,
        )
        submitted = st.form_submit_button("Find matches", type="primary")
    if not submitted:
        return
    try:
        report = get_owned_report(case_id["case_id"], user_email)
        if not report:
            st.error("No report found for that case ID.")
            return
        reports = list_reports()
    except ReportStoreError as exc:
        st.error(str(exc))
        return

    st.markdown("#### Your report")
    show_report(report)
    opposite_reports = [
        item for item in reports
        if item.get("case_id") != report.get("case_id")
        and item.get("status") != report.get("status")
        and item.get("species", "dog").lower() == "dog"
    ]
    opposite_reports.sort(
        key=lambda item: feature_similarity(report, item) or 0,
        reverse=True,
    )
    vlm_result = compare_report_photos(report, opposite_reports)
    if vlm_result["status"] in {"ok", "cached"}:
        scored_ids = set(vlm_result["scores"])
        compared_reports = [item for item in opposite_reports
                            if item.get("case_id", "").upper() in scored_ids]
        matches = find_matches(
            report, compared_reports,
            photo_scores=vlm_result["scores"],
            photo_reasons=vlm_result.get("reasons"),
        )
        st.caption(
            f"VLM photo similarity contributes 90%; dog details contribute 7%; "
            f"distance contributes up to 3 points. Compared {vlm_result['compared']} candidate photos "
            f"with {vlm_result['model']}. Photos are sent for visual comparison."
        )
        if vlm_result.get("omitted"):
            st.info(
                f"Compared the 12 best detail matches. {vlm_result['omitted']} other photos were not "
                "included in this VLM request; use Browse reports to inspect them."
            )
        if len(compared_reports) < len(opposite_reports):
            st.info(
                "Only reports with VLM photo scores are included in these automatic results. "
                "Use Search reports to inspect the full report list."
            )
    else:
        matches = find_matches(report, opposite_reports)
        if vlm_result["status"] == "not_configured":
            st.warning(
                "VLM photo matching is not configured. This search uses dog details and distance only. "
                "Set OPENAI_API_KEY in .env to enable image comparison."
            )
        elif vlm_result["status"] == "error":
            st.warning(
                f"{vlm_result.get('message', 'VLM comparison failed.')} "
                "This search uses dog details and distance only."
            )
        else:
            st.info("A usable photo was not available on both sides; this search uses dog details and distance only.")

    st.markdown("#### Possible matches")
    if not matches:
        st.info("No matching opposite-status dog reports found yet. Check again when more reports have been added.")
        return
    st.caption(
        "Match percentages rank similarity; they are not probabilities or identity confirmation. "
        "Missing photos, details, or locations are skipped, and the score is recalculated from the available evidence."
    )
    for item in matches:
        candidate = item["profile"]
        with st.container(border=True):
            candidate_label = "Lost case" if candidate.get("status") == "lost" else "Found case"
            st.markdown(f"### {item['score']}% match · {candidate_label} {candidate['case_id']}")
            st.warning(match_warning(item["score"]))
            show_report(candidate)
            if item.get("reasons"):
                st.text(" · ".join(item["reasons"]))
            private_message_form(
                candidate, f"match_{report['case_id']}_{candidate['case_id']}",
                source_report=report,
            )


def _begin_chat(target_report, source_report=None):
    target_id = target_report["case_id"]
    st.session_state["active_message_report_id"] = target_id
    st.session_state["active_message_origin"] = "communication" if source_report else "search"
    st.session_state["active_message_source_id"] = (source_report or {}).get("case_id")
    body_key = f"new_chat_body_{target_id}"
    draft = generate_message_draft(
        "Possible match", source_report=source_report, target_report=target_report,
    )
    st.session_state[body_key] = draft["text"]
    st.session_state[f"new_chat_draft_generated_{target_id}"] = draft["generated"]


@st.dialog("Private chat", width="large")
def report_message_dialog(case_id):
    try:
        target = get_report(case_id)
        source_id = st.session_state.get("active_message_source_id")
        source = get_report(source_id) if source_id else None
    except ReportStoreError as exc:
        st.error(str(exc))
        return
    if not target or not target.get("contact_email"):
        st.error("This report is no longer available for private messages.")
        return

    st.markdown(f"#### Message about report {target['case_id']}")
    show_report(target)
    suffix = str(case_id).replace("-", "_")
    if st.button("Close chat", key=f"close_new_chat_{suffix}"):
        st.session_state.pop("active_message_report_id", None)
        st.session_state.pop("active_message_source_id", None)
        st.session_state.pop("active_message_origin", None)
        st.rerun()
    current_user = _current_user()
    sender_email = str(current_user.get("email") or "").strip()
    st.caption(
        f"Sending as {safe_public_text(current_user.get('username'), 40) or 'your account'}; "
        "email stays hidden."
    )
    if source and source.get("contact_email") and not source.get("is_sample"):
        if source.get("contact_email", "").casefold() != sender_email.casefold():
            st.error("Your account does not own the source report.")
            return
        st.caption(f"Your found report: {source['case_id']}")

    body_key = f"new_chat_body_{case_id}"
    draft_button = "Regenerate AI draft"
    if st.button(draft_button, key=f"new_chat_generate_{suffix}"):
        draft = generate_message_draft("Possible match", source_report=source, target_report=target)
        st.session_state[body_key] = draft["text"]
        st.session_state[f"new_chat_draft_generated_{case_id}"] = draft["generated"]
    if st.session_state.get(f"new_chat_draft_generated_{case_id}"):
        st.caption("AI draft is editable. Change it before sending if needed.")
    else:
        st.caption("Edit this sample draft; live AI drafts need OPENAI_API_KEY.")

    attachment = st.file_uploader(
        "Optional attachment (PDF, JPG, or PNG; up to 5 MB)",
        type=["pdf", "jpg", "jpeg", "png"], key=f"new_chat_file_{suffix}",
        help="Nothing is attached unless you choose a file.",
    )
    with st.form(f"new_chat_send_{suffix}"):
        body = st.text_area("Message", max_chars=2000, key=body_key)
        send = st.form_submit_button("Send message", type="primary")

    if not send:
        return
    attachment_path = attachment_name = None
    try:
        if source and source.get("contact_email") and not source.get("is_sample"):
            owner = get_owned_report(source["case_id"], sender_email)
            if not owner:
                raise MessageStoreError("Use the private email saved with your source report.")
        attachment_path, attachment_name = _save_private_attachment(attachment)
        thread = create_thread(
            target["case_id"], sender_email, target["contact_email"], body,
            source_case_id=(source or {}).get("case_id"),
            attachment_path=attachment_path, attachment_name=attachment_name,
        )
    except (MessageStoreError, ReportStoreError) as exc:
        if attachment_path:
            _remove_private_attachment(attachment_path)
        st.error(str(exc))
        return

    st.session_state.setdefault("account_chat_tokens", {})[thread["thread_id"]] = thread["sender_token"]
    notice = send_relay_notification(
        thread["recipient_email"], thread["target_case_id"], thread["body"],
        thread["recipient_token"], attachment_path=thread["attachment_path"],
        attachment_name=thread["attachment_name"],
    )
    send_relay_notification(
        sender_email.strip(), thread["target_case_id"], thread["body"],
        thread["sender_token"], is_confirmation=True,
        attachment_path=thread["attachment_path"], attachment_name=thread["attachment_name"],
    )
    st.session_state["comms_notice"] = (
        "Message sent privately." if notice["sent"]
        else "Message saved. Email notification needs SMTP configuration."
    )
    st.session_state.pop("active_message_report_id", None)
    st.session_state.pop("active_message_source_id", None)
    st.session_state.pop("active_message_origin", None)
    st.rerun()


def reports_tab():
    st.subheader("Search reports")
    st.caption("Browse sample and saved dog reports. Choose a report card to message its owner or manage your listing.")
    try:
        reports = [report for report in list_reports()
                   if report.get("species", "dog").lower() == "dog"]
    except ReportStoreError as exc:
        st.error(str(exc))
        return
    if not reports:
        st.info("No reports yet. Add a lost or found dog report to get started.")
        return

    notice = st.session_state.pop("search_notice", None)
    if notice:
        st.success(notice)

    filters = st.columns([1, 2])
    status_filter = filters[0].selectbox("Type", ["All", "Found", "Lost"], key="browse_status")
    search_text = filters[1].text_input("Search case ID, breed, colour, markings, or location", key="browse_search")
    with st.expander("More filters"):
        filter_cols = st.columns(4)
        breed_options = sorted({str(item.get("breed", "")).strip() for item in reports if item.get("breed")})
        colour_options = sorted({str(item.get("colour", "")).strip() for item in reports if item.get("colour")})
        size_options = sorted({str(item.get("size", "")).strip().title() for item in reports if item.get("size")})
        location_options = sorted({str(item.get("place_label", "")).strip() for item in reports if item.get("place_label")})
        breed_filter = filter_cols[0].selectbox("Breed", ["Any"] + breed_options, key="browse_breed")
        colour_filter = filter_cols[1].selectbox("Colour", ["Any"] + colour_options, key="browse_colour")
        size_filter = filter_cols[2].selectbox("Size", ["Any"] + size_options, key="browse_size")
        location_filter = filter_cols[3].selectbox("Location", ["Any"] + location_options, key="browse_location")

    filtered = []
    for report in reports:
        if status_filter != "All" and report.get("status", "").lower() != status_filter.lower():
            continue
        if breed_filter != "Any" and report.get("breed") != breed_filter:
            continue
        if colour_filter != "Any" and report.get("colour") != colour_filter:
            continue
        if size_filter != "Any" and str(report.get("size", "")).title() != size_filter:
            continue
        if location_filter != "Any" and report.get("place_label") != location_filter:
            continue
        searchable = " ".join(str(report.get(key, "")) for key in
                               ("case_id", "breed", "colour", "markings", "place_label"))
        if search_text.strip() and search_text.strip().lower() not in searchable.lower():
            continue
        filtered.append(report)

    st.caption(f"{len(filtered)} report card(s)")
    for report in filtered:
        case_id = report.get("case_id", "Report")
        with st.container(border=True):
            show_report(report)
            action_cols = st.columns([1, 1, 3])
            if action_cols[0].button(
                "Message me", key=f"search_message_{case_id}",
                disabled=not bool(report.get("contact_email")),
                help=None if report.get("contact_email") else "This sample report has no private contact address.",
            ):
                _begin_chat(report)
            if action_cols[1].button(
                "Edit / delete", key=f"search_manage_{case_id}",
                disabled=not bool(report.get("contact_email")) or bool(report.get("is_sample")),
                help=("Sample listings are read-only." if report.get("is_sample") else None)
                if report.get("contact_email") else "Only saved reports with a private owner email can be managed.",
            ):
                if st.session_state.get("active_manage_case_id") == case_id:
                    st.session_state.pop("active_manage_case_id", None)
                    st.session_state.pop("listing_manage_verified", None)
                    st.session_state.pop("listing_otp_pending", None)
                else:
                    st.session_state["active_manage_case_id"] = case_id
                    st.session_state.pop("listing_manage_verified", None)
                    st.session_state.pop("listing_otp_pending", None)
            if report.get("is_demo"):
                action_cols[2].caption("Sample report · included for trying search and match")
            if st.session_state.get("active_manage_case_id") == case_id:
                manage_listing_card(report)

    active_chat = st.session_state.get("active_message_report_id")
    if active_chat and st.session_state.get("active_message_origin") == "search":
        report_message_dialog(active_chat)


def _available_chats():
    account = _current_user()
    email = str(account.get("email") or "").strip()
    if not email:
        return []
    if st.session_state.get("account_chat_owner") != email.casefold():
        st.session_state["account_chat_owner"] = email.casefold()
        st.session_state["account_chat_tokens"] = {}
    token_cache = st.session_state.setdefault("account_chat_tokens", {})
    chats = []
    relay_thread_id = None
    relay_token = st.query_params.get("relay", "")
    if relay_token:
        try:
            relayed = get_thread(relay_token)
            relay_thread_id = relayed.get("thread_id") if relayed else None
        except MessageStoreError:
            relay_thread_id = None
    try:
        threads = list_threads_for_email(email)
    except MessageStoreError as exc:
        st.error(str(exc))
        return []
    for thread_info in threads:
        thread_id = thread_info["thread_id"]
        token = token_cache.get(thread_id)
        if not token:
            try:
                token = issue_account_thread_token(thread_id, email)
            except MessageStoreError:
                continue
            token_cache[thread_id] = token
        try:
            thread = get_thread(token, _skip_retention_check=True)
        except MessageStoreError:
            continue
        if not thread:
            continue
        source_id = thread.get("source_case_id")
        target_id = thread["target_case_id"]
        if source_id:
            source_report = get_report(source_id)
            target_report = get_report(target_id)
            source_label = f"{source_id} · {(source_report or {}).get('breed') or 'Dog'}"
            target_label = f"{target_id} · {(target_report or {}).get('breed') or 'Dog'}"
            listing_label = f"{source_label} ↔ {target_label}"
        else:
            listing_label = f"Case {target_id}"
        username = safe_public_text(thread_info.get("other_username"), 40) or "PawPal member"
        chats.append({
            "token": token, "thread": thread,
            "label": f"{listing_label} · {username}",
            "updated_at": thread_info.get("updated_at"),
        })
        if thread_id == relay_thread_id:
            st.session_state["teams_selected_chat"] = token
    chats.sort(key=lambda item: item.get("updated_at"), reverse=True)
    return chats


def _render_chat_window(chat):
    thread = chat["thread"]
    token = chat["token"]
    st.text(f"Chat: {chat['label']}")
    st.caption("Private relay · email addresses are hidden")
    for message in thread["messages"]:
        own_message = message["sender_side"] == thread["side"]
        role = "user" if own_message else "assistant"
        with st.chat_message(role):
            st.caption("You" if own_message else "Other person")
            if message.get("body"):
                st.text(message["body"])
            path = _resolve_private_attachment(message.get("attachment_path"))
            if path:
                st.download_button(
                    f"Download {Path(message.get('attachment_name') or path.name).name}",
                    path.read_bytes(), file_name=Path(message.get("attachment_name") or path.name).name,
                    key=f"teams_download_{thread['thread_id']}_{message['message_id']}",
                )

    draft_key = f"teams_reply_body_{thread['thread_id']}_{thread['side']}"
    generated_key = f"teams_draft_generated_{thread['thread_id']}_{thread['side']}"
    if draft_key not in st.session_state:
        target = get_report(thread["target_case_id"]) or {"case_id": thread["target_case_id"]}
        source = get_report(thread.get("source_case_id")) if thread.get("source_case_id") else None
        draft = generate_message_draft(
            "reply", source_report=source, target_report=target,
            reply_context=[message.get("body", "") for message in thread["messages"]],
        )
        st.session_state[draft_key] = draft["text"]
        st.session_state[generated_key] = draft["generated"]
    if st.button("Regenerate AI reply", key=f"teams_generate_{thread['thread_id']}_{thread['side']}"):
        target = get_report(thread["target_case_id"]) or {"case_id": thread["target_case_id"]}
        source = get_report(thread.get("source_case_id")) if thread.get("source_case_id") else None
        draft = generate_message_draft(
            "reply", source_report=source, target_report=target,
            reply_context=[message.get("body", "") for message in thread["messages"]],
        )
        st.session_state[draft_key] = draft["text"]
        st.session_state[generated_key] = draft["generated"]
    draft_status = st.session_state.get(generated_key)
    if draft_status is True:
        st.caption("AI reply is editable before you send it.")
    elif draft_status is False:
        st.caption("AI needs OPENAI_API_KEY; edit the sample reply below before sending.")

    attachment = st.file_uploader(
        "Optional attachment (PDF, JPG, or PNG; up to 5 MB)",
        type=["pdf", "jpg", "jpeg", "png"], key=f"teams_reply_file_{thread['thread_id']}_{thread['side']}",
    )
    with st.form(f"teams_reply_form_{thread['thread_id']}_{thread['side']}"):
        body = st.text_area("Write a reply", max_chars=2000, key=draft_key)
        send = st.form_submit_button("Send", type="primary")
    if not send:
        return

    attachment_path = attachment_name = None
    try:
        attachment_path, attachment_name = _save_private_attachment(attachment)
        result = reply_to_thread(
            token, body, attachment_path=attachment_path, attachment_name=attachment_name,
        )
    except MessageStoreError as exc:
        if attachment_path:
            _remove_private_attachment(attachment_path)
        st.error(str(exc))
        return
    notification = send_relay_notification(
        result["notify_email"], result["target_case_id"], result["body"],
        result["notification_token"], is_reply=True,
        attachment_path=result["attachment_path"], attachment_name=result["attachment_name"],
    )
    st.session_state["comms_notice"] = (
        "Reply sent privately." if notification["sent"]
        else "Reply saved. Email notification needs SMTP configuration."
    )
    st.rerun()


def communications_tab():
    st.subheader("Communication")
    st.caption(
        "Your account's chats appear on the left. Names show usernames and case IDs; "
        "emails stay private. Messages are stored in PostgreSQL and removed after seven days."
    )
    notice = st.session_state.pop("comms_notice", None)
    if notice:
        st.info(notice)

    try:
        reports = [item for item in list_reports()
                   if item.get("species", "dog").lower() == "dog"]
    except ReportStoreError as exc:
        st.error(str(exc))
        return

    current_email = str(_current_user().get("email") or "").casefold()
    with st.expander("Start a chat: found report → lost report"):
        found_cases = sorted(
            [item for item in reports if item.get("status") == "found" and item.get("contact_email")
             and not item.get("is_sample") and item.get("contact_email", "").casefold() == current_email],
            key=lambda item: item.get("case_id", ""),
        )
        lost_cases = sorted(
            [item for item in reports if item.get("status") == "lost" and item.get("contact_email")
             and not item.get("is_sample") and item.get("contact_email", "").casefold() != current_email],
            key=lambda item: item.get("case_id", ""),
        )
        if not found_cases or not lost_cases:
            st.caption("This account needs a found listing, and another account must have a lost listing.")
        else:
            with st.form("communications_start_chat"):
                found_id = st.selectbox("Your found report", [item["case_id"] for item in found_cases])
                lost_id = st.selectbox("Lost report", [item["case_id"] for item in lost_cases])
                start = st.form_submit_button("Open chat")
            if start:
                try:
                    found = get_owned_report(found_id, current_email)
                    lost = get_report(lost_id)
                except ReportStoreError as exc:
                    st.error(str(exc))
                    found = lost = None
                if not found or found.get("status") != "found":
                    st.error("The found report and private email did not match.")
                elif not lost or lost.get("status") != "lost":
                    st.error("Choose a saved lost report.")
                else:
                    _begin_chat(lost, found)

    if (st.session_state.get("active_message_report_id")
            and st.session_state.get("active_message_origin") == "communication"):
        report_message_dialog(st.session_state["active_message_report_id"])

    chats = _available_chats()
    left, right = st.columns([1, 2], gap="large")
    with left:
        st.markdown("#### Chats")
        if not chats:
            st.caption("No chats yet. Use Message me on a report card to start one.")
            selected = None
        else:
            token_options = [chat["token"] for chat in chats]
            labels = {chat["token"]: chat["label"] for chat in chats}
            relay_token = st.query_params.get("relay", "")
            current_token = st.session_state.get("teams_selected_chat")
            if relay_token in token_options:
                current_token = relay_token
            if current_token not in token_options:
                current_token = token_options[0]
            st.session_state["teams_selected_chat"] = current_token
            default_index = token_options.index(current_token)
            selected = st.radio(
                "Chats", token_options, index=default_index, format_func=lambda token: labels[token],
                key="teams_selected_chat", label_visibility="collapsed",
            )
    with right:
        if selected:
            chat = next(item for item in chats if item["token"] == selected)
            _render_chat_window(chat)
        else:
            st.info("Select a chat to see its messages here.")


def _remove_uploaded_photo(photo):
    if not photo:
        return
    photo_path = Path(photo)
    if not photo_path.is_absolute():
        photo_path = BASE_DIR / photo_path
    upload_dir = (BASE_DIR / "data" / "uploads").resolve()
    resolved = photo_path.resolve()
    if upload_dir in resolved.parents and resolved.is_file():
        resolved.unlink()


def manage_listing_card(report):
    case_id = report["case_id"]
    st.markdown(f"#### Manage {case_id}")
    verified = st.session_state.get("listing_manage_verified", {})
    authorized = (
        verified.get("case_id") == case_id
        and verified.get("expires_at", 0) > time.time()
    )

    if not authorized:
        otp_email_key = f"otp_email_{case_id}"
        if otp_email_key not in st.session_state:
            st.session_state[otp_email_key] = str(_current_user().get("email") or "")
        with st.form(f"otp_request_form_{case_id}"):
            owner_email = st.text_input(
                "Email saved with this report", type="email",
                placeholder="you@example.com", key=otp_email_key,
            )
            request_code = st.form_submit_button("Email me a verification code")
        if request_code:
            try:
                owner = get_owned_report(case_id, owner_email)
                if not owner:
                    st.error("That email does not match this report.")
                elif owner_email.strip().casefold() != str(_current_user().get("email", "")).casefold():
                    st.error("Log in to the account that owns this report before requesting a code.")
                elif not email_configured():
                    st.error("Email verification is not available until SMTP is configured.")
                else:
                    issued = issue_listing_otp(case_id, owner_email)
                    delivery = send_listing_otp(owner_email, case_id, issued["code"])
                    if delivery["sent"]:
                        st.session_state["listing_otp_pending"] = {
                            "case_id": case_id, "email": owner_email.strip(),
                            "otp_id": issued["otp_id"],
                        }
                        st.success("A six-digit code was sent. It expires in 10 minutes.")
                    else:
                        invalidate_listing_otp(issued["otp_id"])
                        st.error(delivery["message"])
            except (ReportStoreError, ListingOtpError) as exc:
                st.error(str(exc))

        pending = st.session_state.get("listing_otp_pending", {})
        if pending.get("case_id") == case_id:
            with st.form(f"otp_verify_form_{case_id}"):
                code = st.text_input(
                    "Six-digit email code", type="password", max_chars=6,
                    key=f"otp_code_{case_id}",
                )
                verify = st.form_submit_button("Verify and unlock listing")
            if verify:
                try:
                    if verify_listing_otp(case_id, pending["email"], code):
                        st.session_state["listing_manage_verified"] = {
                            "case_id": case_id, "email": pending["email"],
                            "expires_at": time.time() + 600,
                        }
                        st.session_state.pop("listing_otp_pending", None)
                        st.rerun()
                    st.error("The code is incorrect, expired, or already used.")
                except ListingOtpError as exc:
                    st.error(str(exc))
        return

    owner_email = verified["email"]
    try:
        owned_report = get_owned_report(case_id, owner_email)
    except ReportStoreError as exc:
        st.error(str(exc))
        return
    if not owned_report:
        st.session_state.pop("listing_manage_verified", None)
        st.error("This listing is no longer available to that email.")
        return

    st.caption("Email verified. Edit or remove this report for the next 10 minutes.")
    current_status = owned_report.get("status", "lost").title()
    current_size = owned_report.get("size", "unknown").title()
    current_sex = owned_report.get("sex", "unknown").title()
    locations = list(PRESET_LOCATIONS)
    if owned_report.get("place_label") and owned_report["place_label"] not in locations:
        locations.insert(0, owned_report["place_label"])
    with st.form(f"edit_managed_listing_{case_id}"):
        status = st.radio(
            "Report type", ["Lost", "Found"],
            index=0 if current_status == "Lost" else 1, horizontal=True,
            key=f"manage_status_{case_id}",
        )
        breed = st.text_input("Breed or best guess", owned_report.get("breed", ""), max_chars=80, key=f"manage_breed_{case_id}")
        colour = st.text_input("Colour", owned_report.get("colour", ""), max_chars=80, key=f"manage_colour_{case_id}")
        size_options = ["Unknown", "Small", "Medium", "Large"]
        sex_options = ["Unknown", "Female", "Male"]
        size = st.selectbox(
            "Size", size_options,
            index=size_options.index(current_size) if current_size in size_options else 0,
            key=f"manage_size_{case_id}",
        )
        sex = st.selectbox(
            "Sex", sex_options,
            index=sex_options.index(current_sex) if current_sex in sex_options else 0,
            key=f"manage_sex_{case_id}",
        )
        markings = st.text_input(
            "Distinctive markings", owned_report.get("markings", ""), max_chars=500,
            key=f"manage_markings_{case_id}",
        )
        place = st.selectbox(
            "Nearest public location", locations,
            index=locations.index(owned_report.get("place_label"))
            if owned_report.get("place_label") in locations else 0,
            key=f"manage_place_{case_id}",
        )
        new_photo = st.file_uploader(
            "Replace dog photo (optional)", type=["jpg", "jpeg", "png", "webp"],
            help="Up to 10 MB. Use an image focused on the dog; photo metadata is removed before saving.",
            key=f"manage_photo_{case_id}",
        )
        save_changes = st.form_submit_button("Save changes", type="primary")

    if save_changes:
        latitude, longitude = PRESET_LOCATIONS.get(place, (owned_report["lat"], owned_report["lon"]))
        photo_path = None
        if new_photo:
            try:
                photo_bytes = normalize_report_photo(new_photo.getvalue())
                photo_path = _persist_report_photo(case_id, photo_bytes)
            except GuardrailError as exc:
                st.error(str(exc))
                return
            except ReportStoreError as exc:
                st.error(str(exc))
                return
        try:
            update_owned_report(case_id, owner_email, {
                "status": status.lower(), "breed": breed, "colour": colour,
                "size": size.lower(), "sex": sex.lower(), "markings": markings,
                "lat": latitude, "lon": longitude, "place_label": place, "photo": photo_path,
            })
            if photo_path and owned_report.get("photo") != photo_path:
                _remove_uploaded_photo(owned_report.get("photo"))
            st.success(f"Listing {case_id} updated.")
        except ReportStoreError as exc:
            if photo_path:
                _remove_uploaded_photo(photo_path)
            st.error(str(exc))

    with st.form(f"delete_managed_listing_{case_id}"):
        confirm_remove = st.checkbox(
            f"Permanently remove case {case_id} and its private messages",
            key=f"confirm_remove_listing_{case_id}",
        )
        remove_listing = st.form_submit_button("Delete listing")
    if remove_listing:
        if not confirm_remove:
            st.error("Check the box to confirm deletion.")
            return
        try:
            deleted = delete_owned_report(case_id, owner_email)
            _remove_uploaded_photo(deleted.get("photo"))
            for path in deleted.get("private_attachment_paths", []):
                _remove_private_attachment(path)
            st.session_state.pop("listing_manage_verified", None)
            st.session_state.pop("active_manage_case_id", None)
            st.session_state["search_notice"] = f"Listing {case_id} was deleted."
            st.rerun()
        except ReportStoreError as exc:
            st.error(str(exc))



if not st.session_state.get("pawpal_bootstrap_complete"):
    try:
        ensure_demo_users()
        seed_login_demo_data()
        prune_expired_messages()
        st.session_state["pawpal_bootstrap_complete"] = True
        st.session_state.pop("pawpal_bootstrap_error", None)
    except (ReportStoreError, UserStoreError, MessageStoreError) as exc:
        st.session_state["pawpal_bootstrap_error"] = str(exc)

bootstrap_error = st.session_state.get("pawpal_bootstrap_error")
if bootstrap_error:
    st.error(bootstrap_error)

if not _current_user():
    auth_screen()
    st.stop()

account = _current_user()
st.sidebar.text(safe_public_text(account.get("username"), 40) or "PawPal member")
st.sidebar.caption("Your email is private to your account.")
st.sidebar.button("Log out", key="pawpal_logout", on_click=_logout_user)

relay_token = st.query_params.get("relay", "")


def _record_tab_change():
    current = st.session_state.get("main_nav_tabs")
    previous = st.session_state.get("active_nav_tab")
    if current and previous and current != previous:
        history = st.session_state.setdefault("tab_navigation_history", [])
        history.append(previous)
        st.session_state["tab_navigation_history"] = history[-30:]
    if current:
        st.session_state["active_nav_tab"] = current


def _go_back_tab():
    history = st.session_state.setdefault("tab_navigation_history", [])
    current = st.session_state.get("main_nav_tabs", "Add report")
    target = history.pop() if history else ("Add report" if current != "Add report" else None)
    if target:
        st.session_state["active_nav_tab"] = target
        st.session_state["main_nav_tabs"] = target


def _render_back_button(page_name):
    history = st.session_state.get("tab_navigation_history", [])
    current = st.session_state.get("main_nav_tabs", page_name)
    if current != page_name:
        return
    target = history[-1] if history else ("Add report" if current != "Add report" else None)
    if target:
        st.button(f"← Back to {target}", key=f"back_from_{page_name}", on_click=_go_back_tab)


tab_labels = ["Add report", "Find match", "Search report", "Communication"]
default_tab = "Communication" if relay_token else "Add report"
if st.session_state.get("main_nav_tabs") in tab_labels:
    default_tab = st.session_state["main_nav_tabs"]
if "active_nav_tab" not in st.session_state:
    st.session_state["active_nav_tab"] = default_tab

add_tab, match_tab, reports_tab_view, comms_tab = st.tabs(
    tab_labels, default=default_tab, key="main_nav_tabs", on_change=_record_tab_change,
)
if add_tab.open:
    with add_tab:
        _render_back_button("Add report")
        add_report_tab()
if match_tab.open:
    with match_tab:
        _render_back_button("Find match")
        find_match_tab()
if reports_tab_view.open:
    with reports_tab_view:
        _render_back_button("Search report")
        reports_tab()
if comms_tab.open:
    with comms_tab:
        _render_back_button("Communication")
        communications_tab()

"""PostgreSQL persistence for lost and found dog reports."""
import json
import os
from pathlib import Path
import re

from guardrails import resolve_report_photo, safe_public_text
from location import valid_latlon
from retrieval import load_profiles

BASE_DIR = Path(__file__).parent
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS pawpal_reports (
    case_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('lost', 'found')),
    species TEXT NOT NULL DEFAULT 'dog',
    breed TEXT NOT NULL DEFAULT '',
    colour TEXT NOT NULL DEFAULT '',
    size TEXT NOT NULL DEFAULT 'unknown',
    sex TEXT NOT NULL DEFAULT 'unknown',
    markings TEXT NOT NULL DEFAULT '',
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    place_label TEXT NOT NULL,
    photo TEXT,
    contact_email TEXT,
    owner_name TEXT NOT NULL DEFAULT '',
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


class ReportStoreError(RuntimeError):
    """Database setup or report persistence failed."""


def _clean_report_fields(report):
    """Validate bounded public report fields before they reach PostgreSQL."""
    size = safe_public_text(report.get("size") or "unknown", 16).lower()
    sex = safe_public_text(report.get("sex") or "unknown", 16).lower()
    if size not in {"unknown", "small", "medium", "large"}:
        raise ReportStoreError("Choose small, medium, large, or unknown for dog size.")
    if sex not in {"unknown", "female", "male"}:
        raise ReportStoreError("Choose female, male, or unknown for dog sex.")
    place_label = safe_public_text(report.get("place_label"), 120)
    if not place_label:
        raise ReportStoreError("Choose a public location without contact details or a street address.")
    return {
        "breed": safe_public_text(report.get("breed"), 80),
        "colour": safe_public_text(report.get("colour"), 80),
        "size": size,
        "sex": sex,
        "markings": safe_public_text(report.get("markings"), 500),
        "place_label": place_label,
        "owner_name": safe_public_text(report.get("owner_name"), 40),
    }


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


def _connect():
    _load_local_env()
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise ReportStoreError("PostgreSQL is not configured. Set DATABASE_URL in .env.")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise ReportStoreError("PostgreSQL support is missing. Install requirements.txt.") from exc
    try:
        connection = psycopg.connect(database_url, row_factory=dict_row, connect_timeout=5)
        with connection.cursor() as cursor:
            cursor.execute(_SCHEMA)
            cursor.execute(
                "ALTER TABLE pawpal_reports ADD COLUMN IF NOT EXISTS "
                "is_demo BOOLEAN NOT NULL DEFAULT FALSE"
            )
            cursor.execute(
                "ALTER TABLE pawpal_reports ADD COLUMN IF NOT EXISTS "
                "owner_name TEXT NOT NULL DEFAULT ''"
            )
        connection.commit()
        return connection
    except Exception as exc:
        raise ReportStoreError(
            "Could not connect to PostgreSQL. Check DATABASE_URL and that the local database is running."
        ) from exc


def _database_reports():
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM pawpal_reports ORDER BY created_at DESC, case_id")
            return [dict(row) for row in cursor.fetchall()]
    except Exception as exc:
        raise ReportStoreError("Could not load reports from PostgreSQL.") from exc
    finally:
        connection.close()


def list_reports():
    """Return built-in sample reports followed by reports saved by users."""
    reports = [dict(
        profile, contact_email="sample-owner@example.invalid", is_demo=True, is_sample=True,
    ) for profile in load_profiles()]
    photo_cases_path = BASE_DIR / "data" / "real_photo_test_reports.json"
    if photo_cases_path.is_file():
        try:
            photo_cases = json.loads(photo_cases_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReportStoreError("Could not load real-photo demo reports.") from exc
        reports.extend(dict(
            profile, contact_email="", is_demo=True, is_sample=True,
        ) for profile in photo_cases)
    reports.extend(_database_reports())
    return reports


def get_report(case_id):
    """Find a report by its case ID, ignoring letter case and surrounding spaces."""
    sought = str(case_id or "").strip().upper()
    if not sought:
        return None
    for report in list_reports():
        if str(report.get("case_id", "")).upper() == sought:
            return report
    return None


def get_owned_report(case_id, owner_email):
    """Return a saved report only when its private owner email also matches."""
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM pawpal_reports WHERE UPPER(case_id)=UPPER(%s) "
                "AND LOWER(contact_email)=LOWER(%s)",
                (str(case_id or "").strip(), str(owner_email or "").strip()),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as exc:
        raise ReportStoreError("Could not verify report ownership in PostgreSQL.") from exc
    finally:
        connection.close()


def create_report(report):
    """Save a report and return it with its generated case ID."""
    status = str(report.get("status", "")).strip().lower()
    if status not in {"lost", "found"}:
        raise ReportStoreError("Report type must be lost or found.")
    contact_email = str(report.get("contact_email") or "").strip()
    if not _EMAIL_RE.fullmatch(contact_email):
        raise ReportStoreError("Enter a valid private email address.")
    try:
        latitude, longitude = float(report["lat"]), float(report["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReportStoreError("Choose a valid location before saving the report.") from exc
    if not valid_latlon(latitude, longitude):
        raise ReportStoreError("Choose a valid public location before saving the report.")
    fields = _clean_report_fields(report)

    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE SEQUENCE IF NOT EXISTS pawpal_case_id_seq START WITH 11
            """)
            cursor.execute("SELECT nextval('pawpal_case_id_seq') AS next_case")
            case_id = f"LF-{cursor.fetchone()['next_case']:03d}"
            cursor.execute("""
                INSERT INTO pawpal_reports
                    (case_id, status, species, breed, colour, size, sex, markings,
                     lat, lon, place_label, contact_email, owner_name, is_demo)
                VALUES (%s, %s, 'dog', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (
                case_id, status, fields["breed"], fields["colour"], fields["size"],
                fields["sex"], fields["markings"], latitude, longitude, fields["place_label"],
                contact_email, fields["owner_name"],
                bool(report.get("is_demo", False)),
            ))
            saved = dict(cursor.fetchone())
        connection.commit()
        return saved
    except ReportStoreError:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise ReportStoreError("Could not save the report to PostgreSQL.") from exc
    finally:
        connection.close()


def update_report_photo(case_id, photo_path):
    """Attach a locally saved photo path to a report."""
    resolved_photo = resolve_report_photo(photo_path, BASE_DIR)
    if not resolved_photo:
        raise ReportStoreError("Choose an existing report photo inside the app's photo folders.")
    stored_photo = str(resolved_photo.relative_to(BASE_DIR.resolve()))
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE pawpal_reports SET photo=%s WHERE case_id=%s RETURNING case_id",
                (stored_photo, str(case_id).strip().upper()),
            )
            if cursor.fetchone() is None:
                raise ReportStoreError("Report was saved, but its photo could not be attached.")
        connection.commit()
    except ReportStoreError:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise ReportStoreError("Could not save the report photo reference.") from exc
    finally:
        connection.close()


def update_owned_report(case_id, owner_email, report):
    """Edit dog details for a saved report after checking its private owner email."""
    status = str(report.get("status", "")).strip().lower()
    if status not in {"lost", "found"}:
        raise ReportStoreError("Report type must be lost or found.")
    try:
        latitude, longitude = float(report["lat"]), float(report["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReportStoreError("Choose a valid location before saving the report.") from exc
    if not valid_latlon(latitude, longitude):
        raise ReportStoreError("Choose a valid public location before saving the report.")
    fields = _clean_report_fields(report)
    photo_value = str(report.get("photo") or "").strip()
    if photo_value:
        resolved_photo = resolve_report_photo(photo_value, BASE_DIR)
        if not resolved_photo:
            raise ReportStoreError("Choose an existing report photo inside the app's photo folders.")
        photo_value = str(resolved_photo.relative_to(BASE_DIR.resolve()))

    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE pawpal_reports
                SET status=%s, breed=%s, colour=%s, size=%s, sex=%s,
                    markings=%s, lat=%s, lon=%s, place_label=%s, photo=COALESCE(%s, photo)
                WHERE UPPER(case_id)=UPPER(%s) AND LOWER(contact_email)=LOWER(%s)
                RETURNING *
            """, (
                status, fields["breed"], fields["colour"], fields["size"],
                fields["sex"], fields["markings"], latitude, longitude, fields["place_label"],
                photo_value or None,
                str(case_id or "").strip(), str(owner_email or "").strip(),
            ))
            row = cursor.fetchone()
            if row is None:
                raise ReportStoreError("No saved report matched that case ID and private email.")
            saved = dict(row)
        connection.commit()
        return saved
    except ReportStoreError:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise ReportStoreError("Could not update the report in PostgreSQL.") from exc
    finally:
        connection.close()


def delete_owned_report(case_id, owner_email):
    """Delete a saved report and its message threads after owner-email verification."""
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM pawpal_reports WHERE UPPER(case_id)=UPPER(%s) "
                "AND LOWER(contact_email)=LOWER(%s) FOR UPDATE",
                (str(case_id or "").strip(), str(owner_email or "").strip()),
            )
            row = cursor.fetchone()
            if row is None:
                raise ReportStoreError("No saved report matched that case ID and private email.")
            deleted = dict(row)
            cursor.execute("SELECT to_regclass('pawpal_message_threads') AS table_name")
            if cursor.fetchone()["table_name"] is not None:
                cursor.execute(
                    "ALTER TABLE pawpal_message_threads ADD COLUMN IF NOT EXISTS source_case_id TEXT"
                )
                cursor.execute("SELECT to_regclass('pawpal_messages') AS table_name")
                if cursor.fetchone()["table_name"] is not None:
                    cursor.execute(
                        "ALTER TABLE pawpal_messages ADD COLUMN IF NOT EXISTS attachment_path TEXT"
                    )
                    cursor.execute("""
                        SELECT m.attachment_path
                        FROM pawpal_messages m
                        JOIN pawpal_message_threads t USING (thread_id)
                        WHERE UPPER(t.target_case_id)=UPPER(%s)
                           OR UPPER(COALESCE(t.source_case_id, ''))=UPPER(%s)
                    """, (deleted["case_id"], deleted["case_id"]))
                    deleted["private_attachment_paths"] = [
                        item["attachment_path"] for item in cursor.fetchall()
                        if item["attachment_path"]
                    ]
                cursor.execute(
                    "DELETE FROM pawpal_message_threads WHERE UPPER(target_case_id)=UPPER(%s) "
                    "OR UPPER(COALESCE(source_case_id, ''))=UPPER(%s)",
                    (deleted["case_id"], deleted["case_id"]),
                )
            cursor.execute("DELETE FROM pawpal_reports WHERE case_id=%s", (deleted["case_id"],))
        connection.commit()
        return deleted
    except ReportStoreError:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise ReportStoreError("Could not remove the report from PostgreSQL.") from exc
    finally:
        connection.close()

"""Account registration and password verification using PostgreSQL and PBKDF2."""
import hashlib
import hmac
import re
import secrets
import uuid

from guardrails import safe_public_text
from report_store import _connect

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PASSWORD_ITERATIONS = 310_000
_OTP_ITERATIONS = 120_000


class UserStoreError(RuntimeError):
    """Account creation or login validation failure."""


def ensure_schema(connection=None):
    owns_connection = connection is None
    connection = connection or _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pawpal_users (
                    email TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pawpal_signup_otps (
                    otp_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    username TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    otp_salt TEXT NOT NULL,
                    otp_hash TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL,
                    used_at TIMESTAMPTZ
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS pawpal_signup_otps_email_idx
                ON pawpal_signup_otps(email, created_at DESC)
            """)
        connection.commit()
    except Exception as exc:
        connection.rollback()
        raise UserStoreError("Could not prepare account storage in PostgreSQL.") from exc
    finally:
        if owns_connection:
            connection.close()


def _password_digest(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PASSWORD_ITERATIONS,
    ).hex()


def _otp_digest(code, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", code.encode("ascii"), bytes.fromhex(salt), _OTP_ITERATIONS,
    ).hex()


def authenticate(email, password):
    email = str(email or "").strip().lower()
    connection = _connect()
    try:
        ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT email, username, password_salt, password_hash "
                "FROM pawpal_users WHERE LOWER(email)=LOWER(%s)", (email,),
            )
            user = cursor.fetchone()
        if not user:
            return None
        candidate = _password_digest(str(password or ""), user["password_salt"])
        if not hmac.compare_digest(candidate, user["password_hash"]):
            return None
        return {"email": user["email"], "username": user["username"]}
    except UserStoreError:
        raise
    except Exception as exc:
        raise UserStoreError("Could not check the login in PostgreSQL.") from exc
    finally:
        connection.close()


def begin_registration(email, username, password):
    """Create an email-verification challenge without exposing a stored password."""
    email = str(email or "").strip().lower()
    username = str(username or "").strip()
    password = str(password or "")
    if not _EMAIL_RE.fullmatch(email):
        raise UserStoreError("Enter a valid email address.")
    if not 2 <= len(username) <= 40:
        raise UserStoreError("Username must be between 2 and 40 characters.")
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]{1,39}", username)
            or safe_public_text(username) != username):
        raise UserStoreError("Use a public username without email addresses, phone numbers, or other contact details.")
    if len(password) < 10:
        raise UserStoreError("Password must have at least 10 characters.")

    password_salt = secrets.token_hex(16)
    password_hash = _password_digest(password, password_salt)
    otp_salt = secrets.token_hex(16)
    code = f"{secrets.randbelow(1_000_000):06d}"
    otp_hash = _otp_digest(code, otp_salt)
    otp_id = uuid.uuid4().hex
    connection = _connect()
    try:
        ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pawpal_users WHERE LOWER(email)=LOWER(%s)", (email,))
            if cursor.fetchone():
                raise UserStoreError("An account already exists for that email. Log in instead.")
            cursor.execute("""
                SELECT COUNT(*) AS request_count FROM pawpal_signup_otps
                WHERE LOWER(email)=LOWER(%s) AND created_at > NOW() - INTERVAL '1 hour'
            """, (email,))
            if cursor.fetchone()["request_count"] >= 5:
                raise UserStoreError("Too many registration codes requested. Try again in an hour.")
            cursor.execute("""
                UPDATE pawpal_signup_otps SET used_at=NOW()
                WHERE LOWER(email)=LOWER(%s) AND used_at IS NULL
            """, (email,))
            cursor.execute("""
                INSERT INTO pawpal_signup_otps
                    (otp_id, email, username, password_salt, password_hash,
                     otp_salt, otp_hash, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW() + INTERVAL '10 minutes')
            """, (otp_id, email, username, password_salt, password_hash, otp_salt, otp_hash))
        connection.commit()
        return {"otp_id": otp_id, "code": code}
    except UserStoreError:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise UserStoreError("Could not start account registration.") from exc
    finally:
        connection.close()


def invalidate_registration(otp_id):
    connection = _connect()
    try:
        ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute("UPDATE pawpal_signup_otps SET used_at=NOW() WHERE otp_id=%s", (otp_id,))
        connection.commit()
    except Exception as exc:
        connection.rollback()
        raise UserStoreError("Could not cancel account verification.") from exc
    finally:
        connection.close()


def complete_registration(email, code):
    email = str(email or "").strip().lower()
    candidate = str(code or "").strip()
    connection = _connect()
    try:
        ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT otp_id, username, password_salt, password_hash, otp_salt,
                       otp_hash, attempts, expires_at, used_at
                FROM pawpal_signup_otps WHERE LOWER(email)=LOWER(%s)
                ORDER BY created_at DESC LIMIT 1 FOR UPDATE
            """, (email,))
            challenge = cursor.fetchone()
            if (not challenge or challenge["used_at"] is not None
                    or challenge["expires_at"] <= _utc_now() or challenge["attempts"] >= 5):
                connection.commit()
                return None
            valid = (
                len(candidate) == 6 and candidate.isascii() and candidate.isdigit()
                and hmac.compare_digest(_otp_digest(candidate, challenge["otp_salt"]), challenge["otp_hash"])
            )
            if not valid:
                cursor.execute("""
                    UPDATE pawpal_signup_otps
                    SET attempts=attempts+1,
                        used_at=CASE WHEN attempts+1 >= 5 THEN NOW() ELSE used_at END
                    WHERE otp_id=%s
                """, (challenge["otp_id"],))
                connection.commit()
                return None
            cursor.execute("""
                INSERT INTO pawpal_users (email, username, password_salt, password_hash)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (email) DO NOTHING
                RETURNING email, username
            """, (email, challenge["username"], challenge["password_salt"], challenge["password_hash"]))
            user = cursor.fetchone()
            if not user:
                cursor.execute("UPDATE pawpal_signup_otps SET used_at=NOW() WHERE otp_id=%s", (challenge["otp_id"],))
                connection.commit()
                raise UserStoreError("An account already exists for that email. Log in instead.")
            cursor.execute("UPDATE pawpal_signup_otps SET used_at=NOW() WHERE otp_id=%s", (challenge["otp_id"],))
        connection.commit()
        return {"email": user["email"], "username": user["username"]}
    except UserStoreError:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise UserStoreError("Could not finish account registration.") from exc
    finally:
        connection.close()


def username_for_email(email):
    if not email:
        return None
    connection = _connect()
    try:
        ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute("SELECT username FROM pawpal_users WHERE LOWER(email)=LOWER(%s)", (str(email).strip(),))
            row = cursor.fetchone()
            return row["username"] if row else None
    except Exception as exc:
        raise UserStoreError("Could not find the account username.") from exc
    finally:
        connection.close()


DEMO_USERS = (
    {"email": "demo.lost@example.invalid", "username": "Lost Demo", "password": "LostDemo!234"},
    {"email": "demo.finder@example.invalid", "username": "Found Demo", "password": "FoundDemo!234"},
)


def ensure_demo_users():
    """Create public, reserved-domain demo accounts if they are absent."""
    connection = _connect()
    try:
        ensure_schema(connection)
        with connection.cursor() as cursor:
            for user in DEMO_USERS:
                cursor.execute("SELECT 1 FROM pawpal_users WHERE email=%s", (user["email"],))
                if cursor.fetchone():
                    continue
                salt = secrets.token_hex(16)
                cursor.execute("""
                    INSERT INTO pawpal_users (email, username, password_salt, password_hash)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (email) DO NOTHING
                """, (user["email"], user["username"], salt, _password_digest(user["password"], salt)))
        connection.commit()
    except Exception as exc:
        connection.rollback()
        raise UserStoreError("Could not prepare the local demo accounts.") from exc
    finally:
        connection.close()


def _utc_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)

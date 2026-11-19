"""Rate-limited, single-use OTPs for editing or removing report listings."""
import hashlib
import hmac
import secrets
import uuid

from report_store import _connect


class ListingOtpError(RuntimeError):
    """Listing OTP persistence or validation failure."""


def _ensure_schema(connection):
    with connection.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pawpal_listing_otps (
                otp_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                email TEXT NOT NULL,
                salt TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                expires_at TIMESTAMPTZ NOT NULL,
                used_at TIMESTAMPTZ
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS pawpal_listing_otps_owner_idx
            ON pawpal_listing_otps(case_id, email, created_at DESC)
        """)
    connection.commit()


def _derive(code, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", code.encode("ascii"), bytes.fromhex(salt), 120_000,
    ).hex()


def issue_listing_otp(case_id, email):
    """Create a 6-digit code that expires in ten minutes; return it once for email delivery."""
    case_id = str(case_id or "").strip().upper()
    email = str(email or "").strip()
    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(16)
    otp_id = uuid.uuid4().hex
    digest = _derive(code, salt)
    connection = _connect()
    try:
        _ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) AS request_count FROM pawpal_listing_otps
                WHERE case_id=%s AND LOWER(email)=LOWER(%s)
                  AND created_at > NOW() - INTERVAL '1 hour'
            """, (case_id, email))
            if cursor.fetchone()["request_count"] >= 5:
                raise ListingOtpError("Too many code requests. Try again in an hour.")
            cursor.execute("""
                UPDATE pawpal_listing_otps SET used_at=NOW()
                WHERE case_id=%s AND LOWER(email)=LOWER(%s) AND used_at IS NULL
            """, (case_id, email))
            cursor.execute("""
                INSERT INTO pawpal_listing_otps
                    (otp_id, case_id, email, salt, code_hash, expires_at)
                VALUES (%s, %s, %s, %s, %s, NOW() + INTERVAL '10 minutes')
            """, (otp_id, case_id, email, salt, digest))
        connection.commit()
        return {"otp_id": otp_id, "code": code}
    except ListingOtpError:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise ListingOtpError("Could not create an email verification code.") from exc
    finally:
        connection.close()


def invalidate_listing_otp(otp_id):
    connection = _connect()
    try:
        _ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE pawpal_listing_otps SET used_at=NOW() WHERE otp_id=%s",
                (str(otp_id),),
            )
        connection.commit()
    except Exception as exc:
        connection.rollback()
        raise ListingOtpError("Could not invalidate the verification code.") from exc
    finally:
        connection.close()


def verify_listing_otp(case_id, email, code):
    """Consume a matching unexpired code after at most five attempts."""
    connection = _connect()
    try:
        _ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT otp_id, salt, code_hash, attempts, expires_at, used_at
                FROM pawpal_listing_otps
                WHERE case_id=%s AND LOWER(email)=LOWER(%s)
                ORDER BY created_at DESC LIMIT 1 FOR UPDATE
            """, (str(case_id or "").strip().upper(), str(email or "").strip()))
            row = cursor.fetchone()
            if row is None or row["used_at"] is not None or row["expires_at"] <= _utc_now():
                connection.commit()
                return False
            if row["attempts"] >= 5:
                connection.commit()
                return False
            candidate = str(code or "").strip()
            valid = (
                len(candidate) == 6 and candidate.isascii() and candidate.isdigit()
                and hmac.compare_digest(_derive(candidate, row["salt"]), row["code_hash"])
            )
            if valid:
                cursor.execute(
                    "UPDATE pawpal_listing_otps SET used_at=NOW() WHERE otp_id=%s",
                    (row["otp_id"],),
                )
            else:
                cursor.execute("""
                    UPDATE pawpal_listing_otps
                    SET attempts=attempts+1,
                        used_at=CASE WHEN attempts+1 >= 5 THEN NOW() ELSE used_at END
                    WHERE otp_id=%s
                """, (row["otp_id"],))
        connection.commit()
        return valid
    except Exception as exc:
        connection.rollback()
        raise ListingOtpError("Could not verify the email code.") from exc
    finally:
        connection.close()


def _utc_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)

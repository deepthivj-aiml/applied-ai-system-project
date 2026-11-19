"""Private PostgreSQL-backed message threads for report owners."""
import hashlib
from pathlib import Path
import re
import secrets

from report_store import _connect

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_EMAIL_IN_MESSAGE_RE = re.compile(
    r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])"
)
_SCHEMA = """
CREATE TABLE IF NOT EXISTS pawpal_message_threads (
    thread_id TEXT PRIMARY KEY,
    target_case_id TEXT NOT NULL,
    source_case_id TEXT,
    sender_email TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS pawpal_message_tokens (
    token_hash TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES pawpal_message_threads(thread_id) ON DELETE CASCADE,
    side TEXT NOT NULL CHECK (side IN ('sender', 'recipient')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS pawpal_messages (
    message_id BIGSERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES pawpal_message_threads(thread_id) ON DELETE CASCADE,
    sender_side TEXT NOT NULL CHECK (sender_side IN ('sender', 'recipient')),
    body TEXT NOT NULL,
    attachment_path TEXT,
    attachment_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS pawpal_message_threads_case_idx
    ON pawpal_message_threads(target_case_id);
CREATE INDEX IF NOT EXISTS pawpal_messages_thread_idx
    ON pawpal_messages(thread_id, created_at);
"""


class MessageStoreError(RuntimeError):
    """Message validation, ownership, or storage failure."""


def _token_hash(token):
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _ensure_schema(connection):
    with connection.cursor() as cursor:
        for statement in _SCHEMA.split(";"):
            if statement.strip():
                cursor.execute(statement)
        cursor.execute(
            "ALTER TABLE pawpal_message_threads ADD COLUMN IF NOT EXISTS "
            "is_demo BOOLEAN NOT NULL DEFAULT FALSE"
        )
        cursor.execute(
            "ALTER TABLE pawpal_message_threads ADD COLUMN IF NOT EXISTS source_case_id TEXT"
        )
        cursor.execute(
            "ALTER TABLE pawpal_messages ADD COLUMN IF NOT EXISTS attachment_path TEXT"
        )
        cursor.execute(
            "ALTER TABLE pawpal_messages ADD COLUMN IF NOT EXISTS attachment_name TEXT"
        )
    connection.commit()


def _validate_message(email, body, attachment_name=None):
    email = str(email or "").strip()
    body = str(body or "").strip()
    if not _EMAIL_RE.fullmatch(email):
        raise MessageStoreError("Enter a valid private email address for replies.")
    if not body and not attachment_name:
        raise MessageStoreError("Write a message or attach a file before sending.")
    if len(body) > 2000:
        raise MessageStoreError("Messages must be 2,000 characters or fewer.")
    body = _EMAIL_IN_MESSAGE_RE.sub("[email hidden]", body)
    return email, body


def create_thread(
    target_case_id, sender_email, recipient_email, body, *, source_case_id=None,
    attachment_path=None, attachment_name=None, is_demo=False,
):
    """Start a private thread and return one-time opaque access links for both sides."""
    prune_expired_messages()
    sender_email, body = _validate_message(sender_email, body, attachment_name)
    recipient_email = str(recipient_email or "").strip()
    if not _EMAIL_RE.fullmatch(recipient_email):
        raise MessageStoreError("The report owner has no valid private email for messages.")
    if sender_email.casefold() == recipient_email.casefold():
        raise MessageStoreError("Use a different private email from the report owner's email.")

    thread_id = secrets.token_urlsafe(18)
    sender_token = secrets.token_urlsafe(32)
    recipient_token = secrets.token_urlsafe(32)
    connection = _connect()
    try:
        _ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) AS sent_count FROM pawpal_message_threads
                WHERE target_case_id=%s AND is_demo=FALSE
                  AND created_at > NOW() - INTERVAL '1 hour'
            """, (str(target_case_id).strip().upper(),))
            if cursor.fetchone()["sent_count"] >= 3:
                raise MessageStoreError("This report has reached its limit of 3 new conversations per hour.")
            cursor.execute("""
                INSERT INTO pawpal_message_threads
                    (thread_id, target_case_id, source_case_id, sender_email, recipient_email, is_demo)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                thread_id, str(target_case_id).strip().upper(),
                str(source_case_id or "").strip().upper() or None,
                sender_email, recipient_email, bool(is_demo),
            ))
            cursor.execute("""
                INSERT INTO pawpal_message_tokens (token_hash, thread_id, side)
                VALUES (%s, %s, 'sender'), (%s, %s, 'recipient')
            """, (_token_hash(sender_token), thread_id, _token_hash(recipient_token), thread_id))
            cursor.execute("""
                INSERT INTO pawpal_messages
                    (thread_id, sender_side, body, attachment_path, attachment_name)
                VALUES (%s, 'sender', %s, %s, %s)
            """, (thread_id, body, attachment_path, attachment_name))
        connection.commit()
        return {
            "thread_id": thread_id,
            "sender_token": sender_token,
            "recipient_token": recipient_token,
            "recipient_email": recipient_email,
            "target_case_id": str(target_case_id).strip().upper(),
            "source_case_id": str(source_case_id or "").strip().upper() or None,
            "body": body,
            "attachment_path": attachment_path,
            "attachment_name": attachment_name,
            "is_demo": bool(is_demo),
        }
    except MessageStoreError:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise MessageStoreError("Could not save the private message.") from exc
    finally:
        connection.close()


def get_thread(token, *, _skip_retention_check=False):
    """Return a thread visible to a valid email-link token, without either email."""
    if not _skip_retention_check:
        prune_expired_messages()
    connection = _connect()
    try:
        _ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT t.thread_id, t.target_case_id, t.source_case_id, t.is_demo, tok.side
                FROM pawpal_message_tokens tok
                JOIN pawpal_message_threads t USING (thread_id)
                WHERE tok.token_hash=%s
            """, (_token_hash(token),))
            thread = cursor.fetchone()
            if thread is None:
                return None
            cursor.execute("""
                SELECT message_id, sender_side, body, attachment_path, attachment_name, created_at
                FROM pawpal_messages
                WHERE thread_id=%s ORDER BY created_at, message_id
            """, (thread["thread_id"],))
            messages = [dict(row) for row in cursor.fetchall()]
        return {
            "thread_id": thread["thread_id"],
            "target_case_id": thread["target_case_id"],
            "source_case_id": thread["source_case_id"],
            "is_demo": thread["is_demo"],
            "side": thread["side"],
            "messages": messages,
        }
    except Exception as exc:
        raise MessageStoreError("Could not load this private conversation.") from exc
    finally:
        connection.close()


def reply_to_thread(token, body, *, attachment_path=None, attachment_name=None):
    """Append a reply and issue a fresh notification link for the other participant."""
    prune_expired_messages()
    body = str(body or "").strip()
    if not body and not attachment_name:
        raise MessageStoreError("Write a message or attach a file before sending.")
    if len(body) > 2000:
        raise MessageStoreError("Messages must be 2,000 characters or fewer.")
    body = _EMAIL_IN_MESSAGE_RE.sub("[email hidden]", body)

    connection = _connect()
    try:
        _ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT t.thread_id, t.target_case_id, t.sender_email, t.recipient_email,
                       t.is_demo, tok.side
                FROM pawpal_message_tokens tok
                JOIN pawpal_message_threads t USING (thread_id)
                WHERE tok.token_hash=%s
                FOR UPDATE OF t
            """, (_token_hash(token),))
            thread = cursor.fetchone()
            if thread is None:
                raise MessageStoreError("This private conversation link is invalid or expired.")
            side = thread["side"]
            cursor.execute("""
                SELECT COUNT(*) AS sent_count FROM pawpal_messages
                WHERE thread_id=%s AND sender_side=%s
                  AND created_at > NOW() - INTERVAL '5 minutes'
            """, (thread["thread_id"], side))
            if cursor.fetchone()["sent_count"] >= 5:
                raise MessageStoreError("Please wait before sending more messages in this conversation.")
            cursor.execute("""
                INSERT INTO pawpal_messages
                    (thread_id, sender_side, body, attachment_path, attachment_name)
                VALUES (%s, %s, %s, %s, %s)
            """, (thread["thread_id"], side, body, attachment_path, attachment_name))

            other_side = "recipient" if side == "sender" else "sender"
            other_token = secrets.token_urlsafe(32)
            cursor.execute("""
                INSERT INTO pawpal_message_tokens (token_hash, thread_id, side)
                VALUES (%s, %s, %s)
            """, (_token_hash(other_token), thread["thread_id"], other_side))
            destination = thread["recipient_email"] if side == "sender" else thread["sender_email"]
        connection.commit()
        return {
            "thread_id": thread["thread_id"],
            "target_case_id": thread["target_case_id"],
            "is_demo": thread["is_demo"],
            "notify_email": destination,
            "notification_token": other_token,
            "body": body,
            "attachment_path": attachment_path,
            "attachment_name": attachment_name,
            "reply_side": other_side,
        }
    except MessageStoreError:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise MessageStoreError("Could not save the reply.") from exc
    finally:
        connection.close()


def demo_thread_exists(target_case_id):
    """Check whether a demo conversation already exists for a report."""
    connection = _connect()
    try:
        _ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pawpal_message_threads "
                "WHERE target_case_id=%s AND is_demo=TRUE LIMIT 1",
                (str(target_case_id).strip().upper(),),
            )
            return cursor.fetchone() is not None
    except Exception as exc:
        raise MessageStoreError("Could not check demo messages.") from exc
    finally:
        connection.close()


def prune_expired_messages():
    """Delete chat messages older than seven days and remove empty threads/files."""
    connection = _connect()
    attachment_paths = []
    try:
        _ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute("""
                DELETE FROM pawpal_messages
                WHERE created_at < NOW() - INTERVAL '7 days'
                RETURNING attachment_path
            """)
            removed_messages = cursor.rowcount
            attachment_paths = [row["attachment_path"] for row in cursor.fetchall() if row["attachment_path"]]
            cursor.execute("""
                DELETE FROM pawpal_message_threads AS t
                WHERE NOT EXISTS (
                    SELECT 1 FROM pawpal_messages m WHERE m.thread_id=t.thread_id
                )
            """)
            removed_threads = cursor.rowcount
        connection.commit()
    except Exception as exc:
        connection.rollback()
        raise MessageStoreError("Could not apply seven-day chat retention.") from exc
    finally:
        connection.close()

    private_dir = (Path(__file__).parent / "data" / "uploads" / "private-messages").resolve()
    for value in attachment_paths:
        path = Path(value)
        if not path.is_absolute():
            path = Path(__file__).parent / path
        path = path.resolve()
        if private_dir in path.parents and path.is_file():
            try:
                path.unlink()
            except OSError:
                pass
    return {"messages_removed": removed_messages, "threads_removed": removed_threads}


def list_threads_for_email(email):
    """List only threads for one authenticated participant; never return emails."""
    prune_expired_messages()
    email = str(email or "").strip()
    connection = _connect()
    try:
        _ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT t.thread_id, t.target_case_id, t.source_case_id, t.is_demo,
                       CASE WHEN LOWER(t.sender_email)=LOWER(%s) THEN 'sender' ELSE 'recipient' END AS side,
                       COALESCE(u.username, 'PawPal member') AS other_username,
                       (SELECT LEFT(m.body, 160) FROM pawpal_messages m
                        WHERE m.thread_id=t.thread_id ORDER BY m.created_at DESC, m.message_id DESC LIMIT 1)
                           AS last_message,
                       COALESCE((SELECT MAX(m.created_at) FROM pawpal_messages m
                                 WHERE m.thread_id=t.thread_id), t.created_at) AS updated_at
                FROM pawpal_message_threads t
                LEFT JOIN pawpal_users u ON LOWER(u.email)=LOWER(
                    CASE WHEN LOWER(t.sender_email)=LOWER(%s) THEN t.recipient_email ELSE t.sender_email END
                )
                WHERE LOWER(t.sender_email)=LOWER(%s) OR LOWER(t.recipient_email)=LOWER(%s)
                ORDER BY updated_at DESC
            """, (email, email, email, email))
            return [dict(row) for row in cursor.fetchall()]
    except Exception as exc:
        raise MessageStoreError("Could not load this account's private chats.") from exc
    finally:
        connection.close()


def issue_account_thread_token(thread_id, email):
    """Create a session access token after confirming the account is a participant."""
    email = str(email or "").strip()
    token = secrets.token_urlsafe(32)
    connection = _connect()
    try:
        _ensure_schema(connection)
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT sender_email, recipient_email FROM pawpal_message_threads
                WHERE thread_id=%s
            """, (str(thread_id),))
            row = cursor.fetchone()
            if not row:
                raise MessageStoreError("This conversation has expired or was removed.")
            if row["sender_email"].casefold() == email.casefold():
                side = "sender"
            elif row["recipient_email"].casefold() == email.casefold():
                side = "recipient"
            else:
                raise MessageStoreError("This account is not a participant in that conversation.")
            cursor.execute("""
                INSERT INTO pawpal_message_tokens (token_hash, thread_id, side)
                VALUES (%s, %s, %s)
            """, (_token_hash(token), str(thread_id), side))
        connection.commit()
        return token
    except MessageStoreError:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise MessageStoreError("Could not open the private chat for this account.") from exc
    finally:
        connection.close()

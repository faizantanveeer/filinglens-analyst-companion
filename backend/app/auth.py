"""Accounts, sessions, roles and credits.

- Every visitor is a user. Guests are created on first visit (no email); signing up upgrades the
  guest in place, so their documents and chats stay with them.
- Sessions are opaque random tokens (256-bit) sent as `Authorization: Bearer`. Only their SHA-256
  hash is stored, so a database leak can't be replayed. Tokens expire and are revoked on logout.
- Passwords: scrypt (stdlib) with a per-user salt, compared in constant time. Failed logins are
  rate-limited per email and per IP, and errors are generic (no account enumeration).
- Roles: guest < user < admin. Admins are the emails listed in ADMIN_EMAILS.
- Credits: guests get a small question allowance, users a monthly one. Visitors bring their own LLM
  key, so credits bound the hosted resources (retrieval, storage, compute), not LLM spend.
"""

import base64
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Header, HTTPException, Request

from .config import settings
from .db import tx

EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,}$")
ROLES = {"guest": 0, "user": 1, "admin": 2}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


def _period() -> str:
    return _now().strftime("%Y-%m")


# ---------- passwords ----------


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        # Burn similar time for unknown accounts so timing doesn't reveal which emails exist.
        hashlib.scrypt(password.encode(), salt=b"0" * 16, n=2**14, r=8, p=1, dklen=32)
        return False
    _, salt_b64, dk_b64 = stored.split("$")
    dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(dk, base64.b64decode(dk_b64))


def check_password_policy(password: str) -> None:
    if len(password) < 10 or len(password) > 128:
        raise HTTPException(422, "Password must be 10-128 characters.")
    if password.lower() == password or not re.search(r"\d", password):
        raise HTTPException(422, "Password needs at least one uppercase letter and one digit.")


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(422, "Enter a valid email address.")
    return email


# ---------- sessions ----------


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_session(user_id: str, guest: bool) -> str:
    token = secrets.token_urlsafe(32)
    days = settings.guest_session_days if guest else settings.session_days
    with tx() as c:
        c.execute(
            "INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (_token_hash(token), user_id, _iso(_now()), _iso(_now() + timedelta(days=days))),
        )
    return token


def revoke_session(token: str) -> None:
    with tx() as c:
        c.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (_token_hash(token),))


def revoke_all_sessions(user_id: str) -> None:
    with tx() as c:
        c.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if 20 <= len(token) <= 100:
            return token
    return None


def user_for_token(token: str | None) -> dict | None:
    if not token:
        return None
    with tx() as c:
        row = c.execute(
            "SELECT u.*, s.expires_at AS session_expires FROM auth_sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
            (_token_hash(token),),
        ).fetchone()
    if not row:
        return None
    if row["session_expires"] < _iso(_now()):
        revoke_session(token)
        return None
    return dict(row)


def current_user(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: the authenticated user (guest, user or admin), or 401."""
    user = user_for_token(_bearer(authorization))
    if not user:
        raise HTTPException(401, "Your session has expired. Reload the page to continue.")
    return user


def optional_user(authorization: str | None = Header(default=None)) -> dict | None:
    return user_for_token(_bearer(authorization))


def require_role(user: dict, role: str) -> None:
    if ROLES.get(user["role"], 0) < ROLES[role]:
        raise HTTPException(403, "You don't have permission to do that.")


def role_for(email: str) -> str:
    admins = {e.strip().lower() for e in settings.admin_emails.split(",") if e.strip()}
    return "admin" if email in admins else "user"


# ---------- users ----------


def get_user(user_id: str) -> dict | None:
    with tx() as c:
        row = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def create_guest(ip: str) -> dict:
    """Guests are cheap to create, so cap how many one IP can mint per hour."""
    since = _iso(_now() - timedelta(hours=1))
    with tx() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM users WHERE created_ip = ? AND role = 'guest' AND created_at > ?", (ip, since)).fetchone()["n"]
    if n >= settings.guests_per_ip_per_hour:
        raise HTTPException(429, "Too many new sessions from this network. Try again later.")
    uid = "g" + uuid.uuid4().hex[:15]
    with tx() as c:
        c.execute(
            "INSERT INTO users (id, email, password_hash, role, created_at, created_ip, questions_used, period) VALUES (?, NULL, NULL, 'guest', ?, ?, 0, ?)",
            (uid, _iso(_now()), ip, _period()),
        )
    return get_user(uid)


def _rate_limited(keys: list[str]) -> bool:
    since = _iso(_now() - timedelta(minutes=15))
    with tx() as c:
        for key in keys:
            n = c.execute("SELECT COUNT(*) AS n FROM auth_attempts WHERE key = ? AND at > ?", (key, since)).fetchone()["n"]
            if n >= settings.login_attempts_per_15min:
                return True
    return False


def _record_failure(keys: list[str]) -> None:
    with tx() as c:
        for key in keys:
            c.execute("INSERT INTO auth_attempts (key, at) VALUES (?, ?)", (key, _iso(_now())))


def signup(email: str, password: str, guest: dict | None) -> dict:
    email = normalize_email(email)
    check_password_policy(password)
    with tx() as c:
        if c.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise HTTPException(409, "An account with this email already exists. Log in instead.")
    role, pw = role_for(email), hash_password(password)
    if guest and guest["role"] == "guest":
        # Upgrade in place: the guest's documents, chats and memories are already linked to this id.
        with tx() as c:
            c.execute("UPDATE users SET email = ?, password_hash = ?, role = ? WHERE id = ?", (email, pw, role, guest["id"]))
        revoke_all_sessions(guest["id"])  # rotate tokens on privilege change
        return get_user(guest["id"])
    uid = "u" + uuid.uuid4().hex[:15]
    with tx() as c:
        c.execute(
            "INSERT INTO users (id, email, password_hash, role, created_at, created_ip, questions_used, period) VALUES (?, ?, ?, ?, ?, NULL, 0, ?)",
            (uid, email, pw, role, _iso(_now()), _period()),
        )
    return get_user(uid)


def login(email: str, password: str, ip: str, guest: dict | None) -> dict:
    email = email.strip().lower()
    keys = [f"email:{email}", f"ip:{ip}"]
    if _rate_limited(keys):
        raise HTTPException(429, "Too many attempts. Wait 15 minutes and try again.")
    with tx() as c:
        row = c.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        _record_failure(keys)
        raise HTTPException(401, "Email or password is incorrect.")
    user = dict(row)
    if user["role"] != role_for(email) and user["role"] != "guest":  # ADMIN_EMAILS changed since signup
        with tx() as c:
            c.execute("UPDATE users SET role = ? WHERE id = ?", (role_for(email), user["id"]))
        user["role"] = role_for(email)
    if guest and guest["role"] == "guest" and guest["id"] != user["id"]:
        merge_guest(guest["id"], user["id"])
    return user


def merge_guest(guest_id: str, user_id: str) -> None:
    """Move a guest's documents, chats and memories into the account they logged in to, then delete the guest."""
    with tx() as c:
        c.execute("UPDATE documents SET owner_id = ? WHERE owner_id = ?", (user_id, guest_id))
        c.execute("UPDATE sessions SET owner = ? WHERE owner = ?", (user_id, guest_id))
        c.execute("UPDATE memories SET owner = ? WHERE owner = ?", (user_id, guest_id))
        c.execute("UPDATE traces SET owner = ? WHERE owner = ?", (user_id, guest_id))
        c.execute("UPDATE uploads SET owner_id = ? WHERE owner_id = ?", (user_id, guest_id))
        c.execute("DELETE FROM auth_sessions WHERE user_id = ?", (guest_id,))
        c.execute("DELETE FROM users WHERE id = ? AND role = 'guest'", (guest_id,))


# ---------- credits ----------


def limits(user: dict) -> dict:
    guest = user["role"] == "guest"
    return {
        "questions": settings.guest_questions if guest else settings.user_questions_per_month,
        "documents": settings.guest_documents if guest else settings.user_documents,
        "upload_mb": settings.guest_upload_mb if guest else settings.max_upload_mb,
    }


def credits(user: dict) -> dict:
    used = user["questions_used"] if user.get("period") == _period() or user["role"] == "guest" else 0
    limit = limits(user)["questions"]
    return {"used": used, "limit": limit, "remaining": max(0, limit - used), "period": "trial" if user["role"] == "guest" else "month"}


def charge_question(user: dict) -> None:
    """Atomically take one question credit, or raise 402 (the UI then asks guests to sign up)."""
    if user["role"] == "admin":
        return
    limit = limits(user)["questions"]
    period = _period()
    with tx() as c:
        if user["role"] != "guest":  # monthly allowance resets at the start of each month
            c.execute("UPDATE users SET questions_used = 0, period = ? WHERE id = ? AND (period IS NULL OR period <> ?)", (period, user["id"], period))
        ok = c.execute(
            "UPDATE users SET questions_used = questions_used + 1 WHERE id = ? AND questions_used < ?", (user["id"], limit)
        ).rowcount
    if not ok:
        if user["role"] == "guest":
            raise HTTPException(402, f"You've used your {limit} free questions. Create a free account to keep going.")
        raise HTTPException(402, f"You've used this month's {limit} questions.")


def refund_question(user: dict) -> None:
    if user["role"] == "admin":
        return
    with tx() as c:
        c.execute("UPDATE users SET questions_used = questions_used - 1 WHERE id = ? AND questions_used > 0", (user["id"],))


def client_ip(request: Request) -> str:
    """Vercel sets x-real-ip to the verified client address (X-Forwarded-For can be client-supplied)."""
    ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "") or "unknown"
    return ip.strip()[:64]

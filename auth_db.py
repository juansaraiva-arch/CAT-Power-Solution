"""
auth_db.py — User database manager for CAT Power Solution
============================================================
Stores registered users in a local JSON file.

Known limitations (see below for migration notes):
1. Ephemeral filesystem on Streamlit Cloud: auth_users.json is lost on
   redeploy. Recommended migration: Supabase free tier (PostgreSQL) or
   MongoDB Atlas free tier (25 MB).
2. Rate limiting: The current implementation does not limit OTP requests.
   Consider adding a rate limit of 3 OTP requests per email per hour
   using a counter in auth_otps.json.
3. Session expiry: Streamlit sessions end when the browser tab is closed.
   For persistent sessions across browser restarts, consider
   streamlit-cookies or JWT tokens stored as cookies.
4. Audit log persistence: audit_log() currently writes to session state
   only. For persistent audit trail, append to auth_audit.log (also
   gitignored).
"""

import json
import os
import bcrypt
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "auth_users.json"


def _load() -> dict:
    if DB_PATH.exists():
        with open(DB_PATH) as f:
            return json.load(f)
    return {"users": {}}


def _save(db: dict):
    with open(DB_PATH, "w") as f:
        json.dump(db, f, indent=2, default=str)


def user_exists(email: str) -> bool:
    return email.lower() in _load()["users"]


def get_user(email: str) -> dict | None:
    return _load()["users"].get(email.lower())


def register_user(email: str, name: str, password: str, role: str = "full"):
    db = _load()
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    db["users"][email.lower()] = {
        "name": name,
        "password_hash": hashed,
        "role": role,
        "created_at": datetime.utcnow().isoformat(),
        "last_login": None,
    }
    _save(db)


def verify_password(email: str, password: str) -> bool:
    user = get_user(email)
    if not user:
        return False
    return bcrypt.checkpw(password.encode(), user["password_hash"].encode())


def update_last_login(email: str):
    db = _load()
    if email.lower() in db["users"]:
        db["users"][email.lower()]["last_login"] = datetime.utcnow().isoformat()
        _save(db)


def list_users() -> list[dict]:
    db = _load()
    return [{"email": k, **v} for k, v in db["users"].items()]

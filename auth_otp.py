"""
auth_otp.py — OTP manager for CAT Power Solution
===================================================
OTPs are stored in a JSON file, expire after 15 minutes,
and can only be used once. Codes are hashed with SHA-256.
"""

import json
import random
import string
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

OTP_PATH = Path(__file__).parent / "auth_otps.json"
OTP_TTL_MINUTES = 15


def _load() -> dict:
    if OTP_PATH.exists():
        with open(OTP_PATH) as f:
            return json.load(f)
    return {}


def _save(data: dict):
    with open(OTP_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _clean_expired(data: dict) -> dict:
    now = datetime.utcnow()
    return {
        k: v
        for k, v in data.items()
        if datetime.fromisoformat(v["expires_at"]) > now
    }


def generate_otp(email: str) -> str:
    """Generate a 6-digit OTP for the given email. Invalidates previous OTP."""
    code = "".join(random.choices(string.digits, k=6))
    data = _clean_expired(_load())
    data[email.lower()] = {
        "code_hash": hashlib.sha256(code.encode()).hexdigest(),
        "expires_at": (
            datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES)
        ).isoformat(),
        "used": False,
    }
    _save(data)
    return code


def verify_otp(email: str, code: str) -> tuple[bool, str]:
    """
    Returns (success: bool, message: str).
    Marks OTP as used on success.
    """
    data = _clean_expired(_load())
    entry = data.get(email.lower())
    if not entry:
        return False, "Code expired or not found. Request a new one."
    if entry["used"]:
        return False, "This code has already been used. Request a new one."
    if hashlib.sha256(code.strip().encode()).hexdigest() != entry["code_hash"]:
        return False, "Incorrect code. Please check your email and try again."
    # Mark as used
    data[email.lower()]["used"] = True
    _save(data)
    return True, "Code verified."

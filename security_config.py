"""
security_config.py — Authentication gate for CAT Power Solution
================================================================
Provides check_auth() which renders a multi-step login flow
and calls st.stop() until the user is authenticated.

Session keys used:
  - st.session_state["authenticated"]  (bool)
  - st.session_state["auth_user"]      (str — email)
  - st.session_state["auth_role"]      (str — "admin" | "full" | "demo")

NOTE: st.set_page_config() must be called BEFORE check_auth()
      (it is already called in streamlit_app.py).
"""

import streamlit as st
import bcrypt

from auth_db import (
    user_exists,
    get_user,
    register_user,
    verify_password,
    update_last_login,
)
from auth_otp import generate_otp, verify_otp
from auth_email import send_otp_email

ALLOWED_DOMAIN = "cat.com"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_cat_email(email: str) -> bool:
    return email.strip().lower().endswith(f"@{ALLOWED_DOMAIN}")


def _load_admin_entries() -> list[dict]:
    """Load all admin entries from secrets. Supports [[admins]] array."""
    try:
        return list(st.secrets["admins"])
    except Exception:
        return []


def _is_admin_email(email: str) -> bool:
    """Check if an email belongs to any configured admin."""
    email = email.strip().lower()
    return any(
        a["email"].strip().lower() == email for a in _load_admin_entries()
    )


def _verify_admin_password(email: str, password: str) -> bool:
    """Verify password against the matching admin's bcrypt hash."""
    email = email.strip().lower()
    for entry in _load_admin_entries():
        if entry["email"].strip().lower() == email:
            try:
                stored_hash = entry["password"].encode()
                return bcrypt.checkpw(password.encode(), stored_hash)
            except Exception:
                return False
    return False


def audit_log(event: str, detail: str = ""):
    """Append to in-session audit log (non-persistent)."""
    if "audit_log" not in st.session_state:
        st.session_state["audit_log"] = []
    import datetime
    st.session_state["audit_log"].append(
        {"ts": datetime.datetime.utcnow().isoformat(), "event": event, "detail": detail}
    )


# ── Login UI header ──────────────────────────────────────────────────────────

def _render_header():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image("assets/logo_caterpillar.png", width=300)


# ── Main auth gate ───────────────────────────────────────────────────────────

def check_auth():
    """
    Multi-step auth gate. Call at the top of main().
    Sets st.session_state["authenticated"], ["auth_user"], ["auth_role"].
    Calls st.stop() if not authenticated.
    """
    # Already authenticated → return immediately
    if st.session_state.get("authenticated"):
        return

    # Centered login card
    _, col, _ = st.columns([1, 2, 1])
    with col:
        _render_header()

        step = st.session_state.get("auth_step", "start")

        # ── SCREEN A: Email entry ─────────────────────────────────────────
        if step == "start":
            st.subheader("Sign In")
            st.caption("Access restricted to @cat.com accounts")

            email_input = st.text_input(
                "Work Email",
                placeholder="yourname@cat.com",
                key="auth_email_input",
            ).replace(" ", "").strip().lower()

            col1, col2 = st.columns(2)
            submit_email = col1.button(
                "Continue", use_container_width=True, type="primary"
            )

            if submit_email:
                if not email_input:
                    st.error("Please enter your email address.")
                elif not _is_cat_email(email_input) and not _is_admin_email(email_input):
                    st.error("Access is restricted to @cat.com email addresses.")
                else:
                    is_admin = _is_admin_email(email_input)
                    existing = user_exists(email_input)

                    if is_admin or existing:
                        # Returning user or admin → password screen
                        st.session_state["auth_pending_email"] = email_input
                        st.session_state["auth_step"] = "password"
                        st.rerun()
                    else:
                        # New user → send OTP
                        code = generate_otp(email_input)
                        success, err = send_otp_email(email_input, code)
                        if success:
                            st.session_state["auth_pending_email"] = email_input
                            st.session_state["auth_step"] = "otp_sent"
                            st.rerun()
                        else:
                            st.error(f"Failed to send email: {err}")

        # ── SCREEN B: Password login (returning user or admin) ────────────
        elif step == "password":
            pending_email = st.session_state.get("auth_pending_email", "")
            st.subheader("Welcome back")
            st.caption(f"Signing in as **{pending_email}**")

            password_input = st.text_input(
                "Password", type="password", key="auth_password_input"
            )

            col1, col2 = st.columns(2)
            submit_pw = col1.button(
                "Sign In", use_container_width=True, type="primary"
            )
            back = col2.button("Back", use_container_width=True)

            if back:
                st.session_state["auth_step"] = "start"
                st.rerun()

            if submit_pw:
                is_admin = _is_admin_email(pending_email)

                if is_admin:
                    ok = _verify_admin_password(pending_email, password_input)
                    role = "admin"
                else:
                    ok = verify_password(pending_email, password_input)
                    user = get_user(pending_email)
                    role = user["role"] if user else "full"

                if ok:
                    update_last_login(pending_email)
                    st.session_state["authenticated"] = True
                    st.session_state["auth_user"] = pending_email
                    st.session_state["auth_role"] = role
                    st.session_state.pop("auth_step", None)
                    st.session_state.pop("auth_pending_email", None)
                    audit_log("LOGIN_SUCCESS", f"user={pending_email} role={role}")
                    st.rerun()
                else:
                    st.error("Incorrect password. Please try again.")
                    audit_log("LOGIN_FAIL", f"user={pending_email}")

            # Forgot password
            st.markdown("---")
            if st.button("Forgot password? Send new verification code"):
                if pending_email:
                    code = generate_otp(pending_email)
                    success, err = send_otp_email(pending_email, code)
                    if success:
                        st.session_state["auth_step"] = "otp_sent"
                        st.session_state["auth_reset_password"] = True
                        st.rerun()
                    else:
                        st.error(f"Could not send email: {err}")

        # ── SCREEN C: OTP verification ────────────────────────────────────
        elif step == "otp_sent":
            pending_email = st.session_state.get("auth_pending_email", "")
            is_reset = st.session_state.get("auth_reset_password", False)
            action = "reset your password" if is_reset else "verify your identity"

            st.subheader("Check your email")
            st.info(
                f"A 6-digit verification code was sent to **{pending_email}**. "
                f"Enter it below to {action}."
            )
            st.caption("The code expires in 15 minutes.")

            otp_input = st.text_input(
                "Verification Code",
                placeholder="000000",
                max_chars=6,
                key="auth_otp_input",
            ).strip()

            col1, col2 = st.columns(2)
            verify_btn = col1.button(
                "Verify", use_container_width=True, type="primary"
            )
            back = col2.button("Back", use_container_width=True, key="otp_back")

            if back:
                st.session_state["auth_step"] = "start"
                st.session_state.pop("auth_reset_password", None)
                st.rerun()

            if verify_btn:
                if not otp_input or len(otp_input) != 6:
                    st.error("Please enter the 6-digit code from your email.")
                else:
                    ok, msg = verify_otp(pending_email, otp_input)
                    if ok:
                        st.session_state["auth_step"] = "set_password"
                        st.rerun()
                    else:
                        st.error(msg)

            # Resend
            st.markdown("---")
            if st.button("Resend code"):
                code = generate_otp(pending_email)
                success, err = send_otp_email(pending_email, code)
                if success:
                    st.success("A new code was sent to your email.")
                else:
                    st.error(f"Could not send email: {err}")

        # ── SCREEN D: Create / reset password ────────────────────────────
        elif step == "set_password":
            pending_email = st.session_state.get("auth_pending_email", "")
            is_reset = st.session_state.get("auth_reset_password", False)
            title = "Reset Password" if is_reset else "Create Your Password"

            st.subheader(title)
            st.caption(f"Account: **{pending_email}**")

            pw1 = st.text_input("New Password", type="password", key="auth_pw1")
            pw2 = st.text_input("Confirm Password", type="password", key="auth_pw2")

            # Password strength hints
            if pw1:
                checks = [
                    (len(pw1) >= 8, "At least 8 characters"),
                    (any(c.isupper() for c in pw1), "At least one uppercase letter"),
                    (any(c.isdigit() for c in pw1), "At least one number"),
                ]
                for passed, label in checks:
                    icon = "pass" if passed else "    "
                    st.caption(f"[{icon}] {label}")

            col1, col2 = st.columns(2)
            save_btn = col1.button(
                "Save & Sign In", use_container_width=True, type="primary"
            )

            if save_btn:
                errors = []
                if len(pw1) < 8:
                    errors.append("Password must be at least 8 characters.")
                if not any(c.isupper() for c in pw1):
                    errors.append(
                        "Password must contain at least one uppercase letter."
                    )
                if not any(c.isdigit() for c in pw1):
                    errors.append("Password must contain at least one number.")
                if pw1 != pw2:
                    errors.append("Passwords do not match.")

                if errors:
                    for e in errors:
                        st.error(e)
                else:
                    # Derive name from email
                    name = pending_email.split("@")[0].replace(".", " ").title()

                    if user_exists(pending_email):
                        # Password reset — update existing record
                        from auth_db import _load, _save

                        db = _load()
                        db["users"][pending_email]["password_hash"] = (
                            bcrypt.hashpw(
                                pw1.encode(), bcrypt.gensalt()
                            ).decode()
                        )
                        _save(db)
                        role = get_user(pending_email)["role"]
                    else:
                        # First registration
                        register_user(pending_email, name, pw1, role="full")
                        role = "full"

                    update_last_login(pending_email)
                    st.session_state["authenticated"] = True
                    st.session_state["auth_user"] = pending_email
                    st.session_state["auth_role"] = role
                    st.session_state.pop("auth_step", None)
                    st.session_state.pop("auth_pending_email", None)
                    st.session_state.pop("auth_reset_password", None)
                    audit_log("REGISTER", f"user={pending_email} role={role}")
                    st.rerun()

    # Always stop if not authenticated
    if not st.session_state.get("authenticated"):
        st.stop()

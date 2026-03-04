"""
Admin panel — visible only to users with role == "admin".
"""

import streamlit as st
import pandas as pd

from auth_db import list_users, _load, _save
from security_config import check_auth

st.set_page_config(
    page_title="CAT Power Solution — Admin",
    page_icon=":lock:",
    layout="wide",
)

check_auth()

if st.session_state.get("auth_role") != "admin":
    st.error("Admin access required.")
    st.stop()

st.title("User Administration")
st.caption(f"Logged in as: {st.session_state.get('auth_user')} (admin)")

# ── User list ──────────────────────────────────────────────────────────────────
st.subheader("Registered Users")
users = list_users()
if users:
    df = pd.DataFrame(users)[["email", "name", "role", "created_at", "last_login"]]
    df.columns = ["Email", "Name", "Role", "Created", "Last Login"]
    st.dataframe(df, use_container_width=True)
    st.caption(f"{len(users)} registered user(s)")
else:
    st.info("No registered users yet.")

# ── Revoke access ──────────────────────────────────────────────────────────────
st.subheader("Revoke Access")
emails = [u["email"] for u in users]
if emails:
    revoke_email = st.selectbox("Select user to revoke", emails)
    if st.button("Revoke Access", type="secondary"):
        db = _load()
        if revoke_email in db["users"]:
            del db["users"][revoke_email]
            _save(db)
            st.success(f"Access revoked for {revoke_email}")
            st.rerun()

# ── Change role ────────────────────────────────────────────────────────────────
st.subheader("Change Role")
if emails:
    role_email = st.selectbox("Select user", emails, key="role_sel")
    new_role = st.selectbox("New role", ["full", "demo", "admin"], key="role_val")
    if st.button("Update Role"):
        db = _load()
        if role_email in db["users"]:
            db["users"][role_email]["role"] = new_role
            _save(db)
            st.success(f"Role updated: {role_email} -> {new_role}")
            st.rerun()

# ── Stats ──────────────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("Access Statistics")
col1, col2, col3 = st.columns(3)
col1.metric("Total Users", len(users))
col2.metric("Full Access", sum(1 for u in users if u["role"] == "full"))
col3.metric("Demo Access", sum(1 for u in users if u["role"] == "demo"))

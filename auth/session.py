"""
auth/session.py
---------------
Session, user profile, and cooldown state management for QDO authentication.

Provides:
  - Secure session state tracking for Streamlit
  - Session timeout and expiration enforcement
  - Resend cooldown timer tracking
  - Verification attempt limiting
  - Persistent disaster responder account registry
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Dict, List, Optional, Tuple

try:
    import streamlit as st
except ImportError:
    st = None


# Default configuration
DEFAULT_SESSION_TIMEOUT_SECONDS = int(os.environ.get("QDO_SESSION_TIMEOUT_SECONDS", "3600"))  # 1 hour
DEFAULT_RESEND_COOLDOWN_SECONDS = int(os.environ.get("QDO_OTP_RESEND_COOLDOWN_SECONDS", "60"))  # 60s
MAX_VERIFICATION_ATTEMPTS = 5

ACCOUNTS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "responders.json")


def load_responder_accounts() -> Dict[str, Dict]:
    """Load registered responder profiles from local store."""
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_responder_account(phone_e164: str, full_name: str, role: str) -> None:
    """Save or update a responder profile."""
    accounts = load_responder_accounts()
    accounts[phone_e164] = {
        "full_name": full_name.strip() or "Emergency Response Officer",
        "role": role.strip() or "Incident Logistics Specialist",
        "registered_at": time.time(),
        "last_login_at": time.time(),
    }
    os.makedirs(os.path.dirname(ACCOUNTS_FILE), exist_ok=True)
    try:
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2)
    except Exception:
        pass


def get_responder_profile(phone_e164: str) -> Optional[Dict]:
    """Retrieve profile for a given phone number if registered."""
    accounts = load_responder_accounts()
    return accounts.get(phone_e164)


def init_session_state() -> None:
    """Initialize necessary authentication fields in Streamlit session_state."""
    if st is None:
        return

    defaults = {
        "authenticated": False,
        "auth_user": None,
        "session_expires_at": 0.0,
        "otp_sent": False,
        "pending_phone": "",
        "last_otp_request_time": 0.0,
        "verification_attempts": 0,
        "auth_error": "",
        "auth_success": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def is_authenticated() -> bool:
    """
    Check if the current Streamlit session is active and unexpired.
    Automatically invalidates expired sessions.
    """
    if st is None:
        return False

    init_session_state()

    if not st.session_state.authenticated:
        return False

    now = time.time()
    if now > st.session_state.session_expires_at:
        # Session expired
        logout_user()
        st.session_state.auth_error = "Your security session has expired. Please log in again."
        return False

    return True


def get_current_user() -> Optional[Dict]:
    """Return details of currently authenticated user."""
    if not is_authenticated():
        return None
    return st.session_state.get("auth_user")


def login_user(phone_e164: str, full_name: Optional[str] = None, role: Optional[str] = None) -> None:
    """
    Establish an authenticated session after verified OTP check for an administrator.
    """
    if st is None:
        return

    init_session_state()

    profile = get_responder_profile(phone_e164)
    admin_name = full_name or (profile.get("full_name") if profile else None) or "QDO Administrator"
    admin_role = role or (profile.get("role") if profile else None) or "System Administrator"

    now = time.time()
    st.session_state.authenticated = True
    st.session_state.is_admin = True
    st.session_state.auth_user = {
        "phone": phone_e164,
        "full_name": admin_name,
        "role": admin_role,
        "session_id": str(uuid.uuid4()),
        "authenticated_at": now,
    }
    st.session_state.session_expires_at = now + DEFAULT_SESSION_TIMEOUT_SECONDS
    st.session_state.otp_sent = False
    st.session_state.pending_phone = ""
    st.session_state.verification_attempts = 0
    st.session_state.auth_error = ""
    st.session_state.auth_success = "Admin authentication successful. Access granted."


def logout_user() -> None:
    """Terminate the current authenticated session."""
    if st is None:
        return

    init_session_state()
    st.session_state.authenticated = False
    st.session_state.auth_user = None
    st.session_state.session_expires_at = 0.0
    st.session_state.otp_sent = False
    st.session_state.pending_phone = ""
    st.session_state.verification_attempts = 0
    st.session_state.auth_success = "You have been safely signed out."


def check_resend_cooldown() -> Tuple[bool, int]:
    """
    Check if user must wait before requesting another OTP.

    Returns
    -------
    (can_request, remaining_seconds)
    """
    if st is None:
        return True, 0

    init_session_state()
    last_req = st.session_state.get("last_otp_request_time", 0.0)
    now = time.time()
    elapsed = now - last_req

    if elapsed < DEFAULT_RESEND_COOLDOWN_SECONDS:
        remaining = int(DEFAULT_RESEND_COOLDOWN_SECONDS - elapsed)
        return False, remaining
    return True, 0


def mark_otp_requested(phone_e164: str) -> None:
    """Record timestamp and state for an OTP request."""
    if st is None:
        return

    init_session_state()
    st.session_state.last_otp_request_time = time.time()
    st.session_state.otp_sent = True
    st.session_state.pending_phone = phone_e164
    st.session_state.verification_attempts = 0
    st.session_state.auth_error = ""


def record_verification_attempt() -> Tuple[bool, int]:
    """
    Record an attempt to verify OTP.

    Returns
    -------
    (allowed, attempts_remaining)
    """
    if st is None:
        return True, MAX_VERIFICATION_ATTEMPTS

    init_session_state()
    st.session_state.verification_attempts += 1
    attempts = st.session_state.verification_attempts
    remaining = max(0, MAX_VERIFICATION_ATTEMPTS - attempts)

    if attempts >= MAX_VERIFICATION_ATTEMPTS:
        return False, 0
    return True, remaining

"""
auth/ui.py
----------
Modern, professional Admin Authentication UI components for QDO in Streamlit.
Adheres to the disaster-response intelligence platform design direction:
  - Deep dark navy palette (#0A1128, #101F42)
  - Cyan / electric blue accents (#00F0FF, #0077B6)
  - Split responsive layout
  - Twilio SMS OTP integration strictly for authorized administrators
  - No public registration (admin access strictly governed by QDO_ADMIN_PHONE_NUMBERS)
"""

from __future__ import annotations

import time
from typing import Optional

try:
    import streamlit as st
except ImportError:
    st = None

from auth.twilio_verify import (
    TwilioVerifyClient,
    check_twilio_config,
    get_authorized_admin_phones,
    is_admin_authorized,
    mask_phone_number,
    normalize_phone_number,
)
from auth.session import (
    check_resend_cooldown,
    get_current_user,
    init_session_state,
    is_authenticated,
    login_user,
    logout_user,
    mark_otp_requested,
    record_verification_attempt,
)


AUTH_CUSTOM_CSS = """
<style>
/* QDO Authentication Page Styles */
.qdo-brand-header {
    background: linear-gradient(135deg, rgba(16, 31, 66, 0.85) 0%, rgba(10, 17, 40, 0.95) 100%);
    border: 1px solid rgba(0, 240, 255, 0.2);
    border-radius: 12px;
    padding: 2.2rem;
    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
}
.qdo-logo-badge {
    display: inline-block;
    padding: 4px 14px;
    background: rgba(0, 240, 255, 0.12);
    border: 1px solid #00F0FF;
    border-radius: 20px;
    color: #00F0FF;
    font-size: 0.8rem;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    margin-bottom: 1rem;
}
.qdo-title {
    font-size: 2.2rem;
    font-weight: 800;
    color: #FFFFFF;
    margin: 0;
    line-height: 1.2;
    letter-spacing: -0.5px;
}
.qdo-title span {
    color: #00F0FF;
}
.qdo-subtitle {
    font-size: 1.05rem;
    color: #94A3B8;
    margin-top: 0.6rem;
    margin-bottom: 1.5rem;
    line-height: 1.4;
}
.qdo-feature-box {
    background: rgba(15, 23, 42, 0.6);
    border-left: 3px solid #00F0FF;
    border-radius: 6px;
    padding: 0.8rem 1rem;
    margin-top: 0.8rem;
    color: #CBD5E1;
    font-size: 0.9rem;
}
.qdo-card {
    background: linear-gradient(145deg, rgba(16, 31, 66, 0.95) 0%, rgba(11, 19, 43, 0.98) 100%);
    border: 1px solid rgba(0, 240, 255, 0.25);
    border-radius: 12px;
    padding: 2rem;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
}
.qdo-warning-box {
    background: rgba(245, 158, 11, 0.1);
    border: 1px solid #F59E0B;
    border-radius: 8px;
    padding: 0.9rem 1.1rem;
    color: #FCD34D;
    font-size: 0.85rem;
    margin-bottom: 1.2rem;
}
</style>
"""


COUNTRY_CODES = [
    ("+1 (United States / Canada)", "+1"),
    ("+91 (India)", "+91"),
    ("+44 (United Kingdom)", "+44"),
    ("+61 (Australia)", "+61"),
    ("+49 (Germany)", "+49"),
    ("+33 (France)", "+33"),
    ("+81 (Japan)", "+81"),
    ("+65 (Singapore)", "+65"),
    ("Other (Manual '+' format)", "+"),
]


def render_login_page() -> bool:
    """
    Render the QDO Admin Login portal with Twilio SMS OTP authentication.

    Returns
    -------
    bool
        True if the user is successfully authenticated, False otherwise.
    """
    if st is None:
        return False

    init_session_state()

    # If already authenticated and active, do not render login screen
    if is_authenticated():
        return True

    st.markdown(AUTH_CUSTOM_CSS, unsafe_allow_html=True)

    # Check Twilio and Admin configuration status
    is_configured, missing_keys, method = check_twilio_config()
    client = TwilioVerifyClient()

    col_left, col_right = st.columns([1.1, 1.0], gap="large")

    # LEFT COLUMN: Branding & Intelligence System Overview
    with col_left:
        st.markdown(
            """
            <div class="qdo-brand-header">
                <div class="qdo-logo-badge">🚨 DISASTER COMMAND CENTER</div>
                <h1 class="qdo-title">Quantum Disaster<br><span>Resource Optimizer</span></h1>
                <p class="qdo-subtitle">Intelligent Resource Allocation for Emergency Response</p>
                <div class="qdo-feature-box">
                    <strong>🔐 Restricted Administrator Portal</strong><br>
                    Restricted to authorized emergency management personnel. Multi-factor SMS authentication is strictly enforced.
                </div>
                <div class="qdo-feature-box">
                    <strong>⚡ Twilio SMS OTP Verification</strong><br>
                    Delivers cryptographic, time-limited one-time verification passcodes via Twilio Programmable SMS to authorized admin devices.
                </div>
                <div class="qdo-feature-box">
                    <strong>🚀 Multi-Solver Optimization Engine</strong><br>
                    Full command access to Greedy baseline scheduling, Simulated Annealing QUBO optimization, Dijkstra dynamic routing, and contingency stress-testing.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if not is_configured:
            st.markdown(
                f"""
                <div class="qdo-warning-box">
                    <strong>⚠️ Configuration Required in .env</strong><br>
                    Missing required settings: <code>{', '.join(missing_keys)}</code>.<br><br>
                    To configure Twilio SMS Admin Login:
                    <ol style="margin-bottom:0; padding-left:1.2rem;">
                        <li>Set <code>TWILIO_ACCOUNT_SID</code> & <code>TWILIO_AUTH_TOKEN</code> from your <a href="https://console.twilio.com" target="_blank" style="color:#00F0FF;">Twilio Console</a>.</li>
                        <li>Set <code>TWILIO_PHONE_NUMBER</code> to your Twilio sender number.</li>
                        <li>Set <code>QDO_ADMIN_PHONE_NUMBERS</code> to your authorized mobile number (E.164 format, e.g. <code>+14155552671</code>).</li>
                    </ol>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # RIGHT COLUMN: Administrator Authentication Form
    with col_right:
        st.markdown('<div class="qdo-card">', unsafe_allow_html=True)

        if st.session_state.otp_sent:
            _render_otp_verification_view(client)
        else:
            _render_phone_entry_view(client, is_configured)

        st.markdown("</div>", unsafe_allow_html=True)

    return is_authenticated()


def _render_phone_entry_view(client: TwilioVerifyClient, is_configured: bool) -> None:
    """Render the Admin Mobile Number entry and OTP request view."""
    st.markdown("### 🔒 Administrator Sign In")
    st.caption("Enter your authorized administrator mobile number to receive a secure SMS login passcode.")

    c1, c2 = st.columns([1.1, 1.9])
    with c1:
        country_choice = st.selectbox(
            "Country Code",
            options=[c[0] for c in COUNTRY_CODES],
            index=0,
            key="login_country_code",
        )
    prefix = next(c[1] for c in COUNTRY_CODES if c[0] == country_choice)

    with c2:
        phone_input = st.text_input(
            "Admin Mobile Number",
            placeholder="4155552671" if prefix == "+1" else "Enter number",
            key="login_phone_input",
            help="Enter your mobile number. Must match an authorized number in QDO_ADMIN_PHONE_NUMBERS.",
        )

    can_resend, remaining_secs = check_resend_cooldown()

    send_clicked = st.button(
        "📲 Send Admin Login Code via SMS",
        disabled=(not is_configured) or (not can_resend),
        use_container_width=True,
        type="primary",
        key="login_send_otp_btn",
    )

    if not can_resend:
        st.info(f"⏳ Cooldown active. You can request another code in {remaining_secs}s.")

    if send_clicked:
        if not phone_input.strip():
            st.error("Please enter your administrator mobile phone number.")
            return

        valid, phone_e164, err = normalize_phone_number(phone_input, default_country_code=prefix)
        if not valid:
            st.error(err)
            return

        # Strict Admin Authorization Check
        if not is_admin_authorized(phone_e164):
            st.error(
                "⛔ Access Denied: This mobile number is not registered as an authorized QDO Administrator. "
                "Only authorized phone numbers configured in QDO_ADMIN_PHONE_NUMBERS may log in."
            )
            return

        with st.spinner("Dispatching verification passcode via Twilio SMS..."):
            success, msg, sid = client.send_verification_otp(phone_e164)
            if success:
                mark_otp_requested(phone_e164)
                st.success(msg)
                time.sleep(0.5)
                st.rerun()
            else:
                st.error(msg)


def _render_otp_verification_view(client: TwilioVerifyClient) -> None:
    """Render the 6-digit OTP verification view for administrators."""
    pending_phone = st.session_state.pending_phone
    masked_phone = mask_phone_number(pending_phone)

    st.markdown("### 🔐 Enter Verification Code")
    st.info(f"Admin security passcode dispatched via SMS to **{masked_phone}**")

    otp_code = st.text_input(
        "6-Digit Passcode",
        placeholder="123456",
        max_chars=8,
        key="otp_code_input",
        help="Enter the 6-digit verification code received on your mobile device (valid for 5 minutes).",
    )

    col_verify, col_change = st.columns([1.6, 1.0])

    with col_verify:
        verify_btn = st.button(
            "✅ Verify & Enter Admin Console",
            type="primary",
            use_container_width=True,
            key="verify_otp_btn",
        )

    with col_change:
        change_btn = st.button(
            "↩️ Change Number",
            use_container_width=True,
            key="change_phone_btn",
        )

    if change_btn:
        st.session_state.otp_sent = False
        st.session_state.pending_phone = ""
        st.rerun()

    # Resend cooldown logic
    can_resend, remaining_secs = check_resend_cooldown()
    if can_resend:
        resend_btn = st.button(
            "🔄 Resend SMS Passcode",
            key="resend_otp_btn",
        )
        if resend_btn:
            with st.spinner("Resending admin verification code..."):
                success, msg, _ = client.send_verification_otp(pending_phone)
                if success:
                    mark_otp_requested(pending_phone)
                    st.success(msg)
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error(msg)
    else:
        st.caption(f"⏳ Resend available in **{remaining_secs} seconds**.")

    if verify_btn:
        if not otp_code.strip():
            st.error("Please enter the 6-digit verification code received via SMS.")
            return

        allowed, attempts_left = record_verification_attempt()
        if not allowed:
            st.error("Maximum verification attempts exceeded. Please request a new code.")
            st.session_state.otp_sent = False
            time.sleep(1.0)
            st.rerun()
            return

        with st.spinner("Verifying admin credentials..."):
            approved, msg = client.check_verification_otp(pending_phone, otp_code)
            if approved:
                login_user(pending_phone, full_name="QDO Administrator", role="System Administrator")
                st.success("Admin identity confirmed. Loading Disaster Command Center...")
                time.sleep(0.5)
                st.rerun()
            else:
                st.error(f"{msg} ({attempts_left} attempts remaining)")


def render_authenticated_navbar() -> None:
    """Render the top navigation bar when an administrator is authenticated."""
    if st is None or not is_authenticated():
        return

    user = get_current_user()
    if not user:
        return

    masked = mask_phone_number(user.get("phone", ""))
    name = user.get("full_name", "QDO Administrator")
    role = user.get("role", "System Administrator")

    exp_secs = max(0, int(st.session_state.session_expires_at - time.time()))
    exp_mins = exp_secs // 60

    c1, c2, c3 = st.columns([2.5, 1.8, 0.7])
    with c1:
        st.markdown(
            "**🚨 Quantum Disaster Resource Optimizer (QDO)** | `ADMIN COMMAND ACTIVE`"
        )
    with c2:
        st.markdown(
            f"<div style='text-align:right; font-size:0.85rem; color:#94A3B8;'>"
            f"👤 <strong>{name}</strong> ({role}) &nbsp;|&nbsp; 📱 <code>{masked}</code> &nbsp;|&nbsp; ⏳ {exp_mins}m session"
            f"</div>",
            unsafe_allow_html=True,
        )
    with c3:
        if st.button("🚪 Sign Out", key="auth_logout_btn", use_container_width=True):
            logout_user()
            st.rerun()

    st.divider()

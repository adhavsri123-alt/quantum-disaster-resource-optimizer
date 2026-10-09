"""
auth
----
Administrator authentication subsystem for QDO using Twilio SMS OTP.
"""

from auth.twilio_verify import (
    TwilioVerifyClient,
    check_twilio_config,
    get_twilio_credentials,
    get_authorized_admin_phones,
    is_admin_authorized,
    mask_phone_number,
    normalize_phone_number,
    generate_secure_otp,
    hash_otp,
)
from auth.session import (
    get_current_user,
    is_authenticated,
    login_user,
    logout_user,
    check_resend_cooldown,
)
from auth.ui import (
    render_login_page,
    render_authenticated_navbar,
)

__all__ = [
    "TwilioVerifyClient",
    "check_twilio_config",
    "get_twilio_credentials",
    "get_authorized_admin_phones",
    "is_admin_authorized",
    "mask_phone_number",
    "normalize_phone_number",
    "generate_secure_otp",
    "hash_otp",
    "get_current_user",
    "is_authenticated",
    "login_user",
    "logout_user",
    "check_resend_cooldown",
    "render_login_page",
    "render_authenticated_navbar",
]

"""
auth/twilio_verify.py
---------------------
Twilio SMS OTP integration for QDO Administrator Login Authentication.

Supports:
  - Twilio Programmable Messaging (client.messages.create) with server-side
    cryptographic OTP generation, salted SHA-256 hash storage, 5-minute expiry,
    one-time consumption, and attempt limits.
  - Twilio Verify v2 (client.verify.v2.services) as a fallback if Verify Service SID is configured.
  - Strict Admin Authorization: Only pre-configured phone numbers in QDO_ADMIN_PHONE_NUMBERS
    may request or verify an SMS OTP.
  - E.164 phone number normalization and masked display.
  - Safe error translation without credential leakage.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from typing import Dict, List, Optional, Tuple

from pathlib import Path

try:
    from dotenv import load_dotenv
    _env_file = Path(__file__).resolve().parent.parent / ".env"
    if _env_file.exists():
        load_dotenv(dotenv_path=_env_file)
    else:
        load_dotenv()
except ImportError:
    pass

try:
    import streamlit as st
except ImportError:
    st = None


# Configuration Keys
CONFIG_ACCOUNT_SID = "TWILIO_ACCOUNT_SID"
CONFIG_AUTH_TOKEN = "TWILIO_AUTH_TOKEN"
CONFIG_PHONE_NUMBER = "TWILIO_PHONE_NUMBER"          # Twilio Programmable Messaging sender
CONFIG_ADMIN_PHONES = "QDO_ADMIN_PHONE_NUMBERS"       # Authorized Admin mobile numbers (comma-separated)
CONFIG_VERIFY_SERVICE_SID = "TWILIO_VERIFY_SERVICE_SID" # Twilio Verify Service SID (optional)

# E.164 Regex: starts with +, followed by 1-9, total 7-15 digits
E164_REGEX = re.compile(r"^\+[1-9]\d{6,14}$")

# In-memory fallback pending OTP store (for non-streamlit environments / unit tests)
_IN_MEMORY_PENDING_OTPS: Dict[str, Dict] = {}


def get_twilio_credentials() -> Dict[str, str]:
    """
    Retrieve Twilio credentials and admin phone configuration from environment
    variables or Streamlit secrets without logging secrets.
    """
    creds: Dict[str, str] = {}

    keys = (
        CONFIG_ACCOUNT_SID,
        CONFIG_AUTH_TOKEN,
        CONFIG_PHONE_NUMBER,
        CONFIG_ADMIN_PHONES,
        CONFIG_VERIFY_SERVICE_SID,
    )

    for key in keys:
        val = os.environ.get(key, "").strip()
        if not val and st is not None:
            try:
                if key in st.secrets:
                    val = str(st.secrets[key]).strip()
                elif "twilio" in st.secrets and key in st.secrets["twilio"]:
                    val = str(st.secrets["twilio"][key]).strip()
            except Exception:
                pass
        creds[key] = val

    return creds


def get_authorized_admin_phones() -> List[str]:
    """
    Retrieve list of authorized administrator mobile numbers, normalized to E.164 format.
    Only numbers in this list are permitted to authenticate as administrators.
    """
    creds = get_twilio_credentials()
    raw = creds.get(CONFIG_ADMIN_PHONES, "")
    if not raw:
        return []

    phones: List[str] = []
    for item in re.split(r"[,;]", raw):
        cleaned = item.strip()
        if cleaned:
            valid, norm, _ = normalize_phone_number(cleaned)
            if valid and norm not in phones:
                phones.append(norm)
    return phones


def is_admin_authorized(phone_e164: str) -> bool:
    """
    Verify whether the given phone number is registered in QDO_ADMIN_PHONE_NUMBERS.
    """
    authorized = get_authorized_admin_phones()
    return phone_e164 in authorized


def check_twilio_config() -> Tuple[bool, List[str], str]:
    """
    Check whether Twilio credentials and admin authorization are configured.

    Returns
    -------
    (is_configured, missing_keys, delivery_method)
        delivery_method: 'messages' (Programmable Messaging), 'verify' (Twilio Verify), or 'none'
    """
    creds = get_twilio_credentials()
    missing: List[str] = []

    if not creds.get(CONFIG_ACCOUNT_SID):
        missing.append(CONFIG_ACCOUNT_SID)
    if not creds.get(CONFIG_AUTH_TOKEN):
        missing.append(CONFIG_AUTH_TOKEN)

    # Determine delivery method
    has_phone = bool(creds.get(CONFIG_PHONE_NUMBER))
    has_verify = bool(creds.get(CONFIG_VERIFY_SERVICE_SID))

    method = "none"
    if has_phone:
        method = "messages"
    elif has_verify:
        method = "verify"
    else:
        missing.append(f"{CONFIG_PHONE_NUMBER} (or {CONFIG_VERIFY_SERVICE_SID})")

    # Check admin numbers
    if not creds.get(CONFIG_ADMIN_PHONES):
        missing.append(CONFIG_ADMIN_PHONES)

    is_configured = (len(missing) == 0)
    return is_configured, missing, method


def normalize_phone_number(raw_phone: str, default_country_code: str = "+1") -> Tuple[bool, str, str]:
    """
    Normalize and validate an entered phone number into standard E.164 format.
    """
    if not raw_phone:
        return False, "", "Phone number cannot be empty."

    cleaned = re.sub(r"[\s\-\(\)\.]", "", raw_phone.strip())

    if not cleaned.startswith("+"):
        cc = default_country_code.strip()
        if not cc.startswith("+"):
            cc = "+" + cc
        cleaned = cc + cleaned.lstrip("0")

    if not E164_REGEX.match(cleaned):
        return (
            False,
            "",
            "Invalid phone number format. Please provide a valid mobile number with country code (e.g. +14155552671).",
        )

    return True, cleaned, ""


def mask_phone_number(phone: str) -> str:
    """
    Safely mask a phone number for UI display and audit logging (e.g. +1415 *** 2671).
    """
    if not phone or len(phone) < 8:
        return "+* *** ***"

    prefix = phone[: len(phone) - 7]
    suffix = phone[-4:]
    return f"{prefix} *** {suffix}"


def generate_secure_otp() -> str:
    """Generate a cryptographically secure 6-digit numeric OTP."""
    return f"{secrets.randbelow(900000) + 100000:06d}"


def hash_otp(otp_code: str, salt: str) -> str:
    """Compute a salted SHA-256 hash of an OTP code."""
    payload = f"{salt}:{otp_code}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _store_pending_otp(
    phone_e164: str,
    otp_code: str,
    expiry_seconds: int = 300,
    sid: Optional[str] = None,
    status: Optional[str] = None,
) -> None:
    """Store salted OTP hash and metadata in session or memory (never in plaintext)."""
    salt = secrets.token_hex(16)
    hashed = hash_otp(otp_code, salt)
    expires_at = time.time() + expiry_seconds

    data = {
        "phone": phone_e164,
        "hash": hashed,
        "salt": salt,
        "expires_at": expires_at,
        "attempts": 0,
        "sid": sid,
        "status": status or "queued",
    }

    if st is not None:
        st.session_state["_pending_otp_data"] = data
    else:
        _IN_MEMORY_PENDING_OTPS[phone_e164] = data


def _get_pending_otp(phone_e164: str) -> Optional[Dict]:
    """Retrieve pending OTP metadata."""
    if st is not None:
        data = st.session_state.get("_pending_otp_data")
        if data and data.get("phone") == phone_e164:
            return data
        return None
    return _IN_MEMORY_PENDING_OTPS.get(phone_e164)


def _clear_pending_otp(phone_e164: str) -> None:
    """Invalidate and remove pending OTP metadata (one-time use)."""
    if st is not None:
        st.session_state["_pending_otp_data"] = None
    _IN_MEMORY_PENDING_OTPS.pop(phone_e164, None)


class TwilioVerifyClient:
    """
    Client for QDO Admin SMS OTP Authentication.
    Uses Twilio Programmable Messaging (client.messages.create) or Twilio Verify v2.
    """

    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        twilio_phone_number: Optional[str] = None,
        verify_service_sid: Optional[str] = None,
    ) -> None:
        creds = get_twilio_credentials()
        self.account_sid = account_sid or creds.get(CONFIG_ACCOUNT_SID, "")
        self.auth_token = auth_token or creds.get(CONFIG_AUTH_TOKEN, "")
        self.twilio_phone_number = twilio_phone_number or creds.get(CONFIG_PHONE_NUMBER, "")
        self.verify_service_sid = verify_service_sid or creds.get(CONFIG_VERIFY_SERVICE_SID, "")
        self._client = None

    @property
    def delivery_method(self) -> str:
        if self.twilio_phone_number:
            return "messages"
        elif self.verify_service_sid:
            return "verify"
        return "none"

    @property
    def is_configured(self) -> bool:
        has_creds = bool(self.account_sid and self.auth_token)
        has_delivery = bool(self.twilio_phone_number or self.verify_service_sid)
        return has_creds and has_delivery

    def _get_client(self):
        if self._client is None:
            if not self.is_configured:
                raise ValueError("Twilio credentials or delivery channels are not configured.")
            from twilio.rest import Client
            self._client = Client(self.account_sid, self.auth_token)
        return self._client

    def send_verification_otp(self, phone_e164: str) -> Tuple[bool, str, Optional[str]]:
        """
        Initiate an SMS OTP verification for an authorized administrator.

        Parameters
        ----------
        phone_e164 : str
            Recipient mobile number in E.164 format.

        Returns
        -------
        (success, message, message_or_verification_sid)
        """
        # Step 1: Strict Admin Authorization Check
        if not is_admin_authorized(phone_e164):
            return (
                False,
                "Access Denied: This mobile number is not registered as an authorized QDO Administrator.",
                "UNAUTHORIZED_ADMIN",
            )

        # Step 2: Configuration Check
        if not self.is_configured:
            is_conf, missing, _ = check_twilio_config()
            return (
                False,
                f"Twilio configuration incomplete. Missing: {', '.join(missing)}.",
                None,
            )

        # Step 3: Dispatch SMS OTP via selected method
        try:
            client = self._get_client()

            if self.delivery_method == "messages":
                # Twilio Programmable Messaging
                otp_code = generate_secure_otp()
                # Pre-store pending OTP
                _store_pending_otp(phone_e164, otp_code, expiry_seconds=300)

                msg = client.messages.create(
                    to=phone_e164,
                    from_=self.twilio_phone_number,
                    body=(
                        f"Your QDO admin login verification code is {otp_code}. "
                        "Valid for 5 minutes. Do not share this code with anyone."
                    ),
                )
                initial_status = getattr(msg, "status", "queued")
                # Update stored metadata with Twilio message SID and initial status
                _store_pending_otp(
                    phone_e164,
                    otp_code,
                    expiry_seconds=300,
                    sid=msg.sid,
                    status=initial_status,
                )
                return (
                    True,
                    f"Admin verification code accepted by Twilio (Status: {initial_status}) and queued for SMS delivery to {mask_phone_number(phone_e164)}.",
                    msg.sid,
                )

            elif self.delivery_method == "verify":
                # Twilio Verify v2
                verification = client.verify.v2.services(self.verify_service_sid).verifications.create(
                    to=phone_e164,
                    channel="sms",
                )
                return (
                    True,
                    f"Admin verification code dispatched via Twilio Verify to {mask_phone_number(phone_e164)}.",
                    verification.sid,
                )

            else:
                return False, "No valid Twilio delivery channel configured.", None

        except Exception as exc:
            # Wipe pending OTP if message dispatch failed so no dangling state remains
            _clear_pending_otp(phone_e164)
            user_msg = self._map_twilio_error(exc)
            return False, user_msg, None

    def check_verification_otp(self, phone_e164: str, otp_code: str) -> Tuple[bool, str]:
        """
        Verify the user-entered OTP code for an authorized administrator.

        Parameters
        ----------
        phone_e164 : str
            Recipient mobile number in E.164 format.
        otp_code : str
            The OTP entered by the user.

        Returns
        -------
        (is_approved, message)
        """
        # Step 1: Strict Admin Authorization Check
        if not is_admin_authorized(phone_e164):
            return False, "Access Denied: Unauthorized administrator mobile number."

        code_cleaned = otp_code.strip()
        if not code_cleaned or not code_cleaned.isdigit() or len(code_cleaned) < 4:
            return False, "Please enter a valid numeric verification code."

        if not self.is_configured:
            return False, "Twilio authentication is not configured on this server."

        # Step 2: Verification check based on delivery method
        if self.delivery_method == "messages":
            # Server-side verification for Programmable Messaging
            pending = _get_pending_otp(phone_e164)
            if not pending:
                return False, "No active verification request found. Please request a new code."

            # Check expiry (5 minutes)
            if time.time() > pending["expires_at"]:
                _clear_pending_otp(phone_e164)
                return False, "Verification code has expired (valid for 5 minutes). Please request a new code."

            # Check attempt limit (max 5)
            pending["attempts"] += 1
            if pending["attempts"] > 5:
                _clear_pending_otp(phone_e164)
                return False, "Maximum verification attempts exceeded. Please request a new code."

            # Constant-time salted hash comparison
            test_hash = hash_otp(code_cleaned, pending["salt"])
            if hmac.compare_digest(test_hash, pending["hash"]):
                # Success: Invalidate immediately (one-time use)
                _clear_pending_otp(phone_e164)
                return True, "Verification successful. Admin identity confirmed."
            else:
                remaining = 5 - pending["attempts"]
                return False, f"Incorrect verification code. ({remaining} attempts remaining)"

        elif self.delivery_method == "verify":
            # Twilio Verify v2 API check
            try:
                client = self._get_client()
                verification_check = client.verify.v2.services(self.verify_service_sid).verification_checks.create(
                    to=phone_e164,
                    code=code_cleaned,
                )
                if getattr(verification_check, "status", "") == "approved":
                    return True, "Verification successful. Admin identity confirmed."
                else:
                    return False, "Incorrect verification code. Please check your SMS and try again."
            except Exception as exc:
                user_msg = self._map_twilio_error(exc)
                return False, user_msg

        return False, "Unable to complete verification check."

    @staticmethod
    def _map_twilio_error(exc: Exception) -> str:
        """
        Translate Twilio API errors into clear, actionable, user-friendly messages
        without exposing secrets, tokens, or raw stack traces.
        """
        err_str = str(exc)
        status_code = getattr(exc, "status", None)
        code = getattr(exc, "code", None)

        if code == 60200 or code == 21211:
            return "Invalid mobile number format. Please check country code and number."
        elif code == 21614:
            return "The destination phone number is unable to receive SMS messages (landline or VoIP)."
        elif code == 21408:
            return "Twilio Geo-Permissions restriction: Sending SMS to this destination country or region is not enabled in your Twilio Console."
        elif code == 21610:
            return "Recipient mobile number is unsubscribed or on the SMS blocklist (STOP)."
        elif code == 21212:
            return "Configuration error: Invalid 'From' phone number for your Twilio account."
        elif code == 60202:
            return "Maximum verification attempts reached for this code. Please request a new code."
        elif code == 60203:
            return "Maximum SMS sends reached for this phone number. Please wait a few minutes."
        elif code == 21606:
            return "Configuration error: TWILIO_PHONE_NUMBER is not a valid Twilio sender number."
        elif code == 21608:
            return "Twilio Trial limitation: This number is not verified on your Twilio account. Please add it to Verified Caller IDs in your Twilio Console."
        elif code == 20003:
            return "Twilio authentication failed: Account SID or Auth Token is incorrect."
        elif code == 20404:
            return "Verification code has expired or was not found. Please request a new code."
        elif status_code == 429:
            return "Too many requests to Twilio service. Rate limit exceeded. Please wait before attempting again."

        # Check for network, DNS, or socket connection timeouts
        err_lower = err_str.lower()
        if any(w in err_lower for w in ["connection", "timeout", "unreachable", "name resolution", "dns"]):
            return "Network connection to Twilio service failed. Please check internet connectivity."

        if "authenticate" in err_lower or "unauthorized" in err_lower:
            return "Authentication provider error. Please check your Twilio configuration."
        return "An error occurred while communicating with the Twilio SMS service. Please try again."

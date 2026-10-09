"""
test_auth.py
------------
Unit and integration tests for Twilio SMS Admin Login Authentication in QDO.

Tests:
  - Phone number normalization, E.164 compliance, and masking
  - Strict Admin Authorization (QDO_ADMIN_PHONE_NUMBERS)
  - Unauthorized numbers blocked before any Twilio SMS call
  - Missing Twilio configuration handling and graceful failure
  - Mocked Twilio Programmable Messaging (client.messages.create) SMS dispatch
  - Server-side cryptographic OTP generation, short 5-minute expiry, and one-time consumption
  - Salted hash comparison and attempt limits (max 5 attempts)
  - Twilio error translation without credential leakage
  - Resend cooldown timers (60s) and request throttling
  - Session lifecycle, expiration, and logout
  - Unauthenticated access denial

NOTE: Automated tests use strict mocks — NO REAL SMS messages are sent
and NO credentials are exposed.
"""

from __future__ import annotations

import os
import time
import unittest
from unittest.mock import MagicMock, patch

from auth.twilio_verify import (
    TwilioVerifyClient,
    check_twilio_config,
    get_authorized_admin_phones,
    get_twilio_credentials,
    is_admin_authorized,
    mask_phone_number,
    normalize_phone_number,
    generate_secure_otp,
    hash_otp,
    _store_pending_otp,
    _get_pending_otp,
    _clear_pending_otp,
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
    DEFAULT_SESSION_TIMEOUT_SECONDS,
    DEFAULT_RESEND_COOLDOWN_SECONDS,
    MAX_VERIFICATION_ATTEMPTS,
)


class TestPhoneNormalizationAndMasking(unittest.TestCase):
    """Verify phone validation, E.164 normalization, and masking."""

    def test_valid_e164_with_plus(self):
        valid, phone, err = normalize_phone_number("+14155552671")
        self.assertTrue(valid)
        self.assertEqual(phone, "+14155552671")
        self.assertEqual(err, "")

    def test_prepend_country_code(self):
        valid, phone, err = normalize_phone_number("4155552671", default_country_code="+1")
        self.assertTrue(valid)
        self.assertEqual(phone, "+14155552671")

    def test_clean_punctuation(self):
        valid, phone, err = normalize_phone_number("(415) 555-2671", default_country_code="+1")
        self.assertTrue(valid)
        self.assertEqual(phone, "+14155552671")

    def test_international_number(self):
        valid, phone, err = normalize_phone_number("9876543210", default_country_code="+91")
        self.assertTrue(valid)
        self.assertEqual(phone, "+919876543210")

    def test_empty_phone_fails(self):
        valid, phone, err = normalize_phone_number("")
        self.assertFalse(valid)
        self.assertIn("cannot be empty", err)

    def test_invalid_short_phone_fails(self):
        valid, phone, err = normalize_phone_number("123", default_country_code="+1")
        self.assertFalse(valid)
        self.assertIn("Invalid phone number", err)

    def test_phone_masking_standard(self):
        masked = mask_phone_number("+14155552671")
        self.assertEqual(masked, "+1415 *** 2671")
        self.assertNotIn("555", masked)

    def test_phone_masking_international(self):
        masked = mask_phone_number("+919876543210")
        self.assertEqual(masked, "+91987 *** 3210")


class TestAdminAuthorization(unittest.TestCase):
    """Verify strict admin authorization checks against QDO_ADMIN_PHONE_NUMBERS."""

    @patch.dict(os.environ, {"QDO_ADMIN_PHONE_NUMBERS": "+14155552671, +14155559999"})
    def test_authorized_numbers_parsed_correctly(self):
        admins = get_authorized_admin_phones()
        self.assertEqual(len(admins), 2)
        self.assertIn("+14155552671", admins)
        self.assertIn("+14155559999", admins)

    @patch.dict(os.environ, {"QDO_ADMIN_PHONE_NUMBERS": "+14155552671"})
    def test_is_admin_authorized(self):
        self.assertTrue(is_admin_authorized("+14155552671"))
        self.assertFalse(is_admin_authorized("+14155550000"))

    @patch.dict(
        os.environ,
        {
            "TWILIO_ACCOUNT_SID": "ACmocked",
            "TWILIO_AUTH_TOKEN": "mocked_token",
            "TWILIO_PHONE_NUMBER": "+14155550100",
            "QDO_ADMIN_PHONE_NUMBERS": "+14155552671",
        },
    )
    @patch("twilio.rest.Client")
    def test_unauthorized_number_denied_before_twilio_call(self, mock_client_cls):
        client = TwilioVerifyClient()
        success, msg, sid = client.send_verification_otp("+14155550000")  # not authorized

        self.assertFalse(success)
        self.assertIn("Access Denied", msg)
        self.assertEqual(sid, "UNAUTHORIZED_ADMIN")
        # Verify no SMS call was ever initiated to Twilio
        mock_client_cls.assert_not_called()

    @patch.dict(
        os.environ,
        {
            "TWILIO_ACCOUNT_SID": "ACmocked",
            "TWILIO_AUTH_TOKEN": "mocked_token",
            "TWILIO_PHONE_NUMBER": "+14155550100",
            "QDO_ADMIN_PHONE_NUMBERS": "+14155552671",
        },
    )
    def test_unauthorized_number_check_denied(self):
        client = TwilioVerifyClient()
        approved, msg = client.check_verification_otp("+14155550000", "123456")
        self.assertFalse(approved)
        self.assertIn("Access Denied", msg)


class TestTwilioConfigurationHandling(unittest.TestCase):
    """Verify behavior when Twilio credentials are unset or incomplete."""

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_credentials_detected(self):
        is_conf, missing, method = check_twilio_config()
        self.assertFalse(is_conf)
        self.assertIn("TWILIO_ACCOUNT_SID", missing)
        self.assertIn("TWILIO_AUTH_TOKEN", missing)
        self.assertIn("QDO_ADMIN_PHONE_NUMBERS", missing)
        self.assertEqual(method, "none")

    @patch.dict(
        os.environ,
        {
            "QDO_ADMIN_PHONE_NUMBERS": "+14155552671",
        },
        clear=True,
    )
    def test_client_fails_gracefully_when_unconfigured(self):
        client = TwilioVerifyClient()
        self.assertFalse(client.is_configured)
        success, msg, sid = client.send_verification_otp("+14155552671")
        self.assertFalse(success)
        self.assertIn("Twilio configuration incomplete", msg)
        self.assertIsNone(sid)


class TestTwilioProgrammableMessagingFlow(unittest.TestCase):
    """Verify Twilio Programmable Messaging SMS dispatch and verification."""

    def setUp(self):
        _clear_pending_otp("+14155552671")
        self.env = {
            "TWILIO_ACCOUNT_SID": "ACmocked1234567890",
            "TWILIO_AUTH_TOKEN": "mocked_auth_token",
            "TWILIO_PHONE_NUMBER": "+14155550100",
            "QDO_ADMIN_PHONE_NUMBERS": "+14155552671",
        }

    def tearDown(self):
        _clear_pending_otp("+14155552671")

    @patch.dict(
        os.environ,
        {
            "TWILIO_ACCOUNT_SID": "ACmocked1234567890",
            "TWILIO_AUTH_TOKEN": "mocked_auth_token",
            "TWILIO_PHONE_NUMBER": "+14155550100",
            "QDO_ADMIN_PHONE_NUMBERS": "+14155552671",
        },
    )
    @patch("twilio.rest.Client")
    def test_send_and_verify_programmable_messaging_otp(self, mock_client_cls):
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        mock_msg = MagicMock()
        mock_msg.sid = "SMmocked12345"
        mock_msg.status = "queued"
        mock_instance.messages.create.return_value = mock_msg

        client = TwilioVerifyClient()
        self.assertEqual(client.delivery_method, "messages")

        # 1. Send OTP
        success, msg, sid = client.send_verification_otp("+14155552671")
        self.assertTrue(success)
        self.assertEqual(sid, "SMmocked12345")
        self.assertIn("Admin verification code accepted by Twilio", msg)
        self.assertIn("queued", msg)

        # Ensure Twilio messages.create was called with correct parameters
        mock_instance.messages.create.assert_called_once()
        call_kwargs = mock_instance.messages.create.call_args[1]
        self.assertEqual(call_kwargs["to"], "+14155552671")
        self.assertEqual(call_kwargs["from_"], "+14155550100")
        self.assertIn("Your QDO admin login verification code is", call_kwargs["body"])

        # Extract the generated code from call_args to test verification
        body = call_kwargs["body"]
        code = body.split("Your QDO admin login verification code is ")[1].split(".")[0]
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

        # 2. Test wrong code rejection
        approved_wrong, msg_wrong = client.check_verification_otp("+14155552671", "000000")
        self.assertFalse(approved_wrong)
        self.assertIn("Incorrect verification code", msg_wrong)

        # 3. Test correct code approval
        approved_right, msg_right = client.check_verification_otp("+14155552671", code)
        self.assertTrue(approved_right)
        self.assertIn("Verification successful", msg_right)

        # 4. Test one-time consumption (code cannot be reused)
        approved_reused, msg_reused = client.check_verification_otp("+14155552671", code)
        self.assertFalse(approved_reused)
        self.assertIn("No active verification request", msg_reused)

    @patch.dict(
        os.environ,
        {
            "TWILIO_ACCOUNT_SID": "ACmocked1234567890",
            "TWILIO_AUTH_TOKEN": "mocked_auth_token",
            "TWILIO_PHONE_NUMBER": "+14155550100",
            "QDO_ADMIN_PHONE_NUMBERS": "+14155552671",
        },
    )
    def test_expired_otp_rejected(self):
        client = TwilioVerifyClient()
        _store_pending_otp("+14155552671", "654321", expiry_seconds=-10)  # already expired

        approved, msg = client.check_verification_otp("+14155552671", "654321")
        self.assertFalse(approved)
        self.assertIn("expired", msg.lower())

    @patch.dict(
        os.environ,
        {
            "TWILIO_ACCOUNT_SID": "ACmocked1234567890",
            "TWILIO_AUTH_TOKEN": "mocked_auth_token",
            "TWILIO_PHONE_NUMBER": "+14155550100",
            "QDO_ADMIN_PHONE_NUMBERS": "+14155552671",
        },
    )
    def test_attempt_limit_enforced(self):
        client = TwilioVerifyClient()
        _store_pending_otp("+14155552671", "654321", expiry_seconds=300)

        # 5 wrong attempts
        for _ in range(5):
            approved, _ = client.check_verification_otp("+14155552671", "000000")
            self.assertFalse(approved)

        # 6th attempt: attempts exceeded
        approved, msg = client.check_verification_otp("+14155552671", "654321")
        self.assertFalse(approved)
        self.assertIn("exceeded", msg.lower())


class TestTwilioErrorMapping(unittest.TestCase):
    """Verify safe error message mapping without token leakage."""

    @patch.dict(
        os.environ,
        {
            "TWILIO_ACCOUNT_SID": "ACmocked",
            "TWILIO_AUTH_TOKEN": "mocked_token",
            "TWILIO_PHONE_NUMBER": "+14155550100",
            "QDO_ADMIN_PHONE_NUMBERS": "+14155552671",
        },
    )
    @patch("twilio.rest.Client")
    def test_twilio_exception_handled_safely(self, mock_client_cls):
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        from twilio.base.exceptions import TwilioRestException
        mock_instance.messages.create.side_effect = TwilioRestException(
            status=400,
            uri="/Messages",
            msg="From number invalid",
            code=21606,
        )

        client = TwilioVerifyClient()
        success, msg, sid = client.send_verification_otp("+14155552671")
        self.assertFalse(success)
        self.assertIn("TWILIO_PHONE_NUMBER is not a valid Twilio sender number", msg)
        self.assertIsNone(sid)

    @patch.dict(
        os.environ,
        {
            "TWILIO_ACCOUNT_SID": "ACmocked",
            "TWILIO_AUTH_TOKEN": "mocked_token",
            "TWILIO_PHONE_NUMBER": "+14155550100",
            "QDO_ADMIN_PHONE_NUMBERS": "+14155552671",
        },
    )
    @patch("twilio.rest.Client")
    def test_geo_permissions_error_handled(self, mock_client_cls):
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        from twilio.base.exceptions import TwilioRestException
        mock_instance.messages.create.side_effect = TwilioRestException(
            status=400,
            uri="/Messages",
            msg="Geo permission not enabled",
            code=21408,
        )

        client = TwilioVerifyClient()
        success, msg, sid = client.send_verification_otp("+14155552671")
        self.assertFalse(success)
        self.assertIn("Twilio Geo-Permissions restriction", msg)
        self.assertIsNone(sid)

    @patch.dict(
        os.environ,
        {
            "TWILIO_ACCOUNT_SID": "ACmocked",
            "TWILIO_AUTH_TOKEN": "mocked_token",
            "TWILIO_PHONE_NUMBER": "+14155550100",
            "QDO_ADMIN_PHONE_NUMBERS": "+14155552671",
        },
    )
    @patch("twilio.rest.Client")
    def test_landline_unsupported_error_handled(self, mock_client_cls):
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        from twilio.base.exceptions import TwilioRestException
        mock_instance.messages.create.side_effect = TwilioRestException(
            status=400,
            uri="/Messages",
            msg="Cannot receive SMS",
            code=21614,
        )

        client = TwilioVerifyClient()
        success, msg, sid = client.send_verification_otp("+14155552671")
        self.assertFalse(success)
        self.assertIn("unable to receive SMS messages", msg)

    @patch.dict(
        os.environ,
        {
            "TWILIO_ACCOUNT_SID": "ACmocked",
            "TWILIO_AUTH_TOKEN": "mocked_token",
            "TWILIO_PHONE_NUMBER": "+14155550100",
            "QDO_ADMIN_PHONE_NUMBERS": "+14155552671",
        },
    )
    @patch("twilio.rest.Client")
    def test_network_connection_error_handled(self, mock_client_cls):
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        mock_instance.messages.create.side_effect = ConnectionError("Connection refused by peer")

        client = TwilioVerifyClient()
        success, msg, sid = client.send_verification_otp("+14155552671")
        self.assertFalse(success)
        self.assertIn("Network connection to Twilio service failed", msg)

    @patch.dict(
        os.environ,
        {
            "TWILIO_ACCOUNT_SID": "ACmocked",
            "TWILIO_AUTH_TOKEN": "mocked_token",
            "TWILIO_PHONE_NUMBER": "+14155550100",
            "QDO_ADMIN_PHONE_NUMBERS": "+14155552671",
        },
    )
    @patch("twilio.rest.Client")
    def test_pending_otp_cleared_on_send_failure(self, mock_client_cls):
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        mock_instance.messages.create.side_effect = RuntimeError("Dispatch error")

        client = TwilioVerifyClient()
        client.send_verification_otp("+14155552671")
        self.assertIsNone(_get_pending_otp("+14155552671"))


class TestSessionManagementAndState(unittest.TestCase):
    """Verify session state, cooldown tracking, expiration, and admin logout."""

    def setUp(self):
        class MockSessionState(dict):
            def __getattr__(self, key):
                return self.get(key)
            def __setattr__(self, key, value):
                self[key] = value

        self.mock_st = MagicMock()
        self.mock_st.session_state = MockSessionState()

        self.patcher = patch("auth.session.st", self.mock_st)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_unauthenticated_by_default(self):
        self.assertFalse(is_authenticated())
        self.assertIsNone(get_current_user())

    def test_login_creates_authenticated_admin_session(self):
        login_user("+14155552671", full_name="Incident Commander", role="Administrator")
        self.assertTrue(is_authenticated())

        user = get_current_user()
        self.assertIsNotNone(user)
        self.assertEqual(user["phone"], "+14155552671")
        self.assertEqual(user["role"], "Administrator")
        self.assertIn("session_id", user)

    def test_logout_clears_session(self):
        login_user("+14155552671")
        self.assertTrue(is_authenticated())

        logout_user()
        self.assertFalse(is_authenticated())
        self.assertIsNone(get_current_user())

    def test_session_expiration(self):
        login_user("+14155552671")
        self.assertTrue(is_authenticated())

        self.mock_st.session_state.session_expires_at = time.time() - 10.0
        self.assertFalse(is_authenticated())

    def test_resend_cooldown_enforced(self):
        can_resend, remaining = check_resend_cooldown()
        self.assertTrue(can_resend)
        self.assertEqual(remaining, 0)

        mark_otp_requested("+14155552671")
        can_resend, remaining = check_resend_cooldown()
        self.assertFalse(can_resend)
        self.assertGreater(remaining, 0)


if __name__ == "__main__":
    unittest.main()

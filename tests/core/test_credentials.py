"""
Unit tests for jot.core.credentials.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import jot.core.credentials as creds


class TestKeyringHelpers(unittest.TestCase):
    def test_keyring_get_returns_empty_on_windows(self) -> None:
        with patch("jot.core.credentials.platform.system", return_value="Windows"):
            result = creds.keyring_get_api_key()
        self.assertEqual(result, "")

    def test_keyring_get_returns_value_from_keyring(self) -> None:
        mock_kr = MagicMock()
        mock_kr.get_password.return_value = "test-api-key"
        with (
            patch("jot.core.credentials.platform.system", return_value="Darwin"),
            patch.dict(sys.modules, {"keyring": mock_kr}),
        ):
            result = creds.keyring_get_api_key()
        self.assertEqual(result, "test-api-key")
        mock_kr.get_password.assert_called_once_with(
            creds.KEYRING_SERVICE, creds.KEYRING_USER_API
        )

    def test_keyring_get_retries_once_on_exception(self) -> None:
        mock_kr = MagicMock()
        mock_kr.get_password.side_effect = RuntimeError("keyring busy")
        with (
            patch("jot.core.credentials.platform.system", return_value="Linux"),
            patch.dict(sys.modules, {"keyring": mock_kr}),
            patch("jot.core.credentials.time.sleep") as mock_sleep,
        ):
            result = creds.keyring_get_api_key()
        self.assertEqual(result, "")
        self.assertEqual(mock_kr.get_password.call_count, 2)
        mock_sleep.assert_called_once_with(0.5)

    def test_keyring_set_returns_false_on_windows(self) -> None:
        with patch("jot.core.credentials.platform.system", return_value="Windows"):
            result = creds.keyring_set_api_key("some-key")
        self.assertFalse(result)

    def test_keyring_set_returns_true_on_success(self) -> None:
        mock_kr = MagicMock()
        with (
            patch("jot.core.credentials.platform.system", return_value="Darwin"),
            patch.dict(sys.modules, {"keyring": mock_kr}),
        ):
            result = creds.keyring_set_api_key("new-key")
        self.assertTrue(result)
        mock_kr.set_password.assert_called_once_with(
            creds.KEYRING_SERVICE, creds.KEYRING_USER_API, "new-key"
        )

    def test_keyring_set_returns_false_on_exception(self) -> None:
        mock_kr = MagicMock()
        mock_kr.set_password.side_effect = RuntimeError("failed")
        with (
            patch("jot.core.credentials.platform.system", return_value="Linux"),
            patch.dict(sys.modules, {"keyring": mock_kr}),
        ):
            result = creds.keyring_set_api_key("new-key")
        self.assertFalse(result)

    def test_keyring_delete_returns_false_on_windows(self) -> None:
        with patch("jot.core.credentials.platform.system", return_value="Windows"):
            result = creds.keyring_delete_api_key()
        self.assertFalse(result)

    def test_keyring_delete_returns_true_on_success(self) -> None:
        mock_kr = MagicMock()
        with (
            patch("jot.core.credentials.platform.system", return_value="Darwin"),
            patch.dict(sys.modules, {"keyring": mock_kr}),
        ):
            result = creds.keyring_delete_api_key()
        self.assertTrue(result)
        mock_kr.delete_password.assert_called_once_with(
            creds.KEYRING_SERVICE, creds.KEYRING_USER_API
        )

    def test_clearing_absent_entries_succeeds_without_delete(self) -> None:
        mock_kr = MagicMock()
        mock_kr.get_password.return_value = None
        with (
            patch("jot.core.credentials.platform.system", return_value="Darwin"),
            patch.dict(sys.modules, {"keyring": mock_kr}),
        ):
            self.assertTrue(creds.keyring_delete_api_key())
            self.assertTrue(creds.keyring_delete_fallback_keys())
        mock_kr.delete_password.assert_not_called()

    def test_failed_delete_is_reported_for_both_credential_groups(self) -> None:
        mock_kr = MagicMock()
        mock_kr.get_password.return_value = "stored"
        mock_kr.delete_password.side_effect = RuntimeError("locked backend")
        with (
            patch("jot.core.credentials.platform.system", return_value="Darwin"),
            patch.dict(sys.modules, {"keyring": mock_kr}),
        ):
            self.assertFalse(creds.keyring_delete_api_key())
            self.assertFalse(creds.keyring_delete_fallback_keys())

    def test_keyring_fallback_keys_get_set_delete(self) -> None:
        mock_kr = MagicMock()
        mock_kr.get_password.return_value = json.dumps(["k1", "k2"])
        with (
            patch("jot.core.credentials.platform.system", return_value="Darwin"),
            patch.dict(sys.modules, {"keyring": mock_kr}),
        ):
            # GET
            keys = creds.keyring_get_fallback_keys()
            self.assertEqual(keys, ["k1", "k2"])

            # SET
            ok = creds.keyring_set_fallback_keys(["k3", "k4"])
            self.assertTrue(ok)
            mock_kr.set_password.assert_called_with(
                creds.KEYRING_SERVICE,
                creds.KEYRING_USER_FALLBACK_KEYS,
                json.dumps(["k3", "k4"]),
            )

            # DELETE
            del_ok = creds.keyring_delete_fallback_keys()
            self.assertTrue(del_ok)
            mock_kr.delete_password.assert_called_with(
                creds.KEYRING_SERVICE, creds.KEYRING_USER_FALLBACK_KEYS
            )

    def test_keyring_fallback_keys_on_windows_returns_empty_or_false(self) -> None:
        with patch("jot.core.credentials.platform.system", return_value="Windows"):
            self.assertEqual(creds.keyring_get_fallback_keys(), [])
            self.assertFalse(creds.keyring_set_fallback_keys(["k1"]))
            self.assertFalse(creds.keyring_delete_fallback_keys())


class TestDPAPIHelpers(unittest.TestCase):
    def test_dpapi_returns_empty_on_non_windows(self) -> None:
        with patch("jot.core.credentials.platform.system", return_value="Darwin"):
            self.assertEqual(creds.dpapi_protect_text_windows("secret"), "")
            self.assertEqual(creds.dpapi_unprotect_text_windows("secret"), "")
            self.assertEqual(creds.dpapi_unprotect_text_windows_once("secret"), "")

    def test_dpapi_protect_empty_text_returns_empty(self) -> None:
        with patch("jot.core.credentials.platform.system", return_value="Windows"):
            self.assertEqual(creds.dpapi_protect_text_windows(""), "")

    def test_dpapi_unprotect_empty_blob_returns_empty(self) -> None:
        with patch("jot.core.credentials.platform.system", return_value="Windows"):
            self.assertEqual(creds.dpapi_unprotect_text_windows(""), "")

    def test_dpapi_unprotect_retries_once(self) -> None:
        with (
            patch("jot.core.credentials.platform.system", return_value="Windows"),
            patch(
                "jot.core.credentials.dpapi_unprotect_text_windows_once",
                side_effect=["", "decrypted"],
            ) as mock_once,
            patch("jot.core.credentials.time.sleep") as mock_sleep,
        ):
            res = creds.dpapi_unprotect_text_windows("fake-b64")
            self.assertEqual(res, "decrypted")
            self.assertEqual(mock_once.call_count, 2)
            mock_sleep.assert_called_once_with(0.5)

    def test_debug_log_handles_exceptions_gracefully(self) -> None:
        with patch.dict(os.environ, {"JOT_DEBUG": "1"}):
            with patch("builtins.print") as mock_print:
                creds._debug_log(
                    "Testing creds debug log AIzaSy12345678901234567890123456789012345"
                )
                mock_print.assert_called_once()
                self.assertNotIn(
                    "AIzaSy12345678901234567890123456789012345",
                    mock_print.call_args[0][0],
                )


if __name__ == "__main__":
    unittest.main()

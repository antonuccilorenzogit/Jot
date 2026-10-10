"""
Tests for network_service: connectivity checking and offline error classification.
"""

from __future__ import annotations

import socket
import unittest
from unittest.mock import MagicMock, patch

from jot.services.network_service import (
    check_connectivity,
    is_network_offline_error,
)


class TestNetworkService(unittest.TestCase):
    def test_check_connectivity_bypassed_in_test(self):
        # By default in pytest environment it returns True without opening sockets
        self.assertTrue(check_connectivity(bypass_in_test=True))

    def test_check_connectivity_success(self):
        mock_sock = MagicMock()
        with patch("socket.create_connection", return_value=mock_sock) as mock_create:
            result = check_connectivity(
                host="generativelanguage.googleapis.com",
                port=443,
                timeout=2.0,
                bypass_in_test=False,
            )
            self.assertTrue(result)
            mock_create.assert_called_once_with(
                ("generativelanguage.googleapis.com", 443), timeout=2.0
            )
            mock_sock.close.assert_called_once()

    def test_check_connectivity_failure(self):
        with patch(
            "socket.create_connection", side_effect=OSError("Network unreachable")
        ):
            result = check_connectivity(
                host="generativelanguage.googleapis.com",
                port=443,
                timeout=2.0,
                bypass_in_test=False,
            )
            self.assertFalse(result)

    def test_is_network_offline_error_none(self):
        self.assertFalse(is_network_offline_error(None))

    def test_is_network_offline_error_socket_gaierror(self):
        err = socket.gaierror(11001, "getaddrinfo failed")
        self.assertTrue(is_network_offline_error(err))

    def test_is_network_offline_error_connection_error(self):
        self.assertTrue(is_network_offline_error(ConnectionRefusedError("Refused")))
        self.assertTrue(is_network_offline_error(ConnectionResetError("Reset")))

    def test_is_network_offline_error_windows_errno(self):
        err = OSError(11001, "WSAHOST_NOT_FOUND")
        self.assertTrue(is_network_offline_error(err))
        err2 = OSError(10051, "WSAENETUNREACH")
        self.assertTrue(is_network_offline_error(err2))

    def test_is_network_offline_error_text_markers(self):
        err = RuntimeError("ConnectError: [Errno 11001] getaddrinfo failed")
        self.assertTrue(is_network_offline_error(err))

        err_unreach = Exception("HTTP connection failed: Network is unreachable")
        self.assertTrue(is_network_offline_error(err_unreach))

    def test_is_network_offline_error_chained_cause(self):
        root_cause = socket.gaierror(11001, "getaddrinfo failed")
        outer_err = RuntimeError("API call failed")
        outer_err.__cause__ = root_cause
        self.assertTrue(is_network_offline_error(outer_err))

    def test_is_network_offline_error_unrelated(self):
        self.assertFalse(is_network_offline_error(ValueError("Invalid argument")))
        self.assertFalse(is_network_offline_error(KeyError("missing_key")))
        self.assertFalse(is_network_offline_error(RuntimeError("FFmpeg exit code 1")))


if __name__ == "__main__":
    unittest.main()

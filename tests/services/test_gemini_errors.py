import unittest
from typing import Any

from jot.services.gemini_errors import (
    classify_429_error,
    classify_credential_status,
    extract_retry_after_seconds,
)


class DummyExceptionWithHeaders(Exception):
    def __init__(self, message: str, code: int | None = None, headers: Any = None):
        super().__init__(message)
        self.code = code
        self.headers = headers if headers is not None else {}


class GeminiErrorsTaxonomyTests(unittest.TestCase):
    def test_classify_429_rpd_daily_quota_exceeded(self):
        exc = DummyExceptionWithHeaders(
            "Resource has been exhausted (e.g. check quota). GenerateRequestsPerDay limit exceeded.",
            code=429,
        )
        self.assertEqual(classify_429_error(exc), "quota_exceeded")

        exc2 = DummyExceptionWithHeaders(
            "Exceeded your current quota, please check your plan and billing details.",
            code=429,
        )
        self.assertEqual(classify_429_error(exc2), "quota_exceeded")

    def test_classify_429_rpm_tpm_rate_limit_exceeded(self):
        exc = DummyExceptionWithHeaders(
            "Rate limit exceeded: requests per minute (RPM) limit reached. Please wait.",
            code=429,
        )
        self.assertEqual(classify_429_error(exc), "rate_limit_exceeded")

        exc2 = DummyExceptionWithHeaders(
            "Resource exhausted: generatecontenttokenspermodelperminute limit exceeded.",
            code=429,
        )
        self.assertEqual(classify_429_error(exc2), "rate_limit_exceeded")

    def test_classify_429_unknown(self):
        exc = DummyExceptionWithHeaders("Too many requests from this client.", code=429)
        self.assertEqual(classify_429_error(exc), "unknown_429")

    def test_classify_credential_status_401_invalid(self):
        exc = DummyExceptionWithHeaders(
            "API key not valid. Please pass a valid API key.", code=401
        )
        self.assertEqual(classify_credential_status(exc), "invalid")

    def test_classify_credential_status_403_permission_denied(self):
        exc = DummyExceptionWithHeaders(
            "PERMISSION_DENIED: Consumer project has not enabled Gemini API.", code=403
        )
        self.assertEqual(classify_credential_status(exc), "permission_denied")

    def test_classify_credential_status_400_request_error(self):
        exc = DummyExceptionWithHeaders(
            "INVALID_ARGUMENT: Unsupported mime type.", code=400
        )
        self.assertEqual(classify_credential_status(exc), "request_error")

    def test_classify_credential_status_503_temporarily_failing(self):
        exc = DummyExceptionWithHeaders(
            "The model is overloaded. Please try again later.", code=503
        )
        self.assertEqual(classify_credential_status(exc), "temporarily_failing")

    def test_extract_retry_after_from_headers(self):
        exc = DummyExceptionWithHeaders(
            "Rate limited", code=429, headers={"retry-after": "18.5"}
        )
        self.assertEqual(extract_retry_after_seconds(exc), 18.5)

    def test_extract_retry_after_from_httpx_headers(self):
        try:
            import httpx

            headers = httpx.Headers({"Retry-After": "45"})
        except ImportError:
            # Fallback Mapping with lower-case accessor if httpx not directly installed
            class FakeHttpxHeaders:
                def __init__(self, d):
                    self._d = {k.lower(): v for k, v in d.items()}

                def get(self, k, default=None):
                    return self._d.get(k.lower(), default)

                def items(self):
                    return self._d.items()

            headers = FakeHttpxHeaders({"Retry-After": "45"})

        exc = DummyExceptionWithHeaders("Rate limited", code=429, headers=headers)
        self.assertEqual(extract_retry_after_seconds(exc), 45.0)

    def test_extract_retry_after_from_text(self):
        exc = DummyExceptionWithHeaders(
            "Resource exhausted: please retry in 21s", code=429
        )
        self.assertEqual(extract_retry_after_seconds(exc), 21.0)


if __name__ == "__main__":
    unittest.main()

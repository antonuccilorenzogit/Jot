import os
import sys
import tempfile
import unittest
from typing import ClassVar
from unittest.mock import MagicMock, patch

from jot.services.validation_service import (
    _check_ffmpeg_execution,
    _check_writable_dir,
    validate_environment,
)


class _AlwaysOkModels:
    def get(self, model=None, **kwargs):
        return {"model": model}


class _AlwaysOkClient:
    def __init__(self, api_key=None, **kwargs):
        self.api_key = api_key
        self.models = _AlwaysOkModels()


class _FallbackFailModels:
    def get(self, model=None, **kwargs):
        if model == "gemini-3.6-flash":
            raise RuntimeError("model disabled for this key")
        return {"model": model}


class _FallbackFailClient:
    def __init__(self, api_key=None, **kwargs):
        self.api_key = api_key
        self.models = _FallbackFailModels()


class _PrimaryFailModels:
    def get(self, model=None, **kwargs):
        raise RuntimeError("primary access denied")


class _PrimaryFailClient:
    def __init__(self, api_key=None, **kwargs):
        self.api_key = api_key
        self.models = _PrimaryFailModels()


class _ClientCtorFail:
    def __init__(self, api_key=None, **kwargs):
        raise RuntimeError(f"invalid API key {api_key}")


class _MiddleFailModels:
    def get(self, model=None, **kwargs):
        if model == "gemini-3.6-flash":
            raise RuntimeError(
                "middle model disabled key=AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
            )
        return {"model": model}


class _MiddleFailClient:
    def __init__(self, api_key=None, **kwargs):
        self.api_key = api_key
        self.models = _MiddleFailModels()


class _NoGenerateContentModel:
    supported_actions: ClassVar[list[str]] = ["countTokens"]


class _NoGenerateContentModels:
    def get(self, model=None, **kwargs):
        return _NoGenerateContentModel()


class _NoGenerateContentClient:
    def __init__(self, api_key=None, **kwargs):
        self.api_key = api_key
        self.models = _NoGenerateContentModels()


@patch(
    "jot.services.validation_service._check_ffmpeg_execution",
    return_value=(True, "ffmpeg version 7.0"),
)
class ValidationServiceTests(unittest.TestCase):
    @patch("jot.services.validation_service.get_session_root", return_value=".")
    @patch(
        "jot.services.validation_service.resolve_ffmpeg",
        return_value="ffmpeg.exe",
    )
    @patch("google.genai.Client", _AlwaysOkClient)
    def test_validate_environment_with_api_key(self, *_mocks):
        result = validate_environment(
            api_key="fake",
            validate_api_key=True,
            preferred_model="gemini-2.5-flash",
            fallback_models=["gemini-3.6-flash"],
        )
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(len(result["checks"]), 5)
        api_check = next(
            check for check in result["checks"] if check["id"] == "api_key"
        )
        self.assertEqual(api_check["status"], "ok")
        details = [
            check.get("details")
            for check in result["checks"]
            if str(check.get("id", "")).startswith("api")
        ]
        self.assertIn("gemini-3.6-flash", details)

    @patch(
        "jot.services.validation_service.resolve_ffmpeg",
        return_value="ffmpeg.exe",
    )
    @patch("jot.services.validation_service.get_session_root", return_value=".")
    @patch("google.genai.Client", _FallbackFailClient)
    def test_validate_environment_keeps_primary_ok_when_fallback_fails(self, *_mocks):
        result = validate_environment(
            api_key="fake",
            validate_api_key=True,
            preferred_model="gemini-2.5-flash",
            fallback_models=["gemini-3.6-flash"],
        )

        self.assertFalse(result["ok"])
        api_check = next(
            check for check in result["checks"] if check["id"] == "api_key"
        )
        fallback_check = next(
            check for check in result["checks"] if check["id"] == "api_model_1"
        )
        self.assertEqual(api_check["status"], "ok")
        self.assertEqual(fallback_check["status"], "error")
        self.assertIn("gemini-3.6-flash", fallback_check["details"])  # type: ignore[typeddict-item]
        self.assertEqual(
            fallback_check["message"],
            "Modello fallback 1 non accessibile con questa chiave.",
        )

    @patch(
        "jot.services.validation_service.resolve_ffmpeg",
        return_value="ffmpeg.exe",
    )
    @patch("jot.services.validation_service.get_session_root", return_value=".")
    @patch("google.genai.Client", _PrimaryFailClient)
    def test_validate_environment_reports_primary_model_failure_distinctly_from_key_error(
        self, *_mocks
    ):
        result = validate_environment(
            api_key="fake",
            validate_api_key=True,
            preferred_model="gemini-2.5-flash",
            fallback_models=["gemini-3.6-flash"],
        )

        self.assertFalse(result["ok"])
        api_check = next(
            check for check in result["checks"] if check["id"] == "api_key"
        )
        self.assertEqual(api_check["status"], "error")
        self.assertEqual(api_check["label"], "API Key Gemini")
        self.assertEqual(
            api_check["message"],
            "Modello primario non accessibile.",
        )
        self.assertNotIn("fallback", api_check["message"].lower())
        self.assertIn("gemini-2.5-flash", api_check["details"])  # type: ignore[typeddict-item]

    @patch(
        "jot.services.validation_service.resolve_ffmpeg",
        return_value="ffmpeg.exe",
    )
    @patch("jot.services.validation_service.get_session_root", return_value=".")
    @patch("google.genai.Client", _ClientCtorFail)
    def test_validate_environment_reports_client_creation_failure_without_unbound_state(
        self, *_mocks
    ):
        result = validate_environment(
            api_key="fake",
            validate_api_key=True,
            preferred_model="gemini-2.5-flash",
            fallback_models=["gemini-3.6-flash"],
        )

        self.assertFalse(result["ok"])
        api_check = next(
            check for check in result["checks"] if check["id"] == "api_key"
        )
        self.assertEqual(api_check["status"], "error")
        self.assertEqual(api_check["label"], "API Key Gemini")
        self.assertIn("invalid API key", api_check["details"])  # type: ignore[typeddict-item]
        self.assertNotIn("AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345", api_check["details"])  # type: ignore[typeddict-item]

    @patch(
        "jot.services.validation_service.resolve_ffmpeg",
        return_value="ffmpeg.exe",
    )
    @patch("jot.services.validation_service.get_session_root", return_value=".")
    @patch("google.genai.Client", _NoGenerateContentClient)
    def test_validate_environment_rejects_models_without_generate_content(
        self, *_mocks
    ):
        result = validate_environment(
            api_key="fake",
            validate_api_key=True,
            preferred_model="gemini-2.5-flash",
            fallback_models=[],
        )

        self.assertFalse(result["ok"])
        api_check = next(
            check for check in result["checks"] if check["id"] == "api_key"
        )
        self.assertEqual(api_check["status"], "error")
        self.assertIn("generateContent", api_check["details"])  # type: ignore[typeddict-item]

    @patch(
        "jot.services.validation_service.resolve_ffmpeg",
        return_value="ffmpeg.exe",
    )
    @patch("jot.services.validation_service.get_session_root", return_value=".")
    @patch("google.genai.Client", _MiddleFailClient)
    def test_validate_environment_continues_after_middle_fallback_failure(
        self, *_mocks
    ):
        result = validate_environment(
            api_key="fake",
            validate_api_key=True,
            preferred_model="gemini-2.5-flash",
            fallback_models=["gemini-3.6-flash", "gemini-3.7-flash"],
        )

        self.assertFalse(result["ok"])
        check_ids = [check["id"] for check in result["checks"]]
        self.assertIn("api_key", check_ids)
        self.assertIn("api_model_1", check_ids)
        self.assertIn("api_model_2", check_ids)

        api_check = next(c for c in result["checks"] if c["id"] == "api_key")
        middle_check = next(c for c in result["checks"] if c["id"] == "api_model_1")
        last_check = next(c for c in result["checks"] if c["id"] == "api_model_2")

        self.assertEqual(api_check["status"], "ok")
        self.assertEqual(middle_check["status"], "error")
        middle_details = middle_check.get("details", "")
        last_details = last_check.get("details")
        self.assertIn("gemini-3.6-flash", middle_details)
        self.assertNotIn("AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345", middle_details)
        self.assertIn("[API_KEY_REDACTED]", middle_details)
        self.assertEqual(last_check["status"], "ok")
        self.assertEqual(last_details, "gemini-3.7-flash")

    @patch(
        "jot.services.validation_service.resolve_ffmpeg",
        return_value="ffmpeg.exe",
    )
    def test_validate_environment_reports_session_output_root(self, *_mocks):
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "jot.services.validation_service.get_session_root",
                return_value=tmp,
            ):
                result = validate_environment(api_key=None, validate_api_key=False)

        output_check = next(c for c in result["checks"] if c["id"] == "output")
        self.assertTrue(result["ok"])
        self.assertEqual(output_check["label"], "Cartella sessioni/output")
        self.assertEqual(output_check["status"], "ok")
        self.assertEqual(
            output_check["message"], "Cartella sessioni/output scrivibile."
        )
        self.assertEqual(output_check.get("details"), tmp)

    @patch(
        "jot.services.validation_service.resolve_ffmpeg",
        return_value="ffmpeg.exe",
    )
    def test_validate_environment_errors_when_session_output_root_is_unwritable(
        self, *_mocks
    ):
        session_root = os.path.join(tempfile.gettempdir(), "unwritable-session-root")
        with (
            patch(
                "jot.services.validation_service.get_session_root",
                return_value=session_root,
            ),
            patch(
                "jot.services.validation_service._check_writable_dir",
                side_effect=[(True, "Scrittura consentita."), (False, "no write")],
            ),
        ):
            result = validate_environment(api_key=None, validate_api_key=False)

        output_check = next(c for c in result["checks"] if c["id"] == "output")
        self.assertFalse(result["ok"])
        self.assertEqual(output_check["status"], "error")
        self.assertEqual(
            output_check["message"], "Cartella sessioni/output non scrivibile."
        )
        output_details = output_check.get("details", "")
        self.assertIn(f"Percorso: {session_root}", output_details)
        self.assertIn("Errore: no write", output_details)
        self.assertIn("Rimedio:", output_details)

    @patch(
        "jot.services.validation_service.resolve_ffmpeg",
        return_value="ffmpeg",
    )
    def test_validate_environment_reports_ffmpeg_failure(self, *_mocks):
        with patch(
            "jot.services.validation_service._check_ffmpeg_execution",
            return_value=(False, "binary not found"),
        ):
            result = validate_environment(api_key=None, validate_api_key=False)
        self.assertFalse(result["ok"])
        ffmpeg_check = next(c for c in result["checks"] if c["id"] == "ffmpeg")
        self.assertEqual(ffmpeg_check["status"], "error")
        self.assertEqual(
            ffmpeg_check["message"], "FFmpeg non trovato o non utilizzabile."
        )
        self.assertIn("binary not found", ffmpeg_check.get("details", ""))


class CheckFfmpegExecutionTests(unittest.TestCase):
    @patch("subprocess.run")
    def test_ffmpeg_execution_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="ffmpeg version 7.0 Copyright\nExtra info"
        )
        ok, detail = _check_ffmpeg_execution("ffmpeg")
        self.assertTrue(ok)
        self.assertEqual(detail, "ffmpeg version 7.0 Copyright")

    @patch("subprocess.run")
    def test_ffmpeg_execution_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="unrecognized option"
        )
        ok, detail = _check_ffmpeg_execution("ffmpeg")
        self.assertFalse(ok)
        self.assertIn("FFmpeg ha restituito codice 1", detail)
        self.assertIn("unrecognized option", detail)

    @patch("subprocess.run", side_effect=FileNotFoundError("not found"))
    def test_ffmpeg_execution_exception(self, _mock_run):
        ok, detail = _check_ffmpeg_execution("ffmpeg")
        self.assertFalse(ok)
        self.assertIn("not found", detail)


class CheckWritableDirTests(unittest.TestCase):
    def test_returns_true_when_directory_is_writable(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, msg = _check_writable_dir(tmp)
        self.assertTrue(ok)
        self.assertIn("consentita", msg)

    def test_returns_true_even_when_remove_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("os.remove", side_effect=OSError("locked")):
                ok, msg = _check_writable_dir(tmp)
            probe = os.path.join(tmp, ".jot_write_test")
            if os.path.exists(probe):
                os.remove(probe)
        self.assertTrue(ok)
        self.assertIn("consentita", msg)

    def test_returns_false_when_write_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("builtins.open", side_effect=PermissionError("no write")):
                ok, msg = _check_writable_dir(tmp)
        self.assertFalse(ok)
        self.assertIn("no write", msg)


@patch(
    "jot.services.validation_service._check_ffmpeg_execution",
    return_value=(True, "ffmpeg version 7.0"),
)
class TestValidationKeyringCheck(unittest.TestCase):
    """validate_environment keyring check — only emitted on non-Windows."""

    @patch(
        "jot.services.validation_service.platform.system",
        return_value="Darwin",
    )
    @patch(
        "jot.services.validation_service.resolve_ffmpeg",
        return_value="ffmpeg",
    )
    def test_keyring_check_status_ok_when_keyring_accessible(self, *_mocks):
        mock_kr = MagicMock()
        mock_kr.get_password.return_value = None
        with (
            patch(
                "jot.services.validation_service.get_session_root",
                return_value=".",
            ),
            patch.dict(sys.modules, {"keyring": mock_kr}),
        ):
            result = validate_environment(api_key=None, validate_api_key=False)

        keyring_check = next(
            (c for c in result["checks"] if c["id"] == "keyring"), None
        )
        self.assertIsNotNone(
            keyring_check, "keyring check must be present on non-Windows"
        )
        self.assertEqual(keyring_check["status"], "ok")  # type: ignore[index]
        self.assertIn("protetta", keyring_check["message"])  # type: ignore[index]

    @patch(
        "jot.services.validation_service.platform.system",
        return_value="Darwin",
    )
    @patch(
        "jot.services.validation_service.resolve_ffmpeg",
        return_value="ffmpeg",
    )
    def test_keyring_check_status_warning_when_keyring_unavailable(self, *_mocks):
        mock_kr = MagicMock()
        mock_kr.get_password.side_effect = RuntimeError("no keyring backend")
        with (
            patch(
                "jot.services.validation_service.get_session_root",
                return_value=".",
            ),
            patch.dict(sys.modules, {"keyring": mock_kr}),
        ):
            result = validate_environment(api_key=None, validate_api_key=False)

        keyring_check = next(
            (c for c in result["checks"] if c["id"] == "keyring"), None
        )
        self.assertIsNotNone(keyring_check)
        self.assertEqual(keyring_check["status"], "warning")  # type: ignore[index]
        self.assertIn("no keyring backend", keyring_check["details"])  # type: ignore[typeddict-item]

    @patch(
        "jot.services.validation_service.platform.system",
        return_value="Windows",
    )
    @patch(
        "jot.services.validation_service.resolve_ffmpeg",
        return_value="ffmpeg",
    )
    def test_keyring_check_absent_on_windows(self, *_mocks):
        with patch(
            "jot.services.validation_service.get_session_root",
            return_value=".",
        ):
            result = validate_environment(api_key=None, validate_api_key=False)
        check_ids = [c["id"] for c in result["checks"]]
        self.assertNotIn("keyring", check_ids)

    @patch(
        "jot.services.validation_service.resolve_ffmpeg",
        return_value="ffmpeg",
    )
    @patch("jot.services.validation_service.shutil.disk_usage")
    def test_disk_space_warning_when_low_space(self, mock_disk, *_mocks):
        from collections import namedtuple

        DiskUsage = namedtuple("DiskUsage", ["total", "used", "free"])
        mock_disk.return_value = DiskUsage(
            total=100 * 1024 * 1024 * 1024,
            used=99 * 1024 * 1024 * 1024,
            free=500 * 1024 * 1024,
        )

        with patch(
            "jot.services.validation_service.get_session_root",
            return_value=".",
        ):
            result = validate_environment(api_key=None, validate_api_key=False)

        output_check = next(c for c in result["checks"] if c["id"] == "output")
        self.assertEqual(output_check["status"], "warning")
        self.assertIn("Spazio su disco quasi esaurito", output_check["message"])

    def test_generate_diagnostic_report_redacts_api_keys(self, *_mocks):
        from jot.services.validation_service import generate_diagnostic_report

        fake_key = "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
        report = generate_diagnostic_report(
            api_key=fake_key,
            preferred_model="gemini-2.5-flash",
        )

        self.assertIn("Report Diagnostico jot", report)
        self.assertIn("no remote API validation", report)
        self.assertNotIn(fake_key, report)
        self.assertNotIn("AIzaSy...2345", report)

    @patch("jot.services.diagnostics_service.collect_files")
    def test_report_does_not_run_remote_checks(self, collect, *_mocks):
        from jot.services.validation_service import generate_diagnostic_report

        collect.return_value = {"report.md": "Local report"}
        with patch("jot.services.validation_service.validate_environment") as validate:
            report = generate_diagnostic_report(api_key="should_not_be_sent")
        self.assertEqual(report, "Local report")
        validate.assert_not_called()

    @patch(
        "jot.services.validation_service.platform.system",
        return_value="Windows",
    )
    @patch(
        "jot.services.validation_service.get_session_root",
        return_value=".",
    )
    @patch(
        "jot.services.validation_service.resolve_ffmpeg",
        return_value="ffmpeg.exe",
    )
    def test_validate_environment_with_missing_api_key_returns_warning_summary(
        self, *_mocks
    ):
        result = validate_environment(
            api_key="",
            validate_api_key=True,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("has_warnings"))
        self.assertEqual(
            result["summary"],
            "Ambiente pronto con avvisi: verifica le segnalazioni.",
        )
        api_check = next(c for c in result["checks"] if c["id"] == "api_key")
        self.assertEqual(api_check["status"], "warning")
        self.assertEqual(
            api_check["message"], "API key assente: controllo remoto saltato."
        )

    @patch(
        "jot.services.validation_service.platform.system",
        return_value="Windows",
    )
    @patch(
        "jot.services.validation_service.get_session_root",
        return_value=".",
    )
    @patch(
        "jot.services.validation_service.resolve_ffmpeg",
        return_value="ffmpeg.exe",
    )
    @patch("google.genai.Client", _AlwaysOkClient)
    def test_validate_environment_all_ok_has_no_warnings(self, *_mocks):
        result = validate_environment(
            api_key="fake",
            validate_api_key=True,
            preferred_model="gemini-2.5-flash",
            fallback_models=[],
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result.get("has_warnings"))
        self.assertEqual(result["summary"], "Ambiente pronto.")

    @patch(
        "jot.services.validation_service.platform.system",
        return_value="Linux",
    )
    @patch(
        "jot.services.validation_service.get_session_root",
        return_value=".",
    )
    @patch(
        "jot.services.validation_service.resolve_ffmpeg",
        return_value="ffmpeg",
    )
    @patch("google.genai.Client", _AlwaysOkClient)
    def test_validate_environment_all_ok_non_windows_with_keyring_has_no_warnings(
        self, *_mocks
    ):
        mock_kr = MagicMock()
        mock_kr.get_password.return_value = None
        with patch.dict(sys.modules, {"keyring": mock_kr}):
            result = validate_environment(
                api_key="fake",
                validate_api_key=True,
                preferred_model="gemini-2.5-flash",
                fallback_models=[],
            )
            self.assertTrue(result["ok"])
            self.assertFalse(result.get("has_warnings"))
            self.assertEqual(result["summary"], "Ambiente pronto.")


if __name__ == "__main__":
    unittest.main()

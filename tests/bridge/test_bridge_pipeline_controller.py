import unittest
from types import SimpleNamespace
from unittest.mock import patch

from jot.bridge.controllers.pipeline_controller import (
    PipelineControllerMixin,
    _clear_retry_state_if_forced,
    _reset_governor_if_needed,
)


class DummyPipelineController(PipelineControllerMixin):
    def __init__(self):
        self.console_messages: list[str] = []

    def _push_console(self, msg: str) -> None:
        self.console_messages.append(msg)


class TestPipelineControllerConfigPersistence(unittest.TestCase):
    def test_persist_processing_config_success(self):
        ctrl = DummyPipelineController()
        with patch(
            "jot.bridge.controllers.pipeline_controller.save_config"
        ) as mock_save:
            ctrl._persist_processing_config(
                "key123", "gemini-2.5-flash", ["gemini-2.5-pro"]
            )
            mock_save.assert_called_once_with(
                "key123",
                preferred_model="gemini-2.5-flash",
                fallback_models=["gemini-2.5-pro"],
            )
            self.assertEqual(ctrl.console_messages, [])

    def test_persist_processing_config_os_error_pushes_console(self):
        ctrl = DummyPipelineController()
        with patch(
            "jot.bridge.controllers.pipeline_controller.save_config",
            side_effect=OSError("Permission denied"),
        ):
            ctrl._persist_processing_config("key123", None, None)
            self.assertEqual(len(ctrl.console_messages), 1)
            self.assertIn("Impossibile salvare", ctrl.console_messages[0])
            self.assertIn("Permission denied", ctrl.console_messages[0])

    def test_persist_processing_config_unexpected_exception_pushes_console(self):
        ctrl = DummyPipelineController()
        with patch(
            "jot.bridge.controllers.pipeline_controller.save_config",
            side_effect=RuntimeError("Disk corrupted"),
        ):
            ctrl._persist_processing_config("key123", None, None)
            self.assertEqual(len(ctrl.console_messages), 1)
            self.assertIn("Errore imprevisto", ctrl.console_messages[0])
            self.assertIn("Disk corrupted", ctrl.console_messages[0])


class TestForcedCircuitRetry(unittest.TestCase):
    def test_file_force_retry_resets_global_governor(self):
        with patch("jot.services.generation_service.reset_global_governor") as reset:
            _reset_governor_if_needed(
                [
                    {
                        "id": "f1",
                        "path": "audio.mp3",
                        "name": "audio",
                        "force_retry": True,
                    }
                ],
                False,
            )

        reset.assert_called_once_with()

    def test_forced_retry_clears_only_circuit_pause_metadata(self):
        session = {
            "retry_state": {"state": "paused"},
            "last_error": "circuit_breaker_paused",
            "last_error_detail": "503 Service Unavailable",
            "phase1": {"chunks_done": 4},
        }
        with (
            patch(
                "jot.bridge.controllers.pipeline_controller.resolve_session_paths",
                return_value=SimpleNamespace(session_path="session.json"),
            ),
            patch(
                "jot.bridge.controllers.pipeline_controller.os.path.exists",
                return_value=True,
            ),
            patch(
                "jot.bridge.controllers.pipeline_controller.load_session",
                return_value=session,
            ),
            patch("jot.bridge.controllers.pipeline_controller.save_session") as save,
        ):
            _clear_retry_state_if_forced(
                {"id": "f1", "path": "audio.mp3", "name": "audio", "force_retry": True},
                False,
            )

        self.assertIsNone(session["retry_state"])
        self.assertIsNone(session["last_error"])
        self.assertIsNone(session["last_error_detail"])
        self.assertEqual(session["phase1"]["chunks_done"], 4)
        save.assert_called_once_with("session.json", session)

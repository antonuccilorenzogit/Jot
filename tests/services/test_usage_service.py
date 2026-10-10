import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import patch

from jot.services import usage_service


class UsageServiceV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.config_dir_patch = patch(
            "jot.services.usage_service.get_config_dir",
            return_value=self.tmp_dir.name,
        )
        self.config_dir_patch.start()
        usage_service.reset_daily_usage_for_tests()

    def tearDown(self):
        self.config_dir_patch.stop()
        self.tmp_dir.cleanup()

    def test_schema_v2_defaults_and_attempt_recording(self):
        key = "AIzaSyTest1234567890abcdef"
        usage_service.record_request_attempt(key, "gemini-2.5-flash")
        usage_service.record_request_success(key, "gemini-2.5-flash")

        data = usage_service.get_daily_usage(
            primary_key=key,
            primary_model="gemini-2.5-flash",
        )

        self.assertEqual(data["schema_version"], 2)
        self.assertEqual(data["primary_status"], "operational")
        self.assertEqual(data["telemetry"]["requests_sent"], 1)
        self.assertEqual(data["telemetry"]["responses_succeeded"], 1)
        self.assertEqual(data["telemetry"]["final_failures"], 0)
        self.assertEqual(data["telemetry"]["retries_total"], 0)

        # Check credential status
        cred = next(c for c in data["credentials"] if c["is_primary"])
        self.assertEqual(cred["operational_status"], "active")
        self.assertEqual(cred["masked_key"][:6], "AIzaSy")

    def test_project_quota_exhaustion_does_not_switch_model(self):
        key = "AIzaSyTest1234567890abcdef"
        usage_service.mark_quota_exhausted("gemini-2.5-flash")

        data = usage_service.get_daily_usage(
            primary_key=key,
            primary_model="gemini-2.5-flash",
            fallback_models=["gemini-3.6-flash"],
        )

        # 429/RPD never changes model automatically: a configured model fallback
        # does not make the queue runnable again.
        self.assertEqual(data["primary_status"], "quota_exhausted")
        self.assertFalse(data["is_degraded_mode"])
        self.assertIsNone(data["degraded_reason"])

    def test_rate_limiting_and_retry_after(self):
        key = "AIzaSyKey111111111111111111"
        usage_service.mark_rate_limited("gemini-2.5-flash", retry_after_seconds=25.0)

        data = usage_service.get_daily_usage(
            primary_key=key,
            primary_model="gemini-2.5-flash",
        )

        self.assertEqual(data["primary_status"], "rate_limited")
        self.assertIsNotNone(data["retry_after_seconds"])
        self.assertGreater(data["retry_after_seconds"], 0)
        self.assertIn("rate limit", data["status_message"].lower())

    def test_credential_error_mapping(self):
        key = "AIzaSyInvalidKey1234567890"
        usage_service.mark_credential_status(
            key, "invalid", error_msg="API key not valid", code=401
        )

        data = usage_service.get_daily_usage(primary_key=key)
        self.assertEqual(data["primary_status"], "credential_error")
        self.assertIn("401", data["status_message"])

    def test_work_stats_tracking(self):
        usage_service.record_work_completed("chunks", count=5)
        usage_service.record_work_completed("macro", count=2)
        usage_service.record_work_completed("sbobine", count=1)

        data = usage_service.get_daily_usage(primary_key="AIzaSyKey111111111111111111")
        self.assertEqual(data["work_stats"]["chunks_completed"], 5)
        self.assertEqual(data["work_stats"]["revisions_completed"], 2)
        self.assertEqual(data["work_stats"]["sbobine_completed"], 1)

    def test_v1_to_v2_migration_preserves_keys(self):
        # Create a mock legacy v1 api_usage.json
        legacy_data = {
            "quota_date": "2026-09-01",
            "keys": {
                "hash123": {
                    "id": "hash123",
                    "masked_key": "AIzaSy...1111",
                    "is_primary": True,
                    "models": {
                        "gemini-2.5-flash": {
                            "limit": 20,
                            "used_today": 12,
                            "is_exhausted": False,
                            "last_reset_iso": "2026-09-01T10:00:00Z",
                        }
                    },
                }
            },
        }
        usage_file = os.path.join(self.tmp_dir.name, "api_usage.json")
        with open(usage_file, "w", encoding="utf-8") as f:
            json.dump(legacy_data, f)

        # Loading should trigger migration
        data = usage_service.get_daily_usage(
            primary_key="AIzaSyFakeKey111111111111111",
            primary_model="gemini-2.5-flash",
        )
        self.assertEqual(data["schema_version"], 2)
        self.assertTrue(len(data["credentials"]) >= 1)

        # Verify raw file is now valid v2 JSON
        with open(usage_file, encoding="utf-8") as f:
            saved_json = json.load(f)
        self.assertEqual(saved_json["schema_version"], 2)
        self.assertIn("project_limits", saved_json)
        self.assertIn("telemetry", saved_json)

    def test_supported_models_alignment_and_pruning(self):
        # Create an api_usage.json containing obsolete models
        stale_data = {
            "schema_version": 2,
            "quota_date": "2026-09-01",
            "project_limits": {
                "gemini-3.1-flash-lite-preview": {
                    "model_name": "gemini-3.1-flash-lite-preview",
                    "rpd_limit": 500,
                    "rpm_limit": 15,
                    "tpm_limit": 1000000,
                    "source": "configured",
                    "quota_state": "normal",
                },
                "gemini-2.5-flash": {
                    "model_name": "gemini-2.5-flash",
                    "rpd_limit": 20,
                    "rpm_limit": 5,
                    "tpm_limit": 250000,
                    "source": "configured",
                    "quota_state": "normal",
                },
            },
            "telemetry": {},
            "work_stats": {},
            "credentials": {},
        }
        usage_file = os.path.join(self.tmp_dir.name, "api_usage.json")
        with open(usage_file, "w", encoding="utf-8") as f:
            json.dump(stale_data, f)

        data = usage_service.get_daily_usage(
            primary_key="AIzaSyKey111111111111111111",
            primary_model="gemini-2.5-flash",
        )

        # Stale model should be pruned
        self.assertNotIn("gemini-3.1-flash-lite-preview", data["project_limits"])
        # All SUPPORTED_MODELS should be present
        for m in [
            "gemini-2.5-flash",
            "gemini-3.6-flash",
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.5-flash",
        ]:
            self.assertIn(m, data["project_limits"])

    def test_multi_account_key_rotation(self):
        key1 = "AIzaSyAccount1Key111111111"
        key2 = "AIzaSyAccount2Key222222222"

        # Key 1 hits quota exhaustion on gemini-2.5-flash
        usage_service.mark_quota_exhausted("gemini-2.5-flash", api_key=key1)

        # Querying with key1 as primary and key2 as fallback
        data1 = usage_service.get_daily_usage(
            primary_key=key1,
            fallback_keys=[key2],
            primary_model="gemini-2.5-flash",
        )
        self.assertEqual(data1["primary_status"], "degraded")
        self.assertTrue(data1["is_degraded_mode"])
        self.assertIn("riserva", str(data1["status_message"]).lower())

        # When switching primary_key to key2 (from Account 2), quota is fresh!
        data2 = usage_service.get_daily_usage(
            primary_key=key2,
            fallback_keys=[key1],
            primary_model="gemini-2.5-flash",
        )
        self.assertEqual(data2["primary_status"], "operational")

    def test_pacific_date_reset(self):
        key = "AIzaSyKey111111111111111111"
        usage_service.record_request_attempt(key, "gemini-2.5-flash")
        usage_service.record_work_completed("sbobine", 5)
        usage_service.mark_quota_exhausted("gemini-2.5-flash")

        # Simulate next day in Pacific time
        fake_next_day = "2099-01-01"
        with patch(
            "jot.services.usage_service.get_pacific_date_string",
            return_value=fake_next_day,
        ):
            data = usage_service.get_daily_usage(
                primary_key=key,
                primary_model="gemini-2.5-flash",
            )
            self.assertEqual(
                data["project_limits"]["gemini-2.5-flash"]["quota_state"], "normal"
            )
            self.assertEqual(data["primary_status"], "operational")
            self.assertEqual(data["quota_date"], fake_next_day)
            self.assertEqual(data["work_stats"]["sbobine_completed"], 0)
            self.assertEqual(data["telemetry"]["requests_sent"], 0)

    def test_force_refresh_preserves_daily_quota_exhaustion(self):
        key = "AIzaSyKey111111111111111111"
        usage_service.mark_quota_exhausted("gemini-2.5-flash", api_key=key)

        with patch("google.genai.Client") as mock_client:
            mock_client.return_value.models.get.return_value = True
            data = usage_service.get_daily_usage(
                primary_key=key,
                primary_model="gemini-2.5-flash",
                force_refresh=True,
            )
            # Preserves exhaustion for the day until midnight PT
            self.assertEqual(data["primary_status"], "quota_exhausted")
            self.assertEqual(
                data["project_limits"]["gemini-2.5-flash"]["quota_state"],
                "rpd_exhausted",
            )

    def test_force_refresh_with_fallback_preserves_exhausted_models(self):
        primary_key = "AIzaSyKey111111111111111111"
        fb_key = "AIzaSyKey222222222222222222"
        usage_service.mark_quota_exhausted("gemini-2.5-flash", api_key=primary_key)

        with patch("google.genai.Client") as mock_client:
            mock_client.return_value.models.get.return_value = True
            data = usage_service.get_daily_usage(
                primary_key=primary_key,
                fallback_keys=[fb_key],
                primary_model="gemini-2.5-flash",
                force_refresh=True,
            )
            # Degraded because primary is exhausted but fallback is available
            self.assertEqual(data["primary_status"], "degraded")
            # Model itself is normal because fallback is ready
            self.assertEqual(
                data["project_limits"]["gemini-2.5-flash"]["quota_state"], "normal"
            )
            primary_cred = next(c for c in data["credentials"] if c["is_primary"])
            self.assertIn("gemini-2.5-flash", primary_cred["exhausted_models"])
            fb_cred = next(c for c in data["credentials"] if not c["is_primary"])
            self.assertEqual(fb_cred["exhausted_models"], [])


if __name__ == "__main__":
    unittest.main()

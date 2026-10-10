"""Exercise persistent and process-only credentials through the actual config API."""

import json
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from jot.core import credentials
from jot.services import config_service as cs
from tests.bridge.test_controllers import DummySettingsHost


@pytest.fixture(params=["Windows", "Darwin"])
def store(tmp_path, monkeypatch, request):
    monkeypatch.setattr(cs, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(cs, "LEGACY_CONFIG_FILE", str(tmp_path / "legacy.json"))
    monkeypatch.setattr(cs.platform, "system", lambda: request.param)
    cs._config_cache = None
    cs._config_cache_gen = 0
    backend = {"primary": "", "fallback": []}
    monkeypatch.setattr(
        cs, "_dpapi_protect_text_windows", lambda value: "protected:" + value
    )
    monkeypatch.setattr(
        cs,
        "_dpapi_unprotect_text_windows",
        lambda value: value.removeprefix("protected:"),
    )
    monkeypatch.setattr(cs, "_keyring_get_api_key", lambda: backend["primary"])
    monkeypatch.setattr(cs, "_keyring_get_fallback_keys", lambda: backend["fallback"])

    def save(group, value):
        backend[group] = value
        return True

    monkeypatch.setattr(
        cs, "_keyring_set_api_key", lambda value: save("primary", value)
    )
    monkeypatch.setattr(
        cs, "_keyring_set_fallback_keys", lambda value: save("fallback", value)
    )
    monkeypatch.setattr(cs, "_keyring_delete_api_key", lambda: save("primary", ""))
    monkeypatch.setattr(
        cs, "_keyring_delete_fallback_keys", lambda: save("fallback", [])
    )
    yield backend
    cs._config_cache = None


def fail_protection(monkeypatch):
    monkeypatch.setattr(cs, "_dpapi_protect_text_windows", lambda _: "")
    monkeypatch.setattr(cs, "_keyring_set_api_key", lambda _: False)
    monkeypatch.setattr(cs, "_keyring_set_fallback_keys", lambda _: False)


def disk():
    with open(cs.CONFIG_FILE, encoding="utf-8") as handle:
        return json.load(handle)


def test_failed_replacement_preserves_old_store_and_runtime_across_cache(
    store, monkeypatch, tmp_path
):
    cs.save_config("old-primary", ["old-reserve"])
    old_disk = disk()
    fail_protection(monkeypatch)
    states = cs.save_config("new-secret", ["new-reserve"])
    assert states == {"primary": "session_only", "fallback": "session_only"}
    assert disk() == old_disk
    assert "new-secret" not in json.dumps(disk())
    assert "new-reserve" not in json.dumps(disk())
    for _ in range(2):
        loaded = cs.load_config()
        assert loaded["api_key"] == "new-secret"
        assert loaded["fallback_keys"] == ["new-reserve"]
    cs._config_cache_ts = 0
    cs.save_session_root_to_config(str(tmp_path / "sessions"))
    cs.save_config(None, preferred_model="gemini-3.5-flash")
    assert cs.load_config()["api_key"] == "new-secret"
    assert cs.load_config()["fallback_keys"] == ["new-reserve"]
    # Simulate a restart: process-only state must disappear, stored credentials survive.
    cs._credential_overrides.clear()
    cs._config_cache = None
    assert cs.load_config()["api_key"] == "old-primary"
    assert cs.load_config()["fallback_keys"] == ["old-reserve"]


def test_first_failed_save_never_writes_plaintext_even_legacy_mode(store, monkeypatch):
    fail_protection(monkeypatch)
    monkeypatch.setenv("JOT_WRITE_LEGACY_CONFIG", "1")
    cs.save_config("new-secret", ["new-reserve"])
    for path in (cs.CONFIG_FILE, cs.LEGACY_CONFIG_FILE):
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
        assert "new-secret" not in raw and "new-reserve" not in raw
    assert cs.load_config()["api_key"] == "new-secret"


def test_omitted_values_keep_override_and_empty_values_clear(store, monkeypatch):
    fail_protection(monkeypatch)
    cs.save_config("temporary", ["reserve"])
    cs.save_config(None)
    assert cs.load_config()["api_key"] == "temporary"
    assert cs.load_config()["fallback_keys"] == ["reserve"]
    cs.save_config("", [])
    assert cs.load_config()["api_key"] == ""
    assert cs.load_config()["fallback_keys"] == []


def test_successful_retry_removes_override(store, monkeypatch):
    original = cs._dpapi_protect_text_windows
    setter = cs._keyring_set_api_key
    fail_protection(monkeypatch)
    cs.save_config("temporary")
    monkeypatch.setattr(cs, "_dpapi_protect_text_windows", original)
    monkeypatch.setattr(cs, "_keyring_set_api_key", setter)
    assert cs.save_config("temporary")["primary"] == "protected"
    assert (cs.CONFIG_FILE, "primary") not in cs._credential_overrides
    assert cs.load_config()["credential_storage"]["primary"] == "protected"


def test_legacy_failure_preserves_original_without_copy_and_success_migrates(
    store, monkeypatch
):
    original = cs._dpapi_protect_text_windows
    setter = cs._keyring_set_api_key
    fallback_setter = cs._keyring_set_fallback_keys
    raw = {"api_key": "legacy-primary", "fallback_keys": ["legacy-reserve"]}
    with open(cs.LEGACY_CONFIG_FILE, "w", encoding="utf-8") as handle:
        json.dump(raw, handle)
    fail_protection(monkeypatch)
    loaded = cs.load_config()
    assert loaded["credential_storage"] == {
        "primary": "legacy_plaintext",
        "fallback": "legacy_plaintext",
    }
    assert loaded["fallback_keys"] == ["legacy-reserve"]
    assert not cs.os.path.exists(cs.CONFIG_FILE)
    cs.save_session_root_to_config("sessions")
    assert not cs.os.path.exists(cs.CONFIG_FILE)
    monkeypatch.setattr(cs, "_dpapi_protect_text_windows", original)
    monkeypatch.setattr(cs, "_keyring_set_api_key", setter)
    monkeypatch.setattr(cs, "_keyring_set_fallback_keys", fallback_setter)
    cs._config_cache = None
    loaded = cs.load_config()
    assert loaded["credential_storage"] == {
        "primary": "protected",
        "fallback": "protected",
    }
    assert not cs.os.path.exists(cs.LEGACY_CONFIG_FILE)
    assert not disk()["api_key"] and not disk()["fallback_keys"]


def test_deletion_failure_masks_previous_keys_for_process(store, monkeypatch):
    if cs.platform.system() == "Windows":
        return  # DPAPI deletion is the atomic removal of the config fields.
    cs.save_config("old", ["reserve"])
    monkeypatch.setattr(cs, "_keyring_delete_api_key", lambda: False)
    monkeypatch.setattr(cs, "_keyring_delete_fallback_keys", lambda: False)
    assert cs.save_config("", []) == {
        "primary": "session_only",
        "fallback": "session_only",
    }
    assert cs.load_config()["api_key"] == ""
    assert cs.load_config()["fallback_keys"] == []
    cs._config_cache = None
    assert cs.load_config()["api_key"] == ""


def test_stale_load_cannot_overwrite_new_process_override(store, monkeypatch):
    cs.save_config("old")
    cs._config_cache = None
    fail_protection(monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    original = cs._read_config_from_disk_paths

    def delayed_read():
        result = original()
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(cs, "_read_config_from_disk_paths", delayed_read)
    result = []
    thread = threading.Thread(target=lambda: result.append(cs.load_config()))
    thread.start()
    assert entered.wait(5)
    cs.save_config("new")
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert result[0]["api_key"] == "new"
    assert cs.load_config()["api_key"] == "new"


def test_failed_replacement_still_warns_about_old_plaintext_on_disk(store, monkeypatch):
    raw = {"api_key": "old-plaintext", "fallback_keys": ["old-reserve"]}
    with open(cs.CONFIG_FILE, "w", encoding="utf-8") as handle:
        json.dump(raw, handle)
    fail_protection(monkeypatch)
    cs.save_config("new-secret", ["new-reserve"])
    loaded = cs.load_config()
    assert loaded["api_key"] == "new-secret"
    assert loaded["credential_storage"]["primary"] == "session_only"
    assert loaded["api_key_insecure"]
    assert "chiaro" in loaded["api_key_insecure_reason"]
    assert disk() == raw | {
        "preferred_model": cs.DEFAULT_MODEL,
        "fallback_models": list(cs.DEFAULT_FALLBACK_MODELS),
    }


def test_real_fallback_delete_helper_failure_keeps_clear_override(store, monkeypatch):
    if cs.platform.system() == "Windows":
        return
    cs.save_config("old", ["reserve"])
    fake_keyring = MagicMock()
    fake_keyring.delete_password.side_effect = RuntimeError("locked keyring")
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.setattr(
        cs, "_keyring_delete_fallback_keys", credentials.keyring_delete_fallback_keys
    )
    assert cs.save_config(None, [])["fallback"] == "session_only"
    assert cs.load_config()["fallback_keys"] == []
    cs._config_cache = None
    assert cs.load_config()["fallback_keys"] == []


def test_protected_save_after_failed_migration_cleans_legacy(store, monkeypatch):
    legacy = Path(cs.LEGACY_CONFIG_FILE)
    legacy.write_text(
        json.dumps({"api_key": "legacy-primary", "fallback_keys": ["legacy-reserve"]}),
        encoding="utf-8",
    )
    with monkeypatch.context() as failed:
        fail_protection(failed)
        assert cs.load_config()["api_key_insecure"]
    assert cs.save_config("replacement", ["replacement-reserve"]) == {
        "primary": "protected",
        "fallback": "protected",
    }
    assert not legacy.exists()
    assert not Path(str(legacy) + ".migrated").exists()
    assert not cs.load_config()["api_key_insecure"]
    cs._credential_overrides.clear()
    cs._config_cache = None
    assert cs.load_config()["api_key"] == "replacement"


@pytest.mark.parametrize("failure", ["scrub", "rename", "delete"])
def test_legacy_cleanup_failure_preserves_truthful_warning(store, monkeypatch, failure):
    legacy = Path(cs.LEGACY_CONFIG_FILE)
    legacy.write_text(
        json.dumps({"api_key": "legacy-primary", "fallback_keys": ["legacy-reserve"]}),
        encoding="utf-8",
    )
    original_write = cs._atomic_write_json
    original_replace = cs.os.replace
    original_remove = cs.os.remove

    def write(path, data):
        if failure == "scrub" and path == str(legacy):
            raise OSError("legacy file locked")
        return original_write(path, data)

    def replace(source, target):
        if failure == "rename" and source == str(legacy):
            raise OSError("legacy file locked")
        return original_replace(source, target)

    def remove(path):
        if failure == "delete" and path == str(legacy) + ".migrated":
            raise OSError("legacy file locked")
        return original_remove(path)

    monkeypatch.setattr(cs, "_atomic_write_json", write)
    monkeypatch.setattr(cs.os, "replace", replace)
    monkeypatch.setattr(cs.os, "remove", remove)
    cs.save_config("replacement", ["replacement-reserve"])
    for _ in range(2):
        loaded = cs.load_config()
        assert loaded["api_key"] == "replacement"
        assert loaded["api_key_insecure"] is (failure == "scrub")
    leftovers = [
        path for path in (legacy, Path(str(legacy) + ".migrated")) if path.exists()
    ]
    assert leftovers
    for path in leftovers:
        raw = path.read_text(encoding="utf-8")
        assert ("legacy-primary" in raw) is (failure == "scrub")
        assert ("legacy-reserve" in raw) is (failure == "scrub")


def test_old_plaintext_migrated_copy_is_reported(store):
    cs.save_config("protected-key")
    Path(cs.LEGACY_CONFIG_FILE + ".migrated").write_text(
        json.dumps({"fallback_keys": ["old-plaintext"]}), encoding="utf-8"
    )
    loaded = cs.load_config()
    assert loaded["credential_storage"]["primary"] == "protected"
    assert loaded["api_key_insecure"]


@pytest.mark.parametrize("source", ["modern", "legacy"])
@pytest.mark.parametrize("existing_groups", ["primary", "fallback", "both"])
def test_plaintext_migration_preserves_existing_keyring_groups(
    store, monkeypatch, source, existing_groups
):
    if cs.platform.system() == "Windows":
        pytest.skip("Keyring precedence applies to macOS/Linux")
    if existing_groups in {"primary", "both"}:
        store["primary"] = "current-primary"
    if existing_groups in {"fallback", "both"}:
        store["fallback"] = ["current-reserve"]
    expected_primary = store["primary"] or "legacy-primary"
    expected_fallback = store["fallback"] or ["legacy-reserve"]
    primary_setter = MagicMock(wraps=cs._keyring_set_api_key)
    fallback_setter = MagicMock(wraps=cs._keyring_set_fallback_keys)
    monkeypatch.setattr(cs, "_keyring_set_api_key", primary_setter)
    monkeypatch.setattr(cs, "_keyring_set_fallback_keys", fallback_setter)
    path = cs.CONFIG_FILE if source == "modern" else cs.LEGACY_CONFIG_FILE
    Path(path).write_text(
        json.dumps({"api_key": "legacy-primary", "fallback_keys": ["legacy-reserve"]}),
        encoding="utf-8",
    )
    for _ in range(2):
        cs._config_cache = None
        loaded = cs.load_config()
        assert loaded["api_key"] == expected_primary
        assert loaded["fallback_keys"] == expected_fallback
        assert loaded["credential_storage"] == {
            "primary": "protected",
            "fallback": "protected",
        }
        assert not loaded["api_key_insecure"]
    assert store == {"primary": expected_primary, "fallback": expected_fallback}
    assert primary_setter.call_count == (existing_groups == "fallback")
    assert fallback_setter.call_count == (existing_groups == "primary")
    assert not disk()["api_key"] and not disk()["fallback_keys"]


@pytest.mark.parametrize("failure", [None, "scrub", "delete"])
def test_protected_save_cleans_isolated_migrated_copy(store, monkeypatch, failure):
    cs.save_config("protected-key", ["protected-reserve"])
    migrated = Path(cs.LEGACY_CONFIG_FILE + ".migrated")
    migrated.write_text(
        json.dumps({"api_key": "old-primary", "fallback_keys": ["old-reserve"]}),
        encoding="utf-8",
    )
    original_write = cs._atomic_write_json
    original_remove = cs.os.remove

    def write(path, data):
        if failure == "scrub" and path == str(migrated):
            raise OSError("migrated copy locked")
        return original_write(path, data)

    def remove(path):
        if failure == "delete" and path == str(migrated):
            raise OSError("migrated copy locked")
        return original_remove(path)

    monkeypatch.setattr(cs, "_atomic_write_json", write)
    monkeypatch.setattr(cs.os, "remove", remove)
    assert not Path(cs.LEGACY_CONFIG_FILE).exists()
    assert cs.load_config()["api_key_insecure"]
    assert cs.save_config("replacement", ["replacement-reserve"]) == {
        "primary": "protected",
        "fallback": "protected",
    }
    cs._credential_overrides.clear()
    cs._config_cache = None
    loaded = cs.load_config()
    assert loaded["api_key"] == "replacement"
    assert loaded["fallback_keys"] == ["replacement-reserve"]
    assert loaded["api_key_insecure"] is (failure == "scrub")
    assert migrated.exists() is (failure is not None)
    if migrated.exists():
        raw = migrated.read_text(encoding="utf-8")
        assert ("old-primary" in raw) is (failure == "scrub")
        assert ("old-reserve" in raw) is (failure == "scrub")


def test_bridge_reports_plaintext_when_legacy_scrub_fails(store, monkeypatch):
    from jot.bridge.controllers import settings_controller

    Path(cs.LEGACY_CONFIG_FILE).write_text(
        json.dumps({"api_key": "legacy-primary"}), encoding="utf-8"
    )
    original_write = cs._atomic_write_json

    def write(path, data):
        if path == cs.LEGACY_CONFIG_FILE:
            raise OSError("legacy file locked")
        return original_write(path, data)

    monkeypatch.setattr(cs, "_atomic_write_json", write)
    monkeypatch.setattr(settings_controller, "save_config", cs.save_config)
    monkeypatch.setattr(settings_controller, "load_config", cs.load_config)
    host = DummySettingsHost()
    saved = host.save_settings("replacement", [], cs.DEFAULT_MODEL, [])
    assert saved["ok"]
    assert saved["credential_storage"]["primary"] == "protected"
    assert saved["api_key_insecure"]
    assert "chiaro" in saved["api_key_insecure_reason"]
    assert host.load_settings()["api_key_insecure"]


@pytest.mark.parametrize("source", ["modern", "legacy"])
@pytest.mark.parametrize("existing_groups", ["primary", "fallback", "both"])
def test_keyring_precedence_survives_failed_plaintext_scrub(
    store, monkeypatch, source, existing_groups
):
    if cs.platform.system() == "Windows":
        pytest.skip("Keyring precedence applies to macOS/Linux")
    if existing_groups in {"primary", "both"}:
        store["primary"] = "current-primary"
    if existing_groups in {"fallback", "both"}:
        store["fallback"] = ["current-reserve"]
    raw = {"api_key": "obsolete-primary", "fallback_keys": ["obsolete-reserve"]}
    path = Path(cs.CONFIG_FILE if source == "modern" else cs.LEGACY_CONFIG_FILE)
    path.write_text(json.dumps(raw), encoding="utf-8")
    fail_protection(monkeypatch)
    writer = MagicMock(side_effect=OSError("read-only config"))
    monkeypatch.setattr(cs, "_atomic_write_json", writer)

    # The cache must retain both effective keys and the residual plaintext warning.
    for invalidate_cache in (True, False, True):
        if invalidate_cache:
            cs._config_cache = None
        loaded = cs.load_config()
        assert loaded["api_key"] == (store["primary"] or raw["api_key"])
        assert loaded["fallback_keys"] == (store["fallback"] or raw["fallback_keys"])
        assert loaded["credential_storage"] == {
            "primary": "protected" if store["primary"] else "legacy_plaintext",
            "fallback": "protected" if store["fallback"] else "legacy_plaintext",
        }
        assert loaded["api_key_insecure"]
        assert "chiaro" in loaded["api_key_insecure_reason"]
    assert writer.call_count == 2
    assert json.loads(path.read_text(encoding="utf-8")) == raw

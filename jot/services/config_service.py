"""
Configuration and credential management for jot.

Contains:
- User-home and config-file path resolution
- Re-exported DPAPI / Keyring credential helpers from core.credentials
- load_config / save_config
- Filesystem helpers: get_desktop_dir, safe_output_basename
- debug_log utility
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import threading
import time

from jot.core.credentials import (
    _KEYRING_SERVICE,
    _KEYRING_USER_API,
    _KEYRING_USER_FALLBACK_KEYS,
    KEYRING_SERVICE,
    KEYRING_USER_API,
    KEYRING_USER_FALLBACK_KEYS,
    _dpapi_make_blob_class,
    _dpapi_protect_text_windows,
    _dpapi_unprotect_text_windows,
    _dpapi_unprotect_text_windows_once,
    _keyring_delete_api_key,
    _keyring_delete_fallback_keys,
    _keyring_get_api_key,
    _keyring_get_fallback_keys,
    _keyring_set_api_key,
    _keyring_set_fallback_keys,
    dpapi_protect_text_windows,
    dpapi_unprotect_text_windows,
    dpapi_unprotect_text_windows_once,
    keyring_delete_api_key,
    keyring_delete_fallback_keys,
    keyring_get_api_key,
    keyring_get_fallback_keys,
    keyring_set_api_key,
    keyring_set_fallback_keys,
)
from jot.core.model_registry import (
    DEFAULT_FALLBACK_MODELS,
    DEFAULT_MODEL,
    sanitize_fallback_models,
    sanitize_model_name,
)
from jot.utils.file_ops import (
    _atomic_write_json as _file_ops_atomic_write_json,
)

_config_lock = threading.Lock()
_write_lock = threading.Lock()
# Independent of the TTL cache: explicit empty values also mask old stored keys.
_credential_overrides: dict[tuple[str, str], object] = {}
_config_cache: dict | None = None
_config_cache_ts: float = 0.0
_config_cache_gen: int = 0
_CONFIG_CACHE_TTL = 30.0


def debug_log(msg: str) -> None:
    # Check if debug mode is active
    try:
        is_debug = str(os.environ.get("JOT_DEBUG", "")).strip() in (
            "1",
            "true",
            "TRUE",
            "yes",
            "YES",
        )
    except Exception:
        is_debug = False

    if not is_debug:
        return

    try:
        from jot.utils.logging_utils import get_logger, initialize_app_logging

        initialize_app_logging()
        get_logger().info("[debug] %s", msg)
    except Exception:
        pass


def _resolve_user_home() -> str:
    """
    Resolve the user's home directory robustly across platforms and packaging contexts.
    On some macOS GUI launches the environment can be sparse; fall back to system account info.
    """
    candidates = []
    try:
        candidates.append(os.path.expanduser("~"))
    except Exception:
        pass
    try:
        candidates.append(os.environ.get("HOME"))
    except Exception:
        pass
    if platform.system() != "Windows":
        try:
            import pwd  # type: ignore

            candidates.append(pwd.getpwuid(os.getuid()).pw_dir)  # type: ignore[attr-defined]
        except Exception:
            pass

    for c in candidates:
        if not c:
            continue
        c = str(c).strip()
        if not c or c == "~":
            continue
        if os.path.isabs(c) and os.path.isdir(c):
            return c

    # Last-resort: use current working directory (may not be writable, but prevents "~" bugs).
    try:
        return os.path.abspath(os.getcwd())
    except Exception:
        return "."


def _get_config_file_path(user_home: str) -> str:
    """
    Pick an OS-appropriate, persistent config path.
    - macOS: ~/Library/Application Support/jot/config.json
    - Windows: %APPDATA%\\jot\\config.json
    - Linux: $XDG_CONFIG_HOME/jot/config.json or ~/.config/jot/config.json
    """
    system = platform.system()
    if system == "Darwin":
        base = os.path.join(user_home, "Library", "Application Support", "jot")
    elif system == "Windows":
        appdata = os.environ.get("APPDATA") or os.path.join(
            user_home, "AppData", "Roaming"
        )
        base = os.path.join(appdata, "jot")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(user_home, ".config")
        base = os.path.join(xdg, "jot")
    return os.path.join(base, "config.json")


USER_HOME = _resolve_user_home()
CONFIG_FILE = _get_config_file_path(USER_HOME)
THEME_PREF_FILE = os.path.join(os.path.dirname(CONFIG_FILE), "theme_pref.txt")
LEGACY_CONFIG_FILE = os.path.join(USER_HOME, ".jot_config.json")


def get_config_dir() -> str:
    """Returns the directory where configuration and usage files are stored."""
    return os.path.dirname(CONFIG_FILE)


# In testing environment, isolate from actual user configuration to prevent data loss or key overwrites.
import sys

if "pytest" in sys.modules or os.environ.get("JOT_TESTING") == "1":
    import getpass
    import tempfile

    # Incorporate username to prevent PermissionError on multi-user systems
    try:
        _username = getpass.getuser()
    except Exception:
        _username = "unknown"
    _test_temp_dir = os.path.join(tempfile.gettempdir(), f"jot_test_{_username}")

    try:
        os.makedirs(_test_temp_dir, exist_ok=True)
    except Exception:
        pass

    CONFIG_FILE = os.path.join(_test_temp_dir, "jot_test_config.json")
    THEME_PREF_FILE = os.path.join(_test_temp_dir, "jot_test_theme_pref.txt")
    LEGACY_CONFIG_FILE = os.path.join(_test_temp_dir, "jot_test_legacy_config.json")


def get_desktop_dir() -> str:
    # Cross-platform Desktop path (Windows/macOS/Linux). Fallback: home directory.
    try:
        if platform.system() == "Windows":
            # Prefer OneDrive Desktop if present (common on Windows 10/11).
            for env_key in ("OneDriveConsumer", "OneDriveCommercial", "OneDrive"):
                od = os.environ.get(env_key)
                if od:
                    p = os.path.join(od, "Desktop")
                    if os.path.isdir(p):
                        return p
            up = os.environ.get("USERPROFILE") or USER_HOME
            p = os.path.join(up, "Desktop")
            if os.path.isdir(p):
                return p
        # macOS/Linux default
        p = os.path.join(USER_HOME, "Desktop")
        if os.path.isdir(p):
            return p
    except Exception:
        pass
    return USER_HOME


def safe_output_basename(name: str) -> str:
    # Safe across Windows/macOS. Keep it readable.
    s = (name or "").strip() or "Sbobina"
    s = re.sub(r"[<>:\"/\\\\|?*]+", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:140] if len(s) > 140 else s


def _scrub_legacy_credentials(path: str) -> None:
    with open(path, encoding="utf-8") as handle:
        legacy = json.load(handle)
    if isinstance(legacy, dict) and (
        legacy.get("api_key") or legacy.get("fallback_keys")
    ):
        legacy["api_key"] = ""
        legacy["fallback_keys"] = []
        _atomic_write_json(path, legacy)


def _remove_legacy_config_after_migration() -> None:
    migrated_path = LEGACY_CONFIG_FILE + ".migrated"
    # Older versions can leave this copy even when the original is already gone.
    try:
        _scrub_legacy_credentials(migrated_path)
        os.remove(migrated_path)
    except FileNotFoundError:
        pass
    except Exception as exc:
        debug_log(f"legacy config migration cleanup: migrated copy failed: {exc}")
    try:
        # Scrub before moving: a failed rename/delete must not leave plaintext behind.
        _scrub_legacy_credentials(LEGACY_CONFIG_FILE)
        os.replace(LEGACY_CONFIG_FILE, migrated_path)
    except FileNotFoundError:
        return
    except Exception as exc:
        debug_log(f"legacy config migration cleanup: replace failed: {exc}")
        return
    try:
        os.remove(migrated_path)
    except FileNotFoundError:
        pass
    except Exception as exc:
        debug_log(f"legacy config migration cleanup: remove failed: {exc}")


def _has_legacy_plaintext_credentials() -> bool:
    for path in (LEGACY_CONFIG_FILE, LEGACY_CONFIG_FILE + ".migrated"):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                legacy = json.load(handle)
            if isinstance(legacy, dict) and (
                legacy.get("api_key") or legacy.get("fallback_keys")
            ):
                return True
        except (OSError, ValueError):
            # An unreadable legacy copy cannot be confirmed free of plaintext.
            return True
    return False


def _clone_config_dict(data: dict) -> dict:
    result = dict(data)
    result["fallback_models"] = list(data.get("fallback_models") or [])
    result["fallback_keys"] = list(data.get("fallback_keys") or [])
    if isinstance(data.get("credential_storage"), dict):
        result["credential_storage"] = dict(data["credential_storage"])
    return result


def _get_cached_config() -> dict | None:
    with _config_lock:
        if (
            _config_cache is not None
            and time.monotonic() - _config_cache_ts < _CONFIG_CACHE_TTL
        ):
            return _clone_config_dict(_config_cache)
    return None


def _update_config_cache(data: dict, gen_at_start: int) -> None:
    global _config_cache, _config_cache_ts
    with _config_lock:
        if _config_cache_gen == gen_at_start:
            _config_cache = _clone_config_dict(data)
            _config_cache_ts = time.monotonic()


def _backup_corrupt_config_file(path: str) -> None:
    try:
        _ts = int(time.time())
        _dest = f"{path}.corrupt-{_ts}"
        try:
            os.close(os.open(_dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            pass  # concurrent caller already backed up the same (identical) file
        else:
            shutil.copy2(path, _dest)
    except Exception as ex:
        debug_log(f"load_config: backup copy failed: {ex}")


def _read_config_from_disk_paths() -> tuple[dict | None, str | None, str | None]:
    _corrupt_path: str | None = None
    for path in (CONFIG_FILE, LEGACY_CONFIG_FILE):
        if not os.path.exists(path):
            continue
        try:
            debug_log(f"load_config: checking file at {path}")
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                debug_log(f"load_config: successfully read json dictionary from {path}")
                return data, None, path
        except json.JSONDecodeError as e:
            debug_log(f"load_config: json decode error for {path}: {e}")
            _backup_corrupt_config_file(path)
            if _corrupt_path is None:
                _corrupt_path = path
        except Exception as exc:
            debug_log(f"load_config: failed to read config from {path}: {exc}")
            if _corrupt_path is None:
                _corrupt_path = path
    return None, _corrupt_path, None


def _credential_fields(group: str) -> tuple[str, ...]:
    return (
        ("api_key", "api_key_protected", "use_keyring")
        if group == "primary"
        else ("fallback_keys", "fallback_keys_protected")
    )


def _persist_credential(group: str, value: object, current: dict, data: dict) -> bool:
    """Replace only after protected-store success; failure preserves the old record."""
    fields = _credential_fields(group)
    windows = platform.system() == "Windows"
    try:
        if windows:
            protected = (
                _dpapi_protect_text_windows(
                    str(value) if group == "primary" else json.dumps(value)
                )
                if value
                else ""
            )
            success = not value or bool(protected)
        else:
            deleter = (
                _keyring_delete_api_key
                if group == "primary"
                else _keyring_delete_fallback_keys
            )
            if value:
                success = (
                    _keyring_set_api_key(str(value))
                    if group == "primary"
                    else _keyring_set_fallback_keys(
                        list(value) if isinstance(value, list) else []
                    )
                ) is True
            else:
                success = deleter() is True
            protected = ""
    except Exception:
        success = False
        protected = ""
    if not success:
        for field in fields:
            if field in current:
                data[field] = current[field]
        return False
    for field in fields:
        data.pop(field, None)
    data[fields[0]] = "" if group == "primary" else []
    if windows and protected:
        data[fields[1]] = protected
    elif not windows and group == "primary":
        data["use_keyring"] = True
    return True


def _resolve_loaded_secrets(data: dict) -> None:
    states = {"primary": "absent", "fallback": "absent"}
    windows = platform.system() == "Windows"
    # Effective keyring values and plaintext still on disk are independent facts.
    data["api_key_insecure"] = bool(data.get("api_key") or data.get("fallback_keys"))
    for group, field in (("primary", "api_key"), ("fallback", "fallback_keys")):
        plain = data.get(field)
        if plain and windows:
            states[group] = "legacy_plaintext"
            continue
        try:
            if windows:
                protected = data.get(field + "_protected")
                value = _dpapi_unprotect_text_windows(protected) if protected else ""
                if group == "fallback":
                    value = json.loads(value) if value else []
                    if not isinstance(value, list):
                        value = []
            else:
                value = (
                    _keyring_get_api_key()
                    if group == "primary"
                    else _keyring_get_fallback_keys()
                )
            if not value and plain:
                data[field] = plain
                states[group] = "legacy_plaintext"
            elif value:
                data[field] = value
                states[group] = "protected"
            else:
                data[field] = "" if group == "primary" else []
        except Exception:
            data[field] = plain or ("" if group == "primary" else [])
            if plain:
                states[group] = "legacy_plaintext"
    data["credential_storage"] = states
    data["has_protected_key"] = states["primary"] == "protected"


def _migrate_plaintext(raw: dict, source_path: str | None) -> dict:
    """Do not copy legacy plaintext to another file, or delete it on store failure."""
    if not source_path or not (raw.get("api_key") or raw.get("fallback_keys")):
        return raw
    with _write_lock:
        try:
            with open(source_path, encoding="utf-8") as handle:
                if json.load(handle) != raw:
                    return raw  # A concurrent save superseded this load.
            migrated = dict(raw)
            changed = False
            for group, field in (("primary", "api_key"), ("fallback", "fallback_keys")):
                if raw.get(field):
                    with _config_lock:
                        overridden = (CONFIG_FILE, group) in _credential_overrides
                    if not overridden:
                        if platform.system() != "Windows":
                            stored = (
                                _keyring_get_api_key()
                                if group == "primary"
                                else _keyring_get_fallback_keys()
                            )
                            if stored:
                                # Automatic migration must not replace newer keys.
                                for credential_field in _credential_fields(group):
                                    migrated.pop(credential_field, None)
                                migrated[field] = "" if group == "primary" else []
                                if group == "primary":
                                    migrated["use_keyring"] = True
                                changed = True
                                continue
                        changed = (
                            _persist_credential(group, raw[field], raw, migrated)
                            or changed
                        )
            if changed:
                destination = (
                    source_path
                    if migrated.get("api_key") or migrated.get("fallback_keys")
                    else CONFIG_FILE
                )
                _atomic_write_json(destination, migrated)
                if destination == CONFIG_FILE and source_path == LEGACY_CONFIG_FILE:
                    _remove_legacy_config_after_migration()
                return migrated
        except Exception:
            pass
    return raw


def _apply_credential_overrides(data: dict) -> dict:
    result = _clone_config_dict(data)
    states = dict(
        result.get("credential_storage") or {"primary": "absent", "fallback": "absent"}
    )
    plaintext_on_disk = (
        bool(result.get("api_key_insecure"))
        or "legacy_plaintext" in states.values()
        or _has_legacy_plaintext_credentials()
    )
    with _config_lock:
        for group, field in (("primary", "api_key"), ("fallback", "fallback_keys")):
            identity = (CONFIG_FILE, group)
            if identity in _credential_overrides:
                value = _credential_overrides[identity]
                result[field] = list(value) if isinstance(value, list) else value
                states[group] = "session_only"
    result["credential_storage"] = states
    result["has_protected_key"] = states["primary"] == "protected"
    result["api_key_insecure"] = plaintext_on_disk
    result["api_key_insecure_reason"] = (
        "Credenziali presenti in chiaro nel file di configurazione. La migrazione protetta non è riuscita."
        if result["api_key_insecure"]
        else ""
    )
    return result


def _sanitize_config_models(data: dict) -> None:
    preferred_model = sanitize_model_name(data.get("preferred_model"), DEFAULT_MODEL)
    fallback_models = sanitize_fallback_models(
        data.get("fallback_models"),
        preferred_model,
        DEFAULT_FALLBACK_MODELS,
    )
    data["preferred_model"] = preferred_model
    data["fallback_models"] = fallback_models


def _build_default_config(corrupt_path: str | None = None) -> dict:
    debug_log("load_config: no config read, returning default values")
    default_cfg: dict = {
        "api_key": "",
        "preferred_model": DEFAULT_MODEL,
        "fallback_models": list(DEFAULT_FALLBACK_MODELS),
    }
    if corrupt_path is not None:
        default_cfg["config_recovered_from"] = corrupt_path
    return default_cfg


def load_config() -> dict:
    cached = _get_cached_config()
    if cached is not None:
        return _apply_credential_overrides(cached)
    gen_at_start = _config_cache_gen
    data, corrupt_path, source_path = _read_config_from_disk_paths()
    if data is not None:
        data = _migrate_plaintext(data, source_path)
        _resolve_loaded_secrets(data)
        _sanitize_config_models(data)
    else:
        data = _build_default_config(corrupt_path)
        _resolve_loaded_secrets(data)
    _update_config_cache(data, gen_at_start)
    return _apply_credential_overrides(data)


def _read_raw_existing_config() -> dict:
    for path in (CONFIG_FILE, LEGACY_CONFIG_FILE):
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                raw_cfg = json.load(fh)
            if isinstance(raw_cfg, dict):
                return raw_cfg
        except Exception:
            pass
    return {}


def _preserve_extra_config_keys(current_cfg: dict, data: dict) -> None:
    for preserve_key in ("session_root",):
        if preserve_key in current_cfg and preserve_key not in data:
            data[preserve_key] = current_cfg[preserve_key]


def _atomic_write_json(file_path: str, data: dict) -> None:
    _file_ops_atomic_write_json(file_path, data, indent=None, mode=0o600)


def _write_legacy_config_if_requested(data: dict) -> None:
    try:
        if str(os.environ.get("JOT_WRITE_LEGACY_CONFIG", "")).strip() in (
            "1",
            "true",
            "TRUE",
            "yes",
            "YES",
        ):
            if not data.get("api_key") and not data.get("fallback_keys"):
                _atomic_write_json(LEGACY_CONFIG_FILE, data)
    except Exception:
        pass


def save_config(
    api_key: str | None,
    fallback_keys: list | None = None,
    preferred_model: str | None = None,
    fallback_models: list | None = None,
) -> dict:
    global _config_cache, _config_cache_gen
    with _write_lock:
        with _config_lock:
            _config_cache = None

        current_cfg = _read_raw_existing_config()
        data: dict = {
            field: current_cfg[field]
            for group in ("primary", "fallback")
            for field in _credential_fields(group)
            if field in current_cfg
        }
        data.setdefault("api_key", "")
        data.setdefault("fallback_keys", [])

        preferred_model_norm = sanitize_model_name(
            preferred_model
            if preferred_model is not None
            else current_cfg.get("preferred_model"),
            DEFAULT_MODEL,
        )
        fallback_models_norm = sanitize_fallback_models(
            fallback_models
            if fallback_models is not None
            else current_cfg.get("fallback_models"),
            preferred_model_norm,
            DEFAULT_FALLBACK_MODELS,
        )
        data["preferred_model"] = preferred_model_norm
        data["fallback_models"] = fallback_models_norm

        updates: dict[str, object] = {}
        outcomes: dict[str, bool] = {}
        if api_key is not None:
            updates["primary"] = str(api_key).strip()
        if fallback_keys is not None:
            updates["fallback"] = [
                str(k).strip() for k in fallback_keys if str(k or "").strip()
            ]
        for group, value in updates.items():
            outcomes[group] = _persist_credential(group, value, current_cfg, data)
        _preserve_extra_config_keys(current_cfg, data)
        # If protection failed for a legacy credential, update its original file only.
        destination = (
            LEGACY_CONFIG_FILE
            if not os.path.exists(CONFIG_FILE)
            and os.path.exists(LEGACY_CONFIG_FILE)
            and (data.get("api_key") or data.get("fallback_keys"))
            else CONFIG_FILE
        )
        _atomic_write_json(destination, data)
        if destination == CONFIG_FILE and not (
            data.get("api_key") or data.get("fallback_keys")
        ):
            _remove_legacy_config_after_migration()
        _write_legacy_config_if_requested(data)
        with _config_lock:
            for group, value in updates.items():
                identity = (CONFIG_FILE, group)
                if outcomes[group]:
                    _credential_overrides.pop(identity, None)
                else:
                    _credential_overrides[identity] = value
            _config_cache = None
            _config_cache_gen += 1
        # Report effective state without running migration/store attempts a second time.
        effective = dict(data)
        _resolve_loaded_secrets(effective)
        for group, value in updates.items():
            if outcomes[group]:
                effective["api_key" if group == "primary" else "fallback_keys"] = value
                effective["credential_storage"][group] = (
                    "protected" if value else "absent"
                )
        return _apply_credential_overrides(effective)["credential_storage"]


def save_session_root_to_config(path: str) -> None:
    """Persist a custom session_root to config.json without touching credentials."""
    global _config_cache, _config_cache_gen
    p_str = str(path).strip()
    if os.path.exists(p_str):
        try:
            p_str = os.path.realpath(p_str)
        except Exception:
            pass
    with _write_lock:
        with _config_lock:
            _config_cache = None
            _config_cache_gen += 1
        current_cfg = _read_raw_existing_config()
        current_cfg["session_root"] = p_str
        destination = (
            LEGACY_CONFIG_FILE
            if not os.path.exists(CONFIG_FILE)
            and os.path.exists(LEGACY_CONFIG_FILE)
            and (current_cfg.get("api_key") or current_cfg.get("fallback_keys"))
            else CONFIG_FILE
        )
        _atomic_write_json(destination, current_cfg)

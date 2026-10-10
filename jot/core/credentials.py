"""
Platform credential management and cryptography for jot.

Encapsulates:
- Windows DPAPI encryption/decryption using ctypes and Windows CryptoAPI.
- macOS/Linux OS Keyring storage via the keyring package.
"""

from __future__ import annotations

import functools
import json
import os
import platform
import time

KEYRING_SERVICE = "jot"
KEYRING_USER_API = "gemini_api_key"
KEYRING_USER_FALLBACK_KEYS = "gemini_fallback_keys"

# Backwards compatibility aliases
_KEYRING_SERVICE = KEYRING_SERVICE
_KEYRING_USER_API = KEYRING_USER_API
_KEYRING_USER_FALLBACK_KEYS = KEYRING_USER_FALLBACK_KEYS


def _debug_log(msg: str) -> None:
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
        from jot.utils.logging_utils import redact_secrets

        msg = redact_secrets(msg)
    except Exception:
        pass

    try:
        print(f"[debug] {msg}", flush=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Keyring Helpers (macOS / Linux)
# ---------------------------------------------------------------------------


def keyring_get_api_key() -> str:
    """
    Retrieve the Gemini API key from the OS keyring on macOS/Linux.
    Returns an empty string on Windows or if no key is stored / keyring fails.
    """
    for attempt in range(2):
        try:
            if platform.system() == "Windows":
                return ""
            import keyring  # type: ignore

            v = keyring.get_password(KEYRING_SERVICE, KEYRING_USER_API)
            result = str(v or "").strip()
            if result:
                return result
            break  # keyring reachable but no key stored — no point retrying
        except Exception:
            pass
        if attempt == 0:
            time.sleep(0.5)
    return ""


def keyring_set_api_key(api_key: str) -> bool:
    """
    Save the Gemini API key into the OS keyring on macOS/Linux.
    Returns True on success, False on Windows or failure.
    """
    try:
        if platform.system() == "Windows":
            return False
        import keyring  # type: ignore

        keyring.set_password(KEYRING_SERVICE, KEYRING_USER_API, str(api_key or ""))
        return True
    except Exception:
        return False


def keyring_delete_api_key() -> bool:
    """
    Delete the Gemini API key from the OS keyring on macOS/Linux.
    Returns True on success, False on Windows or failure.
    """
    try:
        if platform.system() == "Windows":
            return False
        import keyring  # type: ignore

        if keyring.get_password(KEYRING_SERVICE, KEYRING_USER_API) is None:
            return True
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER_API)
        return True
    except Exception:
        return False


def keyring_get_fallback_keys() -> list[str]:
    """
    Retrieve fallback keys list from the OS keyring on macOS/Linux.
    Returns an empty list on Windows or if not found / error.
    """
    try:
        if platform.system() == "Windows":
            return []
        import keyring  # type: ignore

        fk_json = keyring.get_password(KEYRING_SERVICE, KEYRING_USER_FALLBACK_KEYS)
        if fk_json:
            parsed = json.loads(fk_json)
            if isinstance(parsed, list):
                return [str(k).strip() for k in parsed if str(k).strip()]
    except Exception as e:
        _debug_log(f"keyring: failed to load fallback keys: {e}")
    return []


def keyring_set_fallback_keys(fallback_keys: list[str]) -> bool:
    """
    Save fallback keys list into the OS keyring on macOS/Linux.
    Returns True on success, False on Windows or failure.
    """
    try:
        if platform.system() == "Windows":
            return False
        import keyring  # type: ignore

        cleaned = [str(k).strip() for k in fallback_keys if str(k).strip()]
        keyring.set_password(
            KEYRING_SERVICE, KEYRING_USER_FALLBACK_KEYS, json.dumps(cleaned)
        )
        return True
    except Exception as e:
        _debug_log(f"keyring: failed to save fallback keys: {e}")
        return False


def keyring_delete_fallback_keys() -> bool:
    """
    Delete fallback keys from the OS keyring on macOS/Linux.
    Returns True on success, False on Windows or failure.
    """
    try:
        if platform.system() == "Windows":
            return False
        import keyring  # type: ignore

        if keyring.get_password(KEYRING_SERVICE, KEYRING_USER_FALLBACK_KEYS) is None:
            return True
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER_FALLBACK_KEYS)
        return True
    except Exception as e:
        _debug_log(f"keyring: failed to delete fallback keys: {e}")
        return False


# Aliases for backwards compatibility
_keyring_get_api_key = keyring_get_api_key
_keyring_set_api_key = keyring_set_api_key
_keyring_delete_api_key = keyring_delete_api_key
_keyring_get_fallback_keys = keyring_get_fallback_keys
_keyring_set_fallback_keys = keyring_set_fallback_keys
_keyring_delete_fallback_keys = keyring_delete_fallback_keys


# ---------------------------------------------------------------------------
# DPAPI Cryptography Helpers (Windows)
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _dpapi_make_blob_class(ctypes_mod, wintypes_mod):
    class DATA_BLOB(ctypes_mod.Structure):
        _fields_ = [  # noqa: RUF012
            ("cbData", wintypes_mod.DWORD),
            ("pbData", ctypes_mod.POINTER(ctypes_mod.c_byte)),
        ]

    return DATA_BLOB


def dpapi_protect_text_windows(text: str) -> str:
    """
    Best-effort encryption for secrets on Windows using DPAPI (CryptProtectData).
    Returns base64 string on success, "" on failure or on non-Windows platforms.
    """
    if platform.system() != "Windows":
        return ""
    try:
        import base64
        import ctypes
        from ctypes import wintypes

        DATA_BLOB = _dpapi_make_blob_class(ctypes, wintypes)  # type: ignore[arg-type]

        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)  # pyright: ignore[reportAttributeAccessIssue]
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # pyright: ignore[reportAttributeAccessIssue]

        crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(DATA_BLOB),
            wintypes.LPCWSTR,
            ctypes.POINTER(DATA_BLOB),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(DATA_BLOB),
        ]
        crypt32.CryptProtectData.restype = wintypes.BOOL

        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p

        plain = (text or "").encode("utf-8", errors="strict")
        if not plain:
            return ""
        buf = ctypes.create_string_buffer(plain)
        in_blob = DATA_BLOB(len(plain), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
        out_blob = DATA_BLOB()
        CRYPTPROTECT_UI_FORBIDDEN = 0x1
        ok = crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        # Reference buf to keep it alive
        _ = buf
        if not ok:
            err_code = ctypes.get_last_error()  # pyright: ignore[reportAttributeAccessIssue]
            err_msg = str(ctypes.WinError(err_code))  # pyright: ignore[reportAttributeAccessIssue]
            _debug_log(f"dpapi: CryptProtectData failed: {err_msg} (code {err_code})")
            return ""
        try:
            out_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            try:
                kernel32.LocalFree(out_blob.pbData)
            except Exception as e:
                _debug_log(f"dpapi: LocalFree in protect raised: {e}")
        return base64.b64encode(out_bytes).decode("ascii")
    except Exception as exc:
        _debug_log(f"dpapi: protect exception: {exc}")
        return ""


def dpapi_unprotect_text_windows_once(b64: str) -> str:
    """
    Single-attempt decryption of a base64 DPAPI blob on Windows.
    Returns decrypted plaintext on success, "" on failure.
    """
    if platform.system() != "Windows":
        return ""
    try:
        import base64
        import ctypes
        from ctypes import wintypes

        DATA_BLOB = _dpapi_make_blob_class(ctypes, wintypes)  # type: ignore[arg-type]

        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)  # pyright: ignore[reportAttributeAccessIssue]
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # pyright: ignore[reportAttributeAccessIssue]

        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(DATA_BLOB),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(DATA_BLOB),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(DATA_BLOB),
        ]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL

        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p

        raw = base64.b64decode(
            (b64 or "").encode("ascii", errors="ignore"), validate=False
        )
        if not raw:
            return ""
        buf = ctypes.create_string_buffer(raw)
        in_blob = DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
        out_blob = DATA_BLOB()
        desc = wintypes.LPWSTR()
        CRYPTPROTECT_UI_FORBIDDEN = 0x1
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            ctypes.byref(desc),
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        # Reference buf to keep it alive
        _ = buf
        if not ok:
            err_code = ctypes.get_last_error()  # pyright: ignore[reportAttributeAccessIssue]
            err_msg = str(ctypes.WinError(err_code))  # pyright: ignore[reportAttributeAccessIssue]
            _debug_log(f"dpapi: CryptUnprotectData failed: {err_msg} (code {err_code})")
            return ""
        try:
            out_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            try:
                kernel32.LocalFree(out_blob.pbData)
            except Exception as e:
                _debug_log(f"dpapi: LocalFree pbData raised: {e}")
            try:
                if desc:
                    kernel32.LocalFree(desc)
            except Exception as e:
                _debug_log(f"dpapi: LocalFree desc raised: {e}")
        return out_bytes.decode("utf-8", errors="replace").strip()
    except Exception as exc:
        _debug_log(f"dpapi: unprotect exception: {exc}")
        return ""


def dpapi_unprotect_text_windows(b64: str) -> str:
    """
    Best-effort decryption for secrets on Windows using DPAPI (CryptUnprotectData).
    Returns plaintext string on success, "" on failure.
    Retries once after 500 ms to tolerate transient service unavailability.
    """
    if platform.system() != "Windows" or not (b64 or "").strip():
        return ""
    for attempt in range(2):
        result = dpapi_unprotect_text_windows_once(b64)
        if result:
            return result
        if attempt == 0:
            time.sleep(0.5)
    return ""


# Aliases for backwards compatibility
_dpapi_protect_text_windows = dpapi_protect_text_windows
_dpapi_unprotect_text_windows_once = dpapi_unprotect_text_windows_once
_dpapi_unprotect_text_windows = dpapi_unprotect_text_windows

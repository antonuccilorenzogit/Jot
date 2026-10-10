"""
Auto-update logic for jot.

Downloads the platform-appropriate release asset from GitHub, launches the
installer (Windows) or mounts + copies the DMG (macOS), then schedules
a short-delay quit so the webview window closes cleanly.
"""

from __future__ import annotations

import atexit
import hashlib
import os
import plistlib
import re
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

import certifi

_CREATE_NEW_PROCESS_GROUP = 0x00000200
_DETACHED_PROCESS = 0x00000008
_Thread = threading.Thread


def _verify_sha256(
    tmp_path: str, checksum_url: str, ssl_ctx: ssl.SSLContext
) -> str | None:
    """Download checksum file and verify tmp_path hash. Returns error string or None on success."""
    try:
        with urllib.request.urlopen(checksum_url, timeout=30, context=ssl_ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "File checksum SHA-256 assente per questa release — aggiornamento annullato per sicurezza."
        return f"Download checksum fallito: {e}"
    except Exception as e:
        return f"Download checksum fallito: {e}"

    parts = raw.split()
    if not parts:
        return "File checksum vuoto o malformato."
    expected = parts[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        return "Checksum SHA-256 non valido nel file di verifica."

    sha256 = hashlib.sha256()
    try:
        with open(tmp_path, "rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                sha256.update(chunk)
    except OSError as e:
        return f"Lettura file temporaneo fallita: {e}"
    actual = sha256.hexdigest()

    if actual != expected:
        return "Verifica integrit\u00e0 fallita: il file scaricato non corrisponde al checksum atteso."
    return None


def _try_unlink(path: str) -> None:
    """Best-effort unlink; silently ignores all OS errors."""
    try:
        os.unlink(path)
    except OSError:
        pass


def _launch_windows_installer(tmp_path: str) -> subprocess.Popen[bytes]:
    """Launch the Windows installer EXE and schedule temp-file cleanup."""
    proc = subprocess.Popen(
        [tmp_path, "/CURRENTUSER"],
        creationflags=_CREATE_NEW_PROCESS_GROUP | _DETACHED_PROCESS,
    )
    # atexit fires during normal interpreter shutdown (after webview.start() returns),
    # by which time Inno Setup has already copied itself — a single attempt suffices.
    # A daemon thread cannot be used here because the process exits (~1.5 s after
    # _poll_then_destroy calls destroy()) before the thread's first sleep completes.
    atexit.register(_try_unlink, tmp_path)
    return proc


def _poll_then_destroy(
    proc: subprocess.Popen[bytes], emit_fn=None, tmp_path: str = ""
) -> None:
    """Poll the installer process; destroy the app window only once it is confirmed alive.

    Prevents the window from closing when the user denies UAC (installer exits immediately).
    Emits 'done' via emit_fn when the installer is confirmed alive, or 'error' with
    error='uac_denied' if it exits before the liveness window elapses.
    """
    _POLL_INTERVAL = 0.3
    _ALIVE_CONFIRM_POLLS = 5  # 5 x 0.3 s ~ 1.5 s
    for _ in range(_ALIVE_CONFIRM_POLLS):
        time.sleep(_POLL_INTERVAL)
        if proc.poll() is not None:
            if emit_fn is not None:
                try:
                    emit_fn("error", error="uac_denied")
                except Exception:
                    pass
            if tmp_path:
                _try_unlink(tmp_path)
            return  # installer exited quickly — UAC denied or launch failure; leave app open
    if emit_fn is not None:
        try:
            emit_fn("done")
        except Exception:
            pass
    try:
        import webview  # type: ignore

        if webview.windows:
            webview.windows[0].destroy()
    except Exception:
        pass


def _install_macos_dmg(tmp_path: str) -> dict | None:
    """Mount DMG, spawn a detached script to copy app to /Applications, then return.

    Verifies the DMG and permissions, then spawns an independent background script
    that waits for the parent Python process to exit before replacing the app package,
    removing quarantine flags, detaching the DMG, and opening the new version.
    """
    import shlex

    mount_point = None
    detached_script_spawned = False
    try:
        result = subprocess.run(
            ["hdiutil", "attach", "-nobrowse", "-plist", tmp_path],
            capture_output=True,
            check=True,
            timeout=30,
        )
        plist = plistlib.loads(result.stdout)
        for entity in plist.get("system-entities", []):
            mp = entity.get("mount-point")
            if mp:
                mount_point = mp
                break
        if not mount_point:
            return {"ok": False, "error": "Impossibile montare il DMG."}

        app_src = os.path.join(mount_point, "jot.app")
        app_dst = "/Applications/jot.app"

        if not os.path.exists(app_src):
            return {"ok": False, "error": "Applicazione non trovata nel DMG."}

        # Preemptive permission check
        if not os.access(os.path.dirname(app_dst), os.W_OK):
            raise PermissionError("Permesso di scrittura negato per /Applications.")
        if os.path.exists(app_dst) and not os.access(app_dst, os.W_OK):
            raise PermissionError(
                "Permesso di scrittura negato per l'applicazione esistente."
            )

        # Preemptive cleanup of stale tmp directory from prior failed updates
        app_dst_tmp = app_dst + ".tmp"
        if os.path.exists(app_dst_tmp):
            try:
                import shutil

                if os.path.isdir(app_dst_tmp) and not os.path.islink(app_dst_tmp):
                    shutil.rmtree(app_dst_tmp)
                else:
                    os.unlink(app_dst_tmp)
            except Exception:
                pass

        # Secure and robust shell escaping
        quoted_app_dst = shlex.quote(app_dst)
        quoted_app_dst_tmp = shlex.quote(app_dst + ".tmp")
        quoted_app_src = shlex.quote(app_src)
        quoted_mount_point = shlex.quote(mount_point)
        quoted_tmp_path = shlex.quote(tmp_path)

        # Detached background script that waits for this parent process to terminate,
        # performs a safe transactional-like copy, and cleans up DMG mounts.
        script = (
            f"(\n"
            f"  while kill -0 {os.getpid()} 2>/dev/null; do\n"
            f"    sleep 0.2\n"
            f"  done\n"
            f"  rm -rf {quoted_app_dst_tmp}\n"
            f"  if cp -a {quoted_app_src} {quoted_app_dst_tmp}; then\n"
            f"    rm -rf {quoted_app_dst}\n"
            f"    mv {quoted_app_dst_tmp} {quoted_app_dst}\n"
            f"    xattr -dr com.apple.quarantine {quoted_app_dst} 2>/dev/null\n"
            f"    open {quoted_app_dst}\n"
            f"  else\n"
            f"    rm -rf {quoted_app_dst_tmp}\n"
            f"  fi\n"
            f"  hdiutil detach {quoted_mount_point} -force\n"
            f"  rm -f {quoted_tmp_path}\n"
            f") &"
        )

        subprocess.Popen(["/bin/bash", "-c", script], start_new_session=True)
        detached_script_spawned = True

    except subprocess.CalledProcessError as cp_err:
        stderr = (
            cp_err.stderr.decode("utf-8", errors="replace") if cp_err.stderr else ""
        )
        if "Permission denied" in stderr or "Operation not permitted" in stderr:
            raise PermissionError(stderr) from cp_err
        raise

    finally:
        # Only clean up locally if we didn't successfully hand off to the detached script
        if not detached_script_spawned:
            if mount_point:
                subprocess.run(
                    ["hdiutil", "detach", mount_point], check=False, timeout=30
                )
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return None


def _download_and_install_background(
    url: str,
    tmp_path: str,
    ssl_ctx: ssl.SSLContext,
    emit_fn,
) -> None:
    """Background worker: download, verify checksum, and install the update asset."""

    def _emit(
        status: str, *, bytes_done: int = 0, bytes_total: int = 0, error: str = ""
    ) -> None:
        if emit_fn is None:
            return
        payload: dict = {
            "status": status,
            "bytes_done": bytes_done,
            "bytes_total": bytes_total,
        }
        if error:
            payload["error"] = error
        try:
            emit_fn("updateDownloadProgress", payload)
        except Exception:
            pass

    # --- Download ---
    try:
        last_emit = 0.0
        with urllib.request.urlopen(url, timeout=120, context=ssl_ctx) as resp:
            try:
                total = int(resp.headers.get("Content-Length") or 0)
            except (AttributeError, TypeError):
                total = 0
            done = 0
            with open(tmp_path, "wb") as fh:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last_emit >= 0.25:
                        last_emit = now
                        _emit("downloading", bytes_done=done, bytes_total=total)
    except Exception as e:
        _try_unlink(tmp_path)
        _emit("error", error=f"Download fallito: {e}")
        return

    # --- Checksum ---
    _emit("verifying")
    integrity_error = _verify_sha256(tmp_path, url + ".sha256", ssl_ctx)
    if integrity_error:
        _try_unlink(tmp_path)
        _emit("error", error=integrity_error)
        return

    # --- Install ---
    _emit("installing")
    try:
        if sys.platform == "win32":
            proc = _launch_windows_installer(tmp_path)
            _Thread(
                target=_poll_then_destroy,
                args=(proc, _emit, tmp_path),
                daemon=True,
            ).start()
            return  # done/error emitted by _poll_then_destroy once UAC outcome is known
        else:
            err = _install_macos_dmg(tmp_path)
            if err is not None:
                _emit("error", error=err.get("error", "Installazione fallita."))
                return

            def _delayed_destroy() -> None:
                time.sleep(0.8)
                try:
                    import webview  # type: ignore

                    if webview.windows:
                        webview.windows[0].destroy()
                except Exception:
                    pass

            _Thread(target=_delayed_destroy, daemon=True).start()
    except PermissionError:
        _try_unlink(tmp_path)
        _emit("error", error="permission_denied")
        return
    except Exception as e:
        _try_unlink(tmp_path)
        _emit("error", error=f"Installazione fallita: {e}")
        return

    _emit("done")


def download_and_install_update(version: str, emit_fn=None) -> dict:
    """Start the installer download in a background thread; return immediately.

    Synchronous errors (invalid version, unsupported platform, SSL/tempfile failure)
    are returned as ``{"ok": False, "error": "..."}``.  All other outcomes —
    download progress, checksum failures, install errors, and completion — are
    reported asynchronously via *emit_fn* (``"updateDownloadProgress"`` bridge event).

    Returns ``{"ok": True, "status": "downloading"}`` when the background thread
    has been successfully started.
    """
    if not isinstance(version, str) or not re.fullmatch(r"v?\d+\.\d+\.\d+", version):
        return {"ok": False, "error": "Versione non valida."}

    version_clean = version.lstrip("v")

    if sys.platform == "win32":
        filename = f"jot-Setup-v{version_clean}.exe"
        suffix = ".exe"
    elif sys.platform == "darwin":
        filename = f"jot-v{version_clean}.dmg"
        suffix = ".dmg"
    else:
        return {"ok": False, "error": f"Piattaforma non supportata: {sys.platform}"}

    url = f"https://github.com/antonuccilorenzogit/Jot/releases/download/v{version_clean}/{filename}"

    try:
        _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception as e:
        return {"ok": False, "error": f"Configurazione SSL fallita: {e}"}

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
    except Exception as e:
        return {"ok": False, "error": f"Creazione file temporaneo fallita: {e}"}

    _Thread(
        target=_download_and_install_background,
        args=(url, tmp_path, _ssl_ctx, emit_fn),
        daemon=True,
    ).start()
    return {"ok": True, "status": "downloading"}

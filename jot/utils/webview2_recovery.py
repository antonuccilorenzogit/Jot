"""
WebView2 runtime detection, fallback recovery page, and lifecycle monitor.
"""

from __future__ import annotations

import os
import sys
import threading
from html import escape
from typing import Any

from jot.utils.logging_utils import get_logger, record_startup_diagnostic


def _check_webview2_native(*, activate_renderer: bool = True) -> bool:
    """Probe the same loader used by pywebview, optionally selecting its renderer.

    Registry entries and leftover binaries are not evidence that the loader can
    use a runtime. Even winforms.is_chromium is only a cached registry probe.
    Polling a live recovery window must not change its backend before restart.
    """
    version = None
    native_error = None

    def finish(
        available: bool, renderer: str, renderer_error: str | None = None
    ) -> bool:
        if activate_renderer:
            record_startup_diagnostic(
                status="detected" if available else "recovery",
                runtime_available=available,
                runtime_version=str(version) if version else None,
                renderer=renderer,
                native_error=native_error,
                renderer_error=renderer_error,
            )
        return available

    try:
        import webview.platforms.winforms as wf
    except Exception as exc:
        native_error = f"{type(exc).__name__}: {exc}"
        return finish(False, "unavailable")

    available = False
    try:
        from webview.platforms import edgechromium as Chromium

        environment = getattr(Chromium, "CoreWebView2Environment", None)
        if environment is not None:
            version = environment.GetAvailableBrowserVersionString(None)
            available = bool(version and str(version).strip())
            if not available:
                native_error = "Native loader returned no browser version"
        else:
            native_error = "CoreWebView2Environment is unavailable"
    except Exception as exc:
        native_error = f"{type(exc).__name__}: {exc}"

    if not activate_renderer:
        return available

    try:
        if available:
            wf.Chromium = Chromium
            wf.is_cef = False
            wf.is_chromium = True
            wf.renderer = "edgechromium"
        else:
            # The registry probe may have selected Chromium despite stale entries.
            # Explicitly select MSHTML so the recovery HTML can still be displayed.
            from webview.platforms import mshtml as IE

            IE._set_ie_mode()
            wf.IE = IE
            wf.is_cef = False
            wf.is_chromium = False
            wf.renderer = "mshtml"
    except Exception as exc:
        return finish(
            False,
            getattr(wf, "renderer", "unavailable"),
            f"{type(exc).__name__}: {exc}",
        )
    return finish(available, wf.renderer)


def has_webview2_runtime(*, activate_renderer: bool = True) -> bool:
    """Require native loader detection on Windows; other platforms use WebKit.

    Set activate_renderer=False when polling a recovery window that already uses
    MSHTML. The new process will select Chromium after the installation succeeds.
    """
    if sys.platform != "win32":
        if activate_renderer:
            record_startup_diagnostic(
                status="not_required",
                renderer="platform-default",
                runtime_available=None,
            )
        return True

    return _check_webview2_native(activate_renderer=activate_renderer)


def build_missing_webview2_html() -> str:
    """Generate HTML fallback error page shown when WebView2 is missing on Windows."""
    download_url = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
    repo_url = "https://developer.microsoft.com/en-us/microsoft-edge/webview2/"
    from jot.services.config_service import get_config_dir

    log_path = os.path.join(get_config_dir(), "jot.log")
    return f"""<!doctype html>
<html lang="it">
  <head>
    <meta charset="utf-8" />
    <meta http-equiv="X-UA-Compatible" content="IE=11" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>jot</title>
    <style>
      body {{
        margin: 0;
        padding: 40px 20px;
        background: #f0f2f5;
        font-family: "Segoe UI", Arial, sans-serif;
        color: #222;
      }}
      .card {{
        max-width: 560px;
        margin: 20px auto;
        background: #ffffff;
        border: 1px solid #dde1e7;
        border-radius: 10px;
        padding: 36px 40px;
        box-shadow: 0 2px 12px rgba(0,0,0,0.08);
      }}
      h1 {{
        margin: 0 0 14px;
        font-size: 20px;
        font-weight: 700;
        color: #111;
        line-height: 1.3;
      }}
      p {{
        margin: 0 0 10px;
        font-size: 14px;
        line-height: 1.65;
        color: #555;
      }}
      code {{
        background: #eef0f3;
        padding: 2px 7px;
        border-radius: 5px;
        font-family: Consolas, monospace;
        font-size: 12.5px;
        color: #333;
      }}
      strong {{ color: #222; }}
      .actions {{
        margin: 22px 0 18px;
      }}
      a.btn {{
        display: inline-block;
        padding: 9px 18px;
        border-radius: 6px;
        font-size: 13.5px;
        font-weight: 600;
        text-decoration: none;
        margin-right: 8px;
      }}
      a.btn-primary {{
        background: #0f62fe;
        color: #ffffff;
        border: 1px solid #0f62fe;
      }}
      a.btn-secondary {{
        background: #ffffff;
        color: #0f62fe;
        border: 1px solid #c6d0e3;
      }}
      hr {{
        border: none;
        border-top: 1px solid #eef0f3;
        margin: 20px 0;
      }}
      ol {{
        margin: 0;
        padding-left: 22px;
        color: #666;
      }}
      li {{
        font-size: 13.5px;
        line-height: 1.75;
        margin: 4px 0;
      }}
      .status-box {{
        margin-top: 20px;
        padding: 10px 15px;
        background: #fffbe6;
        border: 1px solid #ffe58f;
        border-radius: 6px;
        font-size: 13.0px;
        color: #d46b08;
      }}
      @keyframes status-pulse {{
        0% {{
          opacity: 0.4;
          transform: scale(0.9);
        }}
        50% {{
          opacity: 1;
          transform: scale(1.1);
        }}
        100% {{
          opacity: 0.4;
          transform: scale(0.9);
        }}
      }}
      .status-dot {{
        display: inline-block;
        width: 8px;
        height: 8px;
        background-color: #faad14;
        border-radius: 50%;
        margin-right: 8px;
        vertical-align: middle;
        animation: status-pulse 1.8s infinite ease-in-out;
      }}
      .status-msg {{
        vertical-align: middle;
        font-weight: 600;
      }}
    </style>
  </head>
  <body>
    <div class="card">
      <h1>Serve WebView2 per avviare l&apos;interfaccia</h1>
      <p>
        jot sta usando il renderer Windows legacy <code>MSHTML</code>,
        che non supporta la WebUI moderna. Senza WebView2 l&apos;applicazione non pu&ograve; caricare l&apos;interfaccia.
      </p>
      <p>
        Installa <strong>Microsoft Edge WebView2 Runtime</strong>
        per avviare l&apos;app normalmente.
      </p>
      <div class="actions">
        <a class="btn btn-primary" target="_blank" rel="noopener noreferrer" href="{escape(download_url)}">Scarica WebView2 Runtime</a>
        <a class="btn btn-secondary" target="_blank" rel="noopener noreferrer" href="{escape(repo_url)}">Dettagli tecnici</a>
      </div>
      <hr />
      <ol>
        <li>Clicca su <strong>Scarica WebView2 Runtime</strong> per scaricare l&apos;installer.</li>
        <li>Avvia il file scaricato e completa l&apos;installazione.</li>
        <li>jot rileverà il completamento e si riavvierà automaticamente!</li>
      </ol>
      <p>Se il problema persiste, il log per l&apos;assistenza si trova qui:</p>
      <p><code style="word-break: break-all;">{escape(log_path)}</code></p>
      <div id="status-box" class="status-box">
        <span id="status-dot" class="status-dot"></span>
        <span id="status-msg" class="status-msg">Verifica dello stato di WebView2 in corso...</span>
      </div>
    </div>
    <script>
      setTimeout(function() {{
        var box = document.getElementById('status-box');
        var dot = document.getElementById('status-dot');
        var msg = document.getElementById('status-msg');
        if (box && dot && msg) {{
          box.style.background = '#fffbe6';
          box.style.borderColor = '#ffe58f';
          box.style.color = '#d46b08';
          dot.style.backgroundColor = '#faad14';
          msg.innerHTML = 'In attesa dell&apos;installazione di WebView2...';
        }}
      }}, 500);
    </script>
  </body>
</html>
"""


def get_boot_bg_color() -> str:
    """Native background matching the HTML boot skeleton and CSS base (no flash)."""
    # Priority 1: explicit in-app preference (mirrors localStorage)
    try:
        from jot.services.config_service import THEME_PREF_FILE

        with open(THEME_PREF_FILE, encoding="utf-8") as fh:
            pref = fh.read().strip()
        if pref == "dark":
            return "#161618"
        if pref == "light":
            return "#eceae5"
    except Exception:
        pass
    # Priority 2: OS-level signal
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            if value == 0:
                return "#161618"  # dark  → matches --boot-bg dark & --bg-base dark
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            import subprocess

            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=0.5,
            )
            if result.stdout.strip().lower() == "dark":
                return "#161618"
        except Exception:
            pass
    return "#eceae5"  # light (default)


def clear_webview2_cache(storage_dir: str, dist_path: str) -> None:
    """Auto cache-bust: clear WebView2 HTTP caches when a new build/version is detected."""
    try:
        import shutil

        mtime_file = os.path.join(storage_dir, ".build_mtime")
        if getattr(sys, "frozen", False):
            current_mtime = str(os.path.getmtime(sys.executable))
        else:
            current_mtime = str(os.path.getmtime(dist_path))
        stored_mtime = ""
        if os.path.exists(mtime_file):
            with open(mtime_file, encoding="utf-8") as _f:
                stored_mtime = _f.read().strip()
        if stored_mtime != current_mtime:
            default_profile = os.path.join(storage_dir, "EBWebView", "Default")
            _cleared = False
            _failed = False
            for cache_name in ("Cache", "Code Cache"):
                cache_dir = os.path.join(default_profile, cache_name)
                if os.path.exists(cache_dir):
                    try:
                        shutil.rmtree(cache_dir)
                        _cleared = True
                    except Exception as _e:
                        _failed = True
                        print(
                            f"[!] Impossibile svuotare cache WebView2 ({cache_name}): {_e}"
                        )
            if _cleared:
                print("[*] Cache WebView2 svuotata (nuova build rilevata).")
            if not _failed:
                with open(mtime_file, "w", encoding="utf-8") as _f:
                    _f.write(current_mtime)
    except Exception:
        pass


def start_webview2_monitor(window: Any, stop_event: threading.Event) -> None:
    """Start a background thread to poll for WebView2 installation when missing."""

    def _check_webview2_installation():
        import subprocess

        while not stop_event.is_set():
            if stop_event.wait(1.5):
                break

            if has_webview2_runtime(activate_renderer=False):
                get_logger().info("WebView2 rilevato dal monitor; riavvio richiesto.")
                js_code = """
                var box = document.getElementById('status-box');
                var dot = document.getElementById('status-dot');
                var msg = document.getElementById('status-msg');
                if (box && dot && msg) {
                    box.style.background = '#f6ffed';
                    box.style.borderColor = '#b7eb8f';
                    box.style.color = '#389e0d';
                    dot.style.backgroundColor = '#52c41a';
                    msg.innerHTML = 'Rilevato! Riavvio dell\\'app in corso...';
                }
                """
                try:
                    window.evaluate_js(js_code)
                except Exception:
                    pass

                stop_event.wait(2.0)
                if stop_event.is_set():
                    return

                if getattr(sys, "frozen", False):
                    args = [sys.executable, *sys.argv[1:]]
                else:
                    args = [sys.executable, *sys.argv] if sys.argv else [sys.executable]

                try:
                    subprocess.Popen(args)
                except Exception as e:
                    print(f"[!] Errore nel riavvio automatico: {e}")

                try:
                    window.destroy()
                except Exception:
                    pass
                os._exit(0)

    t = threading.Thread(target=_check_webview2_installation, daemon=True)
    t.start()

"""
Browser development and agentic debugging runner for jot.

Starts the local FastAPI backend on 127.0.0.1 and optionally launches the
Vite development server. It is always isolated and uses deterministic scenarios.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEBUI_DIR = ROOT / "webui"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run jot in browser mode for development, agentic inspection, and E2E testing."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for the FastAPI backend (default: 8000)",
    )
    parser.add_argument(
        "--vite-port",
        type=int,
        default=3000,
        help="Port for the Vite dev server (default: 3000)",
    )
    parser.add_argument(
        "--scenario",
        choices=["success", "failure", "quota", "paused", "regenerate"],
        default="success",
        help="Run a deterministic offline scenario without external Gemini API calls",
    )
    parser.add_argument(
        "--session-root",
        type=str,
        default=None,
        help="Custom directory for sessions (default: isolated temporary directory)",
    )
    parser.add_argument(
        "--no-vite",
        action="store_true",
        help="Run only the FastAPI backend server (without starting Vite)",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Automatically open the browser once started",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Session isolation
    temp_dir_to_clean: str | None = None
    if args.session_root:
        session_root = os.path.abspath(args.session_root)
        os.makedirs(session_root, exist_ok=True)
    else:
        session_root = tempfile.mkdtemp(prefix="jot_browser_")
        temp_dir_to_clean = session_root

    print("=" * 60)
    print("  jot - Browser Host Dev Runner")
    print("=" * 60)
    print(f"Backend URL:    http://127.0.0.1:{args.port}")
    if not args.no_vite:
        print(f"Frontend URL:   http://localhost:{args.vite_port}")
    print(f"Session Root:   {session_root}")
    print(f"Scenario Mode:  {args.scenario.upper()} (Deterministic / No Gemini)")
    print("=" * 60)

    # Launch Vite if requested
    vite_proc: subprocess.Popen | None = None
    if not args.no_vite:
        node_cmd = shutil.which("node")
        vite_script = WEBUI_DIR / "node_modules" / "vite" / "bin" / "vite.js"
        if not node_cmd or not vite_script.is_file():
            parser.error("Node o lo script locale di Vite non sono disponibili")
        vite_env = os.environ.copy()
        vite_env["JOT_BACKEND_PORT"] = str(args.port)
        vite_args = [
            node_cmd,
            str(vite_script),
            "--host=127.0.0.1",
            f"--port={args.vite_port}",
            "--strictPort",
        ]
        vite_proc = subprocess.Popen(vite_args, cwd=str(WEBUI_DIR), env=vite_env)

    # Launch Uvicorn in current process (or subprocess)
    if args.open:
        target_url = (
            f"http://localhost:{args.vite_port}"
            if not args.no_vite
            else f"http://127.0.0.1:{args.port}"
        )

        def _open_browser():
            time.sleep(1.5)
            webbrowser.open(target_url)

        import threading

        threading.Thread(target=_open_browser, daemon=True).start()

    try:
        import uvicorn

        from jot.browser_server.server import create_browser_app

        app = create_browser_app(
            session_root=session_root,
            scenario=args.scenario,
        )
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=args.port,
            log_level="info",
        )
    except KeyboardInterrupt:
        print("\nArresto in corso...")
    finally:
        if vite_proc is not None:
            vite_proc.terminate()
            try:
                vite_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                vite_proc.kill()

        if temp_dir_to_clean and os.path.exists(temp_dir_to_clean):
            try:
                shutil.rmtree(temp_dir_to_clean, ignore_errors=True)
            except Exception:
                pass


if __name__ == "__main__":
    main()

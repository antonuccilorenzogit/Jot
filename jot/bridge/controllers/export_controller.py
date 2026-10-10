"""
Export, import, and package sharing IPC bridge controller.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import webview

from jot.bridge.bridge_utils import bridge_error, bridge_ok
from jot.core.shared import _load_json
from jot.services.sharing_service import (
    create_sbobina_package,
    unpack_and_import_package,
)
from jot.utils.logging_utils import redact_secrets

if TYPE_CHECKING:

    def _get_session_root(self) -> str: ...
    def _invalidate_sessions_cache(self) -> None: ...


class ExportControllerMixin:
    """Mixin providing package export and import IPC methods."""

    if TYPE_CHECKING:
        _window: webview.Window | None

        def _get_session_root(self) -> str: ...
        def _invalidate_sessions_cache(self) -> None: ...

    def export_sbobina_package(
        self,
        session_dir: str,
        export_type: str = "full",
        target_path: str | None = None,
    ) -> dict:
        """Export a session as a `.sbobina` package."""
        try:
            if not target_path and self._window:
                session_path = os.path.join(session_dir, "session.json")
                session_data = (
                    _load_json(session_path) if os.path.isfile(session_path) else {}
                )
                title = session_data.get("input", {}).get("name") or os.path.basename(
                    session_dir
                )
                nome_puro = os.path.splitext(title)[0]
                default_name = f"{nome_puro}_Sbobina.sbobina"

                try:
                    file_paths = self._window.create_file_dialog(
                        webview.SAVE_DIALOG,
                        save_filename=default_name,
                        file_types=(
                            "Pacchetto Sbobina (*.sbobina)",
                            "Tutti i file (*.*)",
                        ),
                    )
                except Exception:
                    file_paths = self._window.create_file_dialog(
                        webview.SAVE_DIALOG,
                        save_filename=default_name,
                    )
                if not file_paths:
                    return bridge_error("Operazione annullata.", cancelled=True)
                target_path = str(
                    file_paths[0]
                    if isinstance(file_paths, list | tuple)
                    else file_paths
                )

            if not target_path:
                return bridge_error("Percorso di destinazione non specificato.")

            res = create_sbobina_package(
                session_dir,
                target_path,
                include_mode=export_type,  # type: ignore[arg-type]
            )
            return res
        except Exception as e:
            return bridge_error(e)

    def import_sbobina_package(self, package_path: str | None = None) -> dict:
        """Import a `.sbobina` package into the session store."""
        try:
            if not package_path and self._window:
                try:
                    file_paths = self._window.create_file_dialog(
                        webview.OPEN_DIALOG,
                        allow_multiple=False,
                        file_types=(
                            "Pacchetto Sbobina (*.sbobina;*.zip)",
                            "Tutti i file (*.*)",
                        ),
                    )
                except Exception:
                    file_paths = self._window.create_file_dialog(
                        webview.OPEN_DIALOG,
                        allow_multiple=False,
                    )
                if not file_paths:
                    return bridge_error("Operazione annullata.", cancelled=True)
                package_path = str(
                    file_paths[0]
                    if isinstance(file_paths, list | tuple)
                    else file_paths
                )

            if not package_path:
                return bridge_error("Nessun pacchetto selezionato.")

            res = unpack_and_import_package(package_path, self._get_session_root())
            if res.get("ok"):
                self._invalidate_sessions_cache()
            return res
        except Exception as e:
            return bridge_error(e)

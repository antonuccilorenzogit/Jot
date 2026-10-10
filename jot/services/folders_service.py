"""
Archive folder management for jot.

Folders are persisted in the same app-data directory as config.json,
in a file called ``folders.json``.

Data model::

    {
      "folders": [
        {
          "id": "<uuid>",
          "name": "Anatomia",
          "color": "#FF6B6B",
          "session_dirs": ["<absolute/session/dir>", ...]
        },
        ...
      ]
    }
"""

from __future__ import annotations

import json
import os

from jot.services.config_service import CONFIG_FILE

FOLDERS_FILE = os.path.join(os.path.dirname(CONFIG_FILE), "folders.json")


def get_folders() -> list[dict]:
    """Return the saved folder list, or ``[]`` if the file is absent or corrupt."""
    try:
        if not os.path.isfile(FOLDERS_FILE):
            return []
        with open(FOLDERS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return []
        folders = data.get("folders", [])
        if not isinstance(folders, list):
            return []
        return [f for f in folders if isinstance(f, dict)]
    except Exception:
        return []


def save_folders(folders: list[dict]) -> None:
    """Atomically write *folders* to disk."""
    if not isinstance(folders, list):
        raise TypeError("folders must be a list")
    os.makedirs(os.path.dirname(FOLDERS_FILE), exist_ok=True)
    tmp = FOLDERS_FILE + ".tmp"
    payload = json.dumps({"folders": folders}, ensure_ascii=False, indent=2)
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, FOLDERS_FILE)
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        raise


def _path_under_root(path: str, root: str) -> bool:
    """Return True if *path* equals or is nested under *root*.

    Uses os.path.normcase so the comparison is case-insensitive on Windows.
    """
    nc_path = os.path.normcase(os.path.realpath(path))
    nc_root = os.path.normcase(os.path.realpath(root))
    if nc_path == nc_root:
        return True
    if not nc_root.endswith(os.sep):
        nc_root += os.sep
    return nc_path.startswith(nc_root)


def migrate_session_roots(old_root: str, new_root: str) -> list[dict]:
    """Migrate session_dirs in all saved folders from old_root to new_root.

    Returns the updated folders list and persists them to disk.
    """
    old_clean = str(old_root or "").strip()
    new_clean = str(new_root or "").strip()
    if not old_clean or not new_clean:
        return get_folders()

    old_real = os.path.realpath(old_clean)
    new_real = os.path.realpath(new_clean)
    if os.path.normcase(old_real) == os.path.normcase(new_real):
        return get_folders()

    folders = get_folders()
    if not folders:
        return []

    modified = False
    migrated_folders: list[dict] = []
    for folder in folders:
        f_copy = dict(folder)
        session_dirs = f_copy.get("session_dirs")
        if isinstance(session_dirs, list):
            new_dirs: list[str] = []
            seen: set[str] = set()
            for s_dir in session_dirs:
                if not isinstance(s_dir, str) or not s_dir.strip():
                    continue
                s_dir_str = s_dir.strip()
                if _path_under_root(s_dir_str, old_real):
                    try:
                        rel = os.path.relpath(os.path.realpath(s_dir_str), old_real)
                        migrated_path = os.path.normpath(os.path.join(new_clean, rel))
                        if migrated_path != s_dir_str:
                            modified = True
                        s_dir_str = migrated_path
                    except (ValueError, OSError):
                        pass
                norm = os.path.normcase(os.path.realpath(s_dir_str))
                if norm not in seen:
                    seen.add(norm)
                    new_dirs.append(s_dir_str)
            if new_dirs != session_dirs:
                modified = True
            f_copy["session_dirs"] = new_dirs
        migrated_folders.append(f_copy)

    if modified:
        save_folders(migrated_folders)

    return migrated_folders


def reconcile_folders_with_session_root(
    folders: list[dict], session_root: str | None = None
) -> tuple[list[dict], bool]:
    """Reconcile session_dirs pointing to nonexistent paths with session_root.

    If a session directory does not exist at its saved path, but a directory
    with the same folder name exists inside session_root, the path is healed.
    Returns (updated_folders, modified_flag).
    """
    if not folders or not session_root:
        return folders, False

    root_str = str(session_root).strip()
    if not root_str or not os.path.isdir(root_str):
        return folders, False

    modified = False
    reconciled_folders: list[dict] = []

    for folder in folders:
        f_copy = dict(folder)
        session_dirs = f_copy.get("session_dirs")
        if isinstance(session_dirs, list):
            new_dirs: list[str] = []
            seen: set[str] = set()
            for s_dir in session_dirs:
                if not isinstance(s_dir, str) or not s_dir.strip():
                    continue
                s_dir_str = s_dir.strip()
                base_name = os.path.basename(os.path.normpath(s_dir_str))
                if base_name:
                    candidate = os.path.normpath(os.path.join(root_str, base_name))
                    if os.path.isdir(candidate) and (
                        _path_under_root(s_dir_str, root_str)
                        or not os.path.isdir(s_dir_str)
                    ):
                        if s_dir_str != candidate:
                            s_dir_str = candidate
                            modified = True
                norm = os.path.normcase(os.path.realpath(s_dir_str))
                if norm not in seen:
                    seen.add(norm)
                    new_dirs.append(s_dir_str)
            if new_dirs != session_dirs:
                modified = True
            f_copy["session_dirs"] = new_dirs
        reconciled_folders.append(f_copy)

    if modified:
        try:
            save_folders(reconciled_folders)
        except Exception:
            pass

    return reconciled_folders, modified

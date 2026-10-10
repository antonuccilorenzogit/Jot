import json
import os
import zipfile
from unittest.mock import patch

import pytest

from jot.services.sharing_service import (
    _safe_zip_extract,
    create_sbobina_package,
    find_audio_for_session,
    unpack_and_import_package,
)


def test_create_sbobina_package_full_and_unpack(tmp_path):
    # Setup mock session directory
    session_dir = tmp_path / "mock_session"
    session_dir.mkdir()

    session_json = session_dir / "session.json"
    session_json.write_text(
        '{"stage": "done", "input": {"name": "lezione.mp3"}}', encoding="utf-8"
    )

    html_file = session_dir / "Sbobina.html"
    html_file.write_text("<h1>Test Sbobina</h1>", encoding="utf-8")

    audio_file = session_dir / "lezione.mp3"
    audio_file.write_bytes(b"MOCK_AUDIO_DATA_12345")

    target_zip = tmp_path / "exports" / "lezione_Sbobina.sbobina"

    # 1. Create full package
    res = create_sbobina_package(str(session_dir), str(target_zip), include_mode="full")
    assert res["ok"] is True
    assert res["audio_included"] is True
    assert os.path.exists(str(target_zip))

    # Verify zip contents
    with zipfile.ZipFile(str(target_zip), "r") as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert "session.json" in names
        assert "Sbobina.html" in names
        assert "audio/lezione.mp3" in names

    # 2. Unpack into new session root
    session_root = tmp_path / "sessions_root"
    session_root.mkdir()

    import_res = unpack_and_import_package(str(target_zip), str(session_root))
    assert import_res["ok"] is True
    assert import_res["has_audio"] is True
    imported_dir = import_res["session_dir"]
    assert os.path.isdir(imported_dir)
    assert os.path.isfile(os.path.join(imported_dir, "Sbobina.html"))
    assert os.path.isfile(os.path.join(imported_dir, "audio", "lezione.mp3"))


def test_create_sbobina_package_text_only(tmp_path):
    session_dir = tmp_path / "mock_session_text"
    session_dir.mkdir()

    session_json = session_dir / "session.json"
    session_json.write_text(
        '{"stage": "done", "input": {"name": "test.mp3"}}', encoding="utf-8"
    )

    html_file = session_dir / "Sbobina.html"
    html_file.write_text("<h1>Text Only Sbobina</h1>", encoding="utf-8")

    target_zip = tmp_path / "exports" / "text_only.sbobina"

    res = create_sbobina_package(
        str(session_dir), str(target_zip), include_mode="text_only"
    )
    assert res["ok"] is True
    assert res["audio_included"] is False

    with zipfile.ZipFile(str(target_zip), "r") as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert "Sbobina.html" in names
        assert not any(n.startswith("audio/") for n in names)


def test_create_sbobina_package_audio_missing(tmp_path):
    session_dir = tmp_path / "no_audio_session"
    session_dir.mkdir()
    target_zip = tmp_path / "audio_only.sbobina"

    res = create_sbobina_package(
        str(session_dir), str(target_zip), include_mode="audio_only"
    )
    assert res["ok"] is False
    assert "File audio sorgente non trovato" in res["error"]


def test_safe_zip_extract_prevents_zip_slip(tmp_path):
    malicious_zip_path = tmp_path / "malicious.zip"
    target_extract = tmp_path / "extract_dir"
    target_extract.mkdir()

    with zipfile.ZipFile(str(malicious_zip_path), "w") as zf:
        zf.writestr("../evil.txt", "hacked")

    with zipfile.ZipFile(str(malicious_zip_path), "r") as zf:
        with pytest.raises(ValueError, match="Attacco Zip Slip rilevato"):
            _safe_zip_extract(zf, str(target_extract))


def test_unpack_invalid_package(tmp_path):
    invalid_file = tmp_path / "corrupt.sbobina"
    invalid_file.write_text("not a zip file", encoding="utf-8")
    session_root = tmp_path / "session_root"
    session_root.mkdir()

    res = unpack_and_import_package(str(invalid_file), str(session_root))
    assert res["ok"] is False
    assert "non è un pacchetto .sbobina valido" in res["error"]

    res_missing = unpack_and_import_package(
        str(tmp_path / "non_existent.sbobina"), str(session_root)
    )
    assert res_missing["ok"] is False
    assert "non trovato" in res_missing["error"]


def test_api_import_sbobina_package_invalidates_cache(tmp_path):
    from jot.app_webview import JotApi

    api = JotApi()
    session_dir = tmp_path / "mock_session"
    session_dir.mkdir()
    (session_dir / "session.json").write_text(
        '{"input": {"name": "test.mp3"}}', encoding="utf-8"
    )

    pkg_path = tmp_path / "test.sbobina"
    create_sbobina_package(str(session_dir), str(pkg_path), include_mode="text_only")

    custom_root = tmp_path / "custom_session_root"
    custom_root.mkdir()

    with patch.object(api, "_get_session_root", return_value=str(custom_root)):
        res = api.import_sbobina_package(package_path=str(pkg_path))
        assert res["ok"] is True
        assert api._sessions_cache is None


def test_safe_zip_extract_rejects_symlink(tmp_path):
    symlink_zip_path = tmp_path / "symlink.zip"
    target_extract = tmp_path / "extract_dir"
    target_extract.mkdir()

    with zipfile.ZipFile(str(symlink_zip_path), "w") as zf:
        zinfo = zipfile.ZipInfo("symlink_file")
        # Set POSIX S_IFLNK attribute (0o120000) in external_attr
        zinfo.external_attr = 0o120777 << 16
        zf.writestr(zinfo, "/etc/passwd")

    with zipfile.ZipFile(str(symlink_zip_path), "r") as zf:
        with pytest.raises(ValueError, match="Link simbolici non consentiti"):
            _safe_zip_extract(zf, str(target_extract))


def test_safe_zip_extract_rejects_excessive_file_count(tmp_path):
    zip_path = tmp_path / "many_files.zip"
    target_extract = tmp_path / "extract_dir"
    target_extract.mkdir()

    with zipfile.ZipFile(str(zip_path), "w") as zf:
        for i in range(505):
            zf.writestr(f"file_{i}.txt", "x")

    with zipfile.ZipFile(str(zip_path), "r") as zf:
        with pytest.raises(ValueError, match=r"numero file .* supera il limite"):
            _safe_zip_extract(zf, str(target_extract))


def test_safe_zip_extract_rejects_zip_bomb_uncompressed_size(tmp_path):
    zip_path = tmp_path / "huge.zip"
    target_extract = tmp_path / "extract_dir"
    target_extract.mkdir()

    with zipfile.ZipFile(str(zip_path), "w") as zf:
        zf.writestr("test.bin", "x")

    with zipfile.ZipFile(str(zip_path), "r") as zf:
        fake_info = zipfile.ZipInfo("fake.bin")
        fake_info.file_size = 2000 * 1024 * 1024
        with patch.object(zf, "infolist", return_value=[fake_info]):
            with pytest.raises(
                ValueError, match="Dimensione decompressa totale eccede"
            ):
                _safe_zip_extract(zf, str(target_extract))


def test_unpack_text_only_clears_host_audio_path(tmp_path):
    # Setup session with audio on creator PC
    session_dir = tmp_path / "creator_session"
    session_dir.mkdir()
    (session_dir / "session.json").write_text(
        '{"input": {"name": "lecture.mp3", "path": "/home/victim/Music/private.mp3", "path_rel_to_session": "audio/private.mp3"}}',
        encoding="utf-8",
    )
    (session_dir / "Sbobina.html").write_text("<p>Sbobina</p>", encoding="utf-8")

    pkg_path = tmp_path / "shared.sbobina"
    create_sbobina_package(str(session_dir), str(pkg_path), include_mode="text_only")

    session_root = tmp_path / "receiver_root"
    session_root.mkdir()

    res = unpack_and_import_package(str(pkg_path), str(session_root))
    assert res["ok"] is True
    assert res["has_audio"] is False

    # Verify session.json in imported dir has cleared input.path
    imported_session_file = os.path.join(res["session_dir"], "session.json")
    with open(imported_session_file, encoding="utf-8") as f:
        imported_session_json = json.load(f)
    assert imported_session_json["input"]["path"] is None
    assert imported_session_json["input"]["path_rel_to_session"] is None

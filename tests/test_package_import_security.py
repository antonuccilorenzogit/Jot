import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from jot.services import sharing_service as sharing
from jot.services.revision_service import build_macro_blocks
from jot.utils.file_ops import save_html_body_content
from tests.bridge.test_controllers import DummyHtmlHost, DummySystemHost


def package(tmp_path, entries):
    path = tmp_path / "input.sbobina"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries:
            archive.writestr(name, value)
    return path


def import_package(tmp_path, entries):
    root = tmp_path / "sessions"
    root.mkdir(exist_ok=True)
    result = sharing.unpack_and_import_package(
        str(package(tmp_path, entries)), str(root)
    )
    return result, root


@pytest.mark.parametrize("include_mode", ["text_only", "full"])
def test_exported_long_transcript_can_be_reimported(tmp_path, include_mode):
    source = tmp_path / "source"
    source.mkdir()
    audio = source / "lecture.mp3"
    audio.write_bytes(b"audio fixture")
    (source / "session.json").write_text(
        json.dumps(
            {
                "stage": "done",
                "input": {"name": "Lezione lunga", "path": str(audio)},
                "outputs": {},
            }
        ),
        encoding="utf-8",
    )
    (source / "Sbobina.html").write_text(
        "<h1>Lezione lunga</h1><p>Contenuto della lezione</p>", encoding="utf-8"
    )
    blocks = build_macro_blocks(("Testo della lezione. " * 50 + "\n\n") * 1100, 22000)
    macro_data = {"limit_chars": 22000, "blocks": blocks}
    macro = source / "phase2_macro_blocks.json"
    macro.write_text(json.dumps(macro_data, ensure_ascii=False), encoding="utf-8")
    assert macro.stat().st_size > sharing.MAX_JSON_SIZE
    archive = tmp_path / "lesson.sbobina"
    exported = sharing.create_sbobina_package(str(source), str(archive), include_mode)
    assert exported["ok"]
    destination = tmp_path / "sessions"
    destination.mkdir()
    imported = sharing.unpack_and_import_package(str(archive), str(destination))
    assert imported["ok"], imported.get("error")
    imported_dir = Path(imported["session_dir"])
    assert (
        json.loads((imported_dir / macro.name).read_text(encoding="utf-8"))
        == macro_data
    )
    assert "Contenuto della lezione" in Path(imported["html_path"]).read_text(
        encoding="utf-8"
    )
    assert imported["has_audio"] is (include_mode == "full")


def test_import_rebuilds_all_html_and_preserves_editor_content(tmp_path):
    original = '<html><head><script>headAttack()</script><style>.evil{color:red}</style><meta http-equiv="refresh" content="0;url=https://evil.example"></head><body onload="attack()"><h2>Lezione &amp; formule</h2><table><tr><td colspan="2">Dato</td></tr></table><span data-math="x^2" data-math-block="true">x²</span><img src="data:image/png;base64,AA==" width="100" onerror="attack()"><a href="javascript:attack()">link</a><script>bodyAttack()</script></body></html>'
    root = tmp_path / "sessions"
    root.mkdir()
    prior = root / "old.html"
    prior.write_text("existing document", encoding="utf-8")
    result, _ = import_package(
        tmp_path,
        [
            ("manifest.json", json.dumps({"session_name": "<script>title</script>"})),
            ("Sbobina.html", original),
            ("nested/SECOND.HTML", original),
            ("fragment.htm", "<h1>Frammento</h1>"),
        ],
    )
    assert result["ok"]
    directory = sharing.os.path.dirname(result["html_path"])
    for relative in ("Sbobina.html", "nested/SECOND.HTML", "fragment.htm"):
        with open(
            sharing.os.path.join(directory, relative), encoding="utf-8"
        ) as handle:
            html = handle.read()
        assert "Content-Security-Policy" in html
        assert "&lt;script&gt;title&lt;/script&gt;" in html
        assert "default-src 'none'" in html
        assert "<script" not in html
        assert "onerror=" not in html and "onload=" not in html
        assert "javascript:" not in html and "headAttack" not in html
        assert ".evil" not in html and 'http-equiv="refresh"' not in html
        if relative != "fragment.htm":
            assert 'colspan="2"' in html
            assert 'data-math="x^2"' in html and 'data-math-block="true"' in html
            assert 'src="data:image/png;base64,AA=="' in html
            assert "<h2>Lezione &amp; formule</h2>" in html
    assert prior.read_text(encoding="utf-8") == "existing document"
    assert save_html_body_content(result["html_path"], '<p data-math="a+b">Edit</p>')
    with open(result["html_path"], encoding="utf-8") as handle:
        saved = handle.read()
    assert "Content-Security-Policy" in saved and 'data-math="a+b"' in saved
    assert "<script" not in saved
    preview = DummyHtmlHost(str(root)).read_html_content(result["html_path"])
    assert preview["ok"] and preview["content"] == saved
    with patch(
        "jot.bridge.controllers.system_controller.file_ops.open_path_with_default_app"
    ) as opener:
        opened = DummySystemHost(str(root)).open_file(result["html_path"])
    assert opened["ok"]
    opener.assert_called_once_with(sharing.os.path.realpath(result["html_path"]))


@pytest.mark.parametrize("caption_source", ["figcaption", "data-caption", "both"])
def test_import_preserves_image_caption_structure_and_removes_active_content(
    tmp_path, caption_source
):
    caption = "Figura 1: schema & formula"
    attribute = (
        ' data-caption="Figura 1: schema &amp; formula"'
        if caption_source in {"data-caption", "both"}
        else ""
    )
    element = (
        '<figcaption class="editor-image-caption" onclick="attack()">'
        "Figura 1: schema &amp; formula<script>attack()</script></figcaption>"
        if caption_source in {"figcaption", "both"}
        else ""
    )
    original = (
        f'<div data-editor-image="true" data-width="56"{attribute}>'
        '<img src="data:image/png;base64,AA==" width="355">'
        f"{element}</div>"
    )
    result, _ = import_package(tmp_path, [("Sbobina.html", original)])
    assert result["ok"], result.get("error")
    imported = Path(result["html_path"]).read_text(encoding="utf-8")

    from html.parser import HTMLParser

    class CaptionParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.caption_attribute = None
            self.has_figcaption = False

        def handle_starttag(self, tag, attrs):
            if tag == "div":
                self.caption_attribute = dict(attrs).get("data-caption")
            if tag == "figcaption":
                self.has_figcaption = True

    parsed = CaptionParser()
    parsed.feed(imported)
    assert parsed.has_figcaption is (caption_source in {"figcaption", "both"})
    assert parsed.caption_attribute == (
        caption if caption_source in {"data-caption", "both"} else None
    )
    assert "Content-Security-Policy" in imported
    assert "<script" not in imported and "onclick=" not in imported
    assert "attack()" not in imported


@pytest.mark.parametrize(
    "name",
    [
        "/absolute.html",
        "../escape",
        r"..\escape",
        r"C:\evil",
        "file:stream",
        "CON.txt",
        "lpt1",
        "trailing.",
        "trailing ",
        "bad?.txt",
        "a//b",
    ],
)
def test_portable_invalid_paths_are_rejected_without_partial_session(tmp_path, name):
    result, root = import_package(tmp_path, [(name, "bad")])
    assert not result["ok"]
    assert not list(root.iterdir())


@pytest.mark.parametrize(
    "names", [("same.txt", "SAME.TXT"), ("a/b.txt", r"a\b.txt"), ("folder", "folder/")]
)
def test_normalized_duplicates_are_rejected(tmp_path, names):
    result, root = import_package(tmp_path, [(name, "test") for name in names])
    assert not result["ok"] and "duplicata" in result["error"]
    assert not list(root.iterdir())


@pytest.mark.parametrize(
    "filename,limit",
    [
        ("session.json", "MAX_JSON_SIZE"),
        ("OTHER.JSON", "MAX_JSON_SIZE"),
        ("nested/phase2_macro_blocks.json", "MAX_JSON_SIZE"),
        ("phase2_macro_blocks.json", "MAX_TRANSCRIPT_JSON_SIZE"),
        ("PHASE2_MACRO_BLOCKS.JSON", "MAX_TRANSCRIPT_JSON_SIZE"),
        ("Sbobina.html", "MAX_HTML_SIZE"),
        ("extra.HTM", "MAX_HTML_SIZE"),
    ],
)
def test_per_file_limits_reject_declared_oversize(
    tmp_path, monkeypatch, filename, limit
):
    monkeypatch.setattr(sharing, limit, 8)
    result, root = import_package(tmp_path, [(filename, "x" * 9)])
    assert not result["ok"] and not list(root.iterdir())


@pytest.mark.parametrize("metadata", ["[]", "null", '"string"', "{"])
@pytest.mark.parametrize("name", ["manifest.json", "session.json"])
def test_metadata_must_be_valid_json_object(tmp_path, metadata, name):
    result, root = import_package(tmp_path, [(name, metadata)])
    assert not result["ok"] and not list(root.iterdir())


def test_disk_space_margin_is_checked_before_extracting(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sharing.shutil,
        "disk_usage",
        lambda _: SimpleNamespace(free=sharing.DISK_SPACE_MARGIN),
    )
    result, root = import_package(tmp_path, [("audio/a.mp3", b"123")])
    assert not result["ok"] and "Spazio" in result["error"]
    assert not list(root.iterdir())


@pytest.mark.parametrize(
    "limit_name,filename",
    [
        ("MAX_TOTAL_UNCOMPRESSED_SIZE", "audio.mp3"),
        ("MAX_JSON_SIZE", "session.json"),
        ("MAX_TRANSCRIPT_JSON_SIZE", "phase2_macro_blocks.json"),
        ("MAX_HTML_SIZE", "Sbobina.html"),
    ],
)
def test_streamed_actual_bytes_enforce_limits(
    tmp_path, monkeypatch, limit_name, filename
):
    monkeypatch.setattr(sharing, limit_name, 8)
    member = zipfile.ZipInfo(filename)
    member.file_size = 1  # Exercise the real-byte guard independently of metadata.
    archive = MagicMock(spec=zipfile.ZipFile)
    archive.infolist.return_value = [member]
    archive.open.return_value = io.BytesIO(b"123456789")
    with pytest.raises(ValueError, match="effettiva"):
        sharing._safe_zip_extract(archive, str(tmp_path))


@pytest.mark.parametrize(
    "failure", [OSError("disk full"), zipfile.BadZipFile("Bad CRC")]
)
def test_interrupted_stream_import_cleans_session(tmp_path, monkeypatch, failure):
    path = package(tmp_path, [("audio/a.mp3", b"123")])
    root = tmp_path / "sessions"
    root.mkdir()
    original = zipfile.ZipFile.open

    def broken_open(archive, member, *args, **kwargs):
        if archive.mode == "r":
            raise failure
        return original(archive, member, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", broken_open)
    result = sharing.unpack_and_import_package(str(path), str(root))
    assert not result["ok"] and not list(root.iterdir())


def test_sanitizer_failure_cleans_import(tmp_path):
    with patch.object(
        sharing, "normalize_imported_html", side_effect=ValueError("parse failure")
    ):
        result, root = import_package(tmp_path, [("Sbobina.html", "<p>test</p>")])
    assert not result["ok"] and not list(root.iterdir())


def test_actual_crc_error_removes_import_directory(tmp_path):
    path = tmp_path / "corrupt.sbobina"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("audio/a.mp3", b"original bytes")
    content = bytearray(path.read_bytes())
    offset = (
        30
        + int.from_bytes(content[26:28], "little")
        + int.from_bytes(content[28:30], "little")
    )
    content[offset] ^= 1
    path.write_bytes(content)
    root = tmp_path / "sessions"
    root.mkdir()
    result = sharing.unpack_and_import_package(str(path), str(root))
    assert not result["ok"] and "CRC" in result["error"]
    assert not list(root.iterdir())


def test_stream_failure_after_partial_write_removes_directory(tmp_path, monkeypatch):
    class InterruptedStream(io.BytesIO):
        def read(self, size=-1):
            if self.tell():
                raise OSError("read interrupted")
            return super().read(size)

    monkeypatch.setattr(sharing, "EXTRACTION_BLOCK_SIZE", 2)
    path = package(tmp_path, [("audio/a.mp3", b"1234")])
    monkeypatch.setattr(
        zipfile.ZipFile, "open", lambda *_args, **_kwargs: InterruptedStream(b"1234")
    )
    root = tmp_path / "sessions"
    root.mkdir()
    result = sharing.unpack_and_import_package(str(path), str(root))
    assert not result["ok"] and "interrupted" in result["error"]
    assert not list(root.iterdir())


def test_foreign_output_path_is_not_registered_without_local_html(tmp_path):
    result, _ = import_package(
        tmp_path,
        [("session.json", json.dumps({"outputs": {"html": "C:/foreign/file.html"}}))],
    )
    assert result["ok"] and result["html_path"] is None
    with open(
        sharing.os.path.join(result["session_dir"], "session.json"), encoding="utf-8"
    ) as handle:
        assert "html" not in json.load(handle)["outputs"]


def test_import_preserves_body_when_head_end_tag_is_omitted(tmp_path):
    html = '<!doctype html><html><head><title>Lezione</title><script>attack()</script><body onload="attack()"><h1>Lezione</h1><p>Contenuto della lezione &amp; formule</p></body></html>'
    result, _ = import_package(tmp_path, [("Sbobina.html", html)])
    assert result["ok"]
    with open(result["html_path"], encoding="utf-8") as handle:
        imported = handle.read()
    assert "<h1>Lezione</h1>" in imported
    assert "<p>Contenuto della lezione &amp; formule</p>" in imported
    assert "Content-Security-Policy" in imported
    assert "<script" not in imported and "attack()" not in imported


@pytest.mark.parametrize(
    "opening",
    [
        "<html><head><title>UNTRUSTED_HEAD_TITLE</title>",
        "<html><head><title>UNTRUSTED_HEAD_TITLE</title></head>",
        "<html><title>UNTRUSTED_HEAD_TITLE</title>",
    ],
)
def test_import_preserves_implicit_body_and_excludes_head_content(tmp_path, opening):
    html = (
        "<!doctype html>"
        + opening
        + "<script>headAttack()</script><style>.evil{color:red}</style>"
        + '<meta http-equiv="refresh" content="0;url=https://evil.example">'
        + "<h1>Lezione</h1><p>Contenuto della lezione &amp; formule</p>"
        + '<span data-math="x^2" data-math-block="true">x²</span>'
        + '<img src="data:image/png;base64,AA==" onerror="attack()">'
        + "<script>bodyAttack()</script></html>"
    )
    result, _ = import_package(tmp_path, [("Sbobina.html", html)])
    assert result["ok"]
    imported = sharing.os.path.join(result["session_dir"], "Sbobina.html")
    with open(imported, encoding="utf-8") as handle:
        content = handle.read()
    assert "<h1>Lezione</h1>" in content
    assert "<p>Contenuto della lezione &amp; formule</p>" in content
    assert 'data-math="x^2"' in content and 'data-math-block="true"' in content
    assert 'src="data:image/png;base64,AA=="' in content
    assert "UNTRUSTED_HEAD_TITLE" not in content
    assert "Content-Security-Policy" in content and "default-src 'none'" in content
    assert "<script" not in content and "Attack()" not in content
    assert ".evil" not in content and 'http-equiv="refresh"' not in content
    assert "onerror=" not in content

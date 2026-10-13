"""
Markdown -> HTML export utilities for jot.

Used for local HTML output (copy/paste into Docs) with basic sanitization.
"""

from __future__ import annotations

import html as _html
import re

_ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "p",
        "br",
        "hr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "strong",
        "em",
        "u",
        "s",
        "mark",
        "code",
        "pre",
        "sub",
        "sup",
        "ul",
        "ol",
        "li",
        "blockquote",
        "table",
        "thead",
        "tbody",
        "tfoot",
        "tr",
        "th",
        "td",
        "colgroup",
        "col",
        "caption",
        "a",
        "span",
        "div",
        "img",
        "figcaption",
    }
)

_ALLOWED_ATTRS: dict[str, set[str]] = {
    "*": {
        "style",
        "class",
        "data-editor-image",
        "data-layout",
        "data-align",
        "data-width",
        "data-caption",
        "data-math",
        "data-math-block",
        "data-t",
        "align",
    },
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "width", "height", "align"},
    "th": {"colspan", "rowspan", "colwidth", "width", "scope"},
    "td": {"colspan", "rowspan", "colwidth", "width"},
    "col": {"width", "span"},
    "colgroup": {"span"},
    "table": {"border", "cellpadding", "cellspacing"},
}

_ALLOWED_URL_SCHEMES: frozenset[str] = frozenset({"http", "https", "mailto", "data"})


def sanitize_html_basic(html: str, *, strip_document_head: bool = False) -> str:
    # Sanitizzazione tramite allowlist (nh3/ammonia) — blocca tag/attributi non permessi
    # e schemi URL pericolosi (javascript:, vbscript:). data: è permesso per src img inline.
    try:
        import nh3 as _nh3
    except ImportError:  # pragma: no cover
        _nh3 = None  # type: ignore[assignment]

    if _nh3 is None:  # pragma: no cover
        raise ImportError(
            "nh3 is required for HTML sanitization. Install it with: pip install nh3"
        )
    return _nh3.clean(
        html or "",
        tags=set(_ALLOWED_TAGS),
        attributes=_ALLOWED_ATTRS,
        url_schemes=set(_ALLOWED_URL_SCHEMES),
        strip_comments=True,
        clean_content_tags={"head", "title", "script", "style"}
        if strip_document_head
        else None,
    )


def normalize_inline_star_lists(md: str) -> str:
    # Normalizza elenchi che a volte l'AI produce in modo non-standard.
    src = (md or "").replace("\u00a0", " ")

    list_line_re = r"^\s*([*+-]|\d+\.)\s+"
    # Bullet unicode che il modello usa spesso (e che Markdown non interpreta come liste).
    bullet_top = ("\u25cf", "\u2022", "\u25aa", "\u2023", "\u25a0")  # ● • ▪ ‣ ■

    # 1) Trasforma elenchi in-line tipo "Esempi: * Voce1 ... * Voce2 ..."
    out_lines = []
    in_fence = False
    for line in src.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        if in_fence:
            out_lines.append(line)
            continue

        # Caso A: riga che INIZIA con bullet unicode -> lista Markdown.
        if not re.match(list_line_re, line):
            m = re.match(
                r"^(\s*)([\u25cf\u2022\u25aa\u2023\u25e6\u25cb\u2219\u25a0\u25a1])\s+(.*)$",
                line,
            )
            if m:
                bullet = m.group(2)
                rest = m.group(3).strip()
                if rest:
                    prefix = "- " if bullet in bullet_top else "    - "
                    out_lines.append(prefix + rest)
                    continue

        # Caso B: bullet unicode "in mezzo" a una riga -> spezza in lista.
        if not re.match(list_line_re, line) and re.search(
            r"[\u25cf\u2022\u25aa\u2023\u25a0\u25a1]\s+(\*\*|[A-ZÀ-ÖØ-Ý])", line
        ):
            if re.search(r"\s[\u25cf\u2022\u25aa\u2023\u25a0\u25a1]\s+", line):
                parts = re.split(r"\s*[\u25cf\u2022\u25aa\u2023\u25a0\u25a1]\s+", line)
                if len(parts) > 1:
                    first = (parts[0] or "").rstrip()
                    if first:
                        out_lines.append(first)
                    for item in parts[1:]:
                        item = (item or "").strip()
                        if item:
                            out_lines.append("- " + item)
                    continue

        # Converti solo se:
        # - c'e' un ":" seguito da "* " (tipico "Esempi: * ... * ...")
        if not re.match(r"^\s*([*+-]|\d+\.)\s+", line) and re.search(
            r":[ \t]*\*[ \t]+(\*\*|[A-ZÀ-ÖØ-Ý])", line
        ):
            if line.count("* ") >= 1:
                line2 = re.sub(r":[ \t]*\*[ \t]+", ":\n\n- ", line, count=1)
                line2 = re.sub(r"[ \t]+\*[ \t]+", "\n- ", line2)
                out_lines.extend(line2.splitlines())
                continue

        out_lines.append(line)

    mid = "\n".join(out_lines)

    # 2) Python-Markdown spesso richiede una riga vuota prima di una lista per riconoscerla.
    fixed = []
    in_fence = False
    for line in mid.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            fixed.append(line)
            continue
        if in_fence:
            fixed.append(line)
            continue

        is_list = bool(re.match(r"^\s{0,3}([*+-]|\d+\.)\s+", line))
        if is_list and fixed:
            prev = fixed[-1]
            prev_is_list = bool(re.match(r"^\s{0,3}([*+-]|\d+\.)\s+", prev))
            if prev.strip() != "" and not prev_is_list:
                fixed.append("")

        fixed.append(line)

    return "\n".join(fixed)


def normalize_heading_levels(md: str) -> str:
    # Limita i titoli esportati a h1-h5, comprimendo eventuali livelli piu' profondi.
    lines: list[str] = []
    in_fence = False

    for line in (md or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            lines.append(line)
            continue

        if in_fence:
            lines.append(line)
            continue

        match = re.match(r"^(\s*)(#{1,})\s+(.*)$", line)
        if not match:
            lines.append(line)
            continue

        indent, hashes, content = match.groups()
        level = min(len(hashes), 5)
        lines.append(f"{indent}{'#' * level} {content.strip()}")

    return "\n".join(lines)


_MATH_BLOCK_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
# Inline math: no spaces just inside the dollars, so "costa 5 $ e 3 $" stays text.
_MATH_INLINE_RE = re.compile(r"(?<![\\$\w])\$(?!\s)([^$\n]+?)(?<!\s)\$(?![\w$])")
_HEADING_TIME_RE = re.compile(r"^(\s*#{1,6})\s+\[\[\s*t\s*=\s*(\d+)\s*\]\]\s*(.*)$")
_ANY_TIME_RE = re.compile(r"\[\[\s*t\s*=\s*\d+(?:\s*:\s*\d+)?\s*\]\]")


# Some models write LaTeX between \( \) and \[ \] (sometimes with the backslash
# doubled) instead of $ and $$: both become the dollar form jot understands.
_PAREN_MATH_RE = re.compile(r"\\{1,2}\((.+?)\\{1,2}\)", re.DOTALL)
_BRACKET_MATH_RE = re.compile(r"\\{1,2}\[(.+?)\\{1,2}\]", re.DOTALL)


def normalize_math_delimiters(md: str) -> str:
    r"""\(x\) -> $x$ and \[x\] -> $$x$$ (outside code fences)."""
    if "\\(" not in md and "\\[" not in md:
        return md
    out: list[str] = []
    in_fence = False
    chunk: list[str] = []

    def _flush() -> None:
        if chunk:
            text = "\n".join(chunk)
            text = _BRACKET_MATH_RE.sub(lambda m: f"$${m.group(1).strip()}$$", text)
            text = _PAREN_MATH_RE.sub(lambda m: f"${m.group(1).strip()}$", text)
            out.append(text)
            chunk.clear()

    for line in md.split("\n"):
        if line.strip().startswith("```"):
            _flush()
            in_fence = not in_fence
            out.append(line)
        elif in_fence:
            out.append(line)
        else:
            chunk.append(line)
    _flush()
    return "\n".join(out)


_EXISTING_MATH_RE = re.compile(
    r'<span data-math="[^"]*">.*?</span>|<div data-math-block="[^"]*">.*?</div>',
    re.DOTALL,
)
_HTML_BLOCK_MATH_RE = re.compile(
    r"<p>\s*\\{1,2}\[(?P<latex>[^<]+?)\\{1,2}\]\s*</p>|\\{1,2}\[(?P<inline_block>[^<]+?)\\{1,2}\]",
    re.DOTALL,
)
_HTML_INLINE_MATH_RE = re.compile(r"\\{1,2}\((?P<latex>[^<]+?)\\{1,2}\)", re.DOTALL)


def repair_math_in_html(html_text: str) -> str:
    r"""Lessons exported before this fix show \(x\) and \[x\] as plain text: turn
    them into real formulas. Formulas that are already real are left alone."""
    if "\\(" not in html_text and "\\[" not in html_text:
        return html_text
    kept: list[str] = []

    def _keep(match: re.Match) -> str:
        kept.append(match.group(0))
        return f"\x00MATH{len(kept) - 1}\x00"

    text = _EXISTING_MATH_RE.sub(_keep, html_text)

    def _block(match: re.Match) -> str:
        latex = _html.unescape(
            (match.group("latex") or match.group("inline_block") or "").strip()
        )
        attr = _html.escape(latex, quote=True)
        return f'<div data-math-block="{attr}">\\[{_html.escape(latex, quote=False)}\\]</div>'

    def _inline(match: re.Match) -> str:
        latex = _html.unescape(match.group("latex").strip())
        attr = _html.escape(latex, quote=True)
        return (
            f'<span data-math="{attr}">\\({_html.escape(latex, quote=False)}\\)</span>'
        )

    text = _HTML_BLOCK_MATH_RE.sub(_block, text)
    text = _HTML_INLINE_MATH_RE.sub(_inline, text)
    return re.sub(r"\x00MATH(\d+)\x00", lambda m: kept[int(m.group(1))], text)


def _protect_math(md: str) -> tuple[str, list[tuple[str, str]]]:
    """Swap LaTeX for placeholders so Markdown does not mangle it."""
    found: list[tuple[str, str]] = []

    def _block(match: re.Match) -> str:
        found.append(("block", match.group(1).strip()))
        return f"\n\nSBOBMATH{len(found) - 1}X\n\n"

    def _inline(match: re.Match) -> str:
        found.append(("inline", match.group(1).strip()))
        return f"SBOBMATH{len(found) - 1}X"

    out: list[str] = []
    in_fence = False
    chunk: list[str] = []

    def _flush() -> None:
        if chunk:
            text = "\n".join(chunk)
            text = _MATH_BLOCK_RE.sub(_block, text)
            text = _MATH_INLINE_RE.sub(_inline, text)
            out.append(text)
            chunk.clear()

    for line in md.split("\n"):
        if line.strip().startswith("```"):
            _flush()
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
        else:
            chunk.append(line)
    _flush()
    return "\n".join(out), found


def _restore_math(html_body: str, found: list[tuple[str, str]]) -> str:
    for index, (kind, latex) in enumerate(found):
        token = f"SBOBMATH{index}X"
        attr = _html.escape(latex, quote=True)
        text = _html.escape(latex, quote=False)
        if kind == "block":
            div = f'<div data-math-block="{attr}">\\[{text}\\]</div>'
            html_body = html_body.replace(f"<p>{token}</p>", div).replace(token, div)
        else:
            html_body = html_body.replace(
                token, f'<span data-math="{attr}">\\({text}\\)</span>'
            )
    return html_body


def apply_heading_timestamps(md: str) -> str:
    """ "## [[t=2610]] Titolo" -> "## Titolo {: data-t="2610" }"; other markers removed."""
    lines = []
    for line in (md or "").split("\n"):
        match = _HEADING_TIME_RE.match(line)
        if match:
            hashes, seconds, title = match.groups()
            title = _ANY_TIME_RE.sub("", title).strip()
            lines.append(f'{hashes} {title} {{: data-t="{int(seconds)}" }}')
        else:
            lines.append(_ANY_TIME_RE.sub("", line))
    return "\n".join(lines)


def build_html_document(title: str, markdown_text: str) -> str:
    import markdown

    normalized_markdown = normalize_heading_levels(markdown_text or "")
    normalized_markdown = apply_heading_timestamps(normalized_markdown)
    normalized_markdown = normalize_math_delimiters(normalized_markdown)
    protected, math = _protect_math(normalized_markdown)
    html_body = markdown.markdown(
        protected, extensions=["extra", "sane_lists"], output_format="html"
    )
    html_body = _restore_math(html_body, math)
    return build_html_document_from_body(title, html_body)


def normalize_imported_html(title: str, html: str) -> str:
    # nh3's HTML5 parser also handles omitted head/body tags without losing text.
    return build_html_document_from_body(title, html, strip_document_head=True)


def build_html_document_from_body(
    title: str, html_body: str, *, strip_document_head: bool = False
) -> str:
    """Wrap sanitized HTML in the same trusted document used by Markdown exports."""
    html_body = sanitize_html_basic(html_body, strip_document_head=strip_document_head)
    safe_title = (title or "Sbobina").strip()
    safe_title_html = _html.escape(safe_title, quote=True)
    # CSP: evita script e richieste di rete anche se l'AI inserisse tag HTML.
    csp = (
        "default-src 'none'; "
        "base-uri 'none'; "
        "form-action 'none'; "
        "frame-ancestors 'none'; "
        "connect-src 'none'; "
        "img-src data:; "
        "font-src data:; "
        "media-src 'none'; "
        "style-src 'unsafe-inline'"
    )
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="Content-Security-Policy" content="{csp}" />
  <meta http-equiv="Referrer-Policy" content="no-referrer" />
  <title>{safe_title_html} - Sbobina</title>
  <style>
    :root {{
      --text: #111;
      --muted: #444;
      --bg: #fff;
      --rule: #e6e6e6;
    }}
    body {{
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.6;
      color: var(--text);
      background: var(--bg);
      max-width: 980px;
      margin: 0 auto;
      padding: 48px 22px;
    }}
    h1, h2, h3, h4, h5 {{ line-height: 1.3; font-weight: 700; }}
    h1 {{ font-size: 20pt; margin: 0 0 0.9rem; }}
    h2 {{ font-size: 16pt; margin: 1.4rem 0 0.6rem; }}
    h3 {{ font-size: 14pt; margin: 1.15rem 0 0.45rem; }}
    h4 {{ font-size: 11pt; margin: 1rem 0 0.4rem; }}
    h5 {{ font-size: 10pt; margin: 0.95rem 0 0.35rem; }}
    p, li {{ margin: 0.55rem 0; }}
    ul, ol {{ padding-left: 1.25rem; }}
    strong {{ font-weight: 700; }}
    hr {{ display: none; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; font-size: 0.95em; }}
    blockquote {{ margin: 0.9rem 0; padding: 0.1rem 0 0.1rem 1rem; border-left: 3px solid var(--rule); color: var(--muted); }}
    table {{ border-collapse: collapse; width: 100%; margin: 1.2rem 0; font-size: 0.95em; }}
    th, td {{ border: 1px solid var(--rule); padding: 8px 12px; text-align: left; vertical-align: top; }}
    th {{ background: #f8f9fa; font-weight: 700; }}
  </style>
</head>
<body>
{html_body}
</body>
</html>
"""

#!/usr/bin/env python3
"""
Generate release notes/changelog from git commits and tag annotations.
Supports Conventional Commits formatting and groups changes accordingly.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys


def run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout.strip()


def parse_semver(tag: str) -> tuple[int, ...] | None:
    clean = tag[len("refs/tags/") :] if tag.startswith("refs/tags/") else tag
    m = re.match(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", clean)
    if m:
        return tuple(int(x or 0) for x in m.groups())
    return None


def get_previous_tag(resolved_tag: str, current_tag: str = "") -> str:
    clean_tag = (
        current_tag[len("refs/tags/") :]
        if current_tag.startswith("refs/tags/")
        else current_tag
    )
    cmd = ["describe", "--tags", "--abbrev=0"]
    if clean_tag:
        cmd.extend(["--exclude", clean_tag])
    cmd.append(f"{resolved_tag}^")
    try:
        tag_out = run_git(cmd)
        if tag_out == clean_tag or tag_out == resolved_tag:
            return ""
        curr_ver = parse_semver(clean_tag or resolved_tag)
        prev_ver = parse_semver(tag_out)
        if curr_ver is not None and prev_ver is not None and prev_ver >= curr_ver:
            return ""
        return tag_out
    except Exception:
        return ""


def sanitize_commit_message(msg: str) -> str:
    """Strip leading/trailing markdown backticks, quotes, and whitespace from commit messages."""
    s = msg.strip()
    while True:
        prev_len = len(s)
        s = s.strip()
        if s.startswith("```"):
            s = s[3:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip("`'\" \t")
        if len(s) == prev_len:
            break
    return s.strip()


def should_ignore_commit(msg: str) -> bool:
    """Determine whether a commit should be excluded from release notes (merge commits, empty commits)."""
    s = sanitize_commit_message(msg)
    if not s:
        return True
    # Ignore empty or symbol-only commits (e.g. "#", "...", "---")
    if all(c in "#.-_*=~ \t" for c in s):
        return True
    # Ignore accidental time/duration commits (e.g. "18m 1m")
    if re.match(r"^(\d+[smhdw]\s*)+$", s, re.IGNORECASE):
        return True
    # Ignore git merge commits
    if re.match(
        r"^merge\s+(branch|pull request|remote-tracking branch)", s, re.IGNORECASE
    ):
        return True
    return False


def classify_unprefixed_commit(desc: str) -> str:
    """Heuristically categorize non-conventional commits based on their leading verbs and keywords."""
    lower = desc.strip().lower()
    words = lower.split()
    first_word = words[0] if words else ""
    first_word_alpha = re.sub(r"[^a-z]", "", first_word)

    # Documentation
    if "readme" in lower or first_word_alpha in ["doc", "docs", "documentation"]:
        return "Documentation"

    # Bug Fixes
    if first_word_alpha in [
        "fix",
        "fixes",
        "fixed",
        "harden",
        "hardens",
        "prevent",
        "prevents",
        "resolve",
        "resolves",
        "resolved",
        "correct",
        "corrects",
        "restore",
        "restores",
        "patch",
        "patches",
        "handle",
        "handles",
        "ripristina",
    ]:
        return "Bug Fixes"

    # Performance
    if first_word_alpha in [
        "perf",
        "optimize",
        "optimization",
        "optimizations",
        "speedup",
        "cache",
        "caching",
    ]:
        return "Performance Improvements"

    # Features / Enhancements
    if first_word_alpha in [
        "add",
        "adds",
        "added",
        "implement",
        "implements",
        "implemented",
        "support",
        "supports",
        "revamp",
        "allow",
        "allows",
        "preserve",
        "preserves",
        "introduce",
        "introduces",
        "promote",
        "promotes",
        "feature",
        "improve",
        "improves",
        "improved",
        "refresh",
        "refreshes",
        "separate",
        "separates",
        "aggiorna",
    ] or lower.startswith("fix/feat"):
        return "Features"

    # Dependencies
    if (
        first_word_alpha
        in ["bump", "bumps", "dep", "deps", "dependency", "dependencies"]
        or "requirement" in lower
    ):
        return "Dependencies"

    # Maintenance & Refactoring
    if first_word_alpha in [
        "refactor",
        "refactors",
        "refactored",
        "refractoring",
        "clean",
        "cleanup",
        "chore",
        "test",
        "tests",
        "ci",
        "build",
        "style",
        "ignore",
        "drop",
        "drops",
        "remove",
        "removes",
        "extract",
        "extracts",
        "migrate",
        "verifica",
    ]:
        return "Maintenance & Refactoring"

    return "Other Changes"


def get_commits(tag: str, max_commits: int = 0) -> list[tuple[str, str]]:
    clean_tag = tag[len("refs/tags/") :] if tag.startswith("refs/tags/") else tag
    resolved_tag = clean_tag
    try:
        run_git(["rev-parse", "--verify", clean_tag])
    except Exception:
        resolved_tag = "HEAD"

    prev_ref = get_previous_tag(resolved_tag, current_tag=clean_tag)

    effective_max = max_commits
    if not prev_ref or prev_ref == clean_tag:
        commit_range = resolved_tag
        if max_commits == 0:
            effective_max = 50
    else:
        commit_range = f"{prev_ref}..{resolved_tag}"

    commits: list[tuple[str, str]] = []
    try:
        cmd = ["log", "--format=%h|%s"]
        if effective_max > 0:
            cmd.extend(["-n", str(effective_max)])
        cmd.append(commit_range)
        log_out = run_git(cmd)
        if log_out:
            for line in log_out.splitlines():
                if "|" in line:
                    h, s = line.split("|", 1)
                    if not should_ignore_commit(s):
                        commits.append((h, sanitize_commit_message(s)))
    except Exception as e:
        print(f"Error getting commits: {e}", file=sys.stderr)
    return commits


def uncapitalize_first(text: str) -> str:
    if not text:
        return text
    words = text.split(maxsplit=1)
    if words and len(words[0]) > 1 and words[0].isupper():
        return text
    return text[0].lower() + text[1:]


def categorize_commits(
    commits: list[tuple[str, str]], repo: str | None
) -> dict[str, list[str]]:
    categories: dict[str, list[str]] = {
        "Features": [],
        "Bug Fixes": [],
        "Performance Improvements": [],
        "Documentation": [],
        "Dependencies": [],
        "Maintenance & Refactoring": [],
        "Other Changes": [],
    }

    type_mapping = {
        "feat": "Features",
        "ui": "Features",
        "ux": "Features",
        "prompt": "Features",
        "fix": "Bug Fixes",
        "revert": "Bug Fixes",
        "perf": "Performance Improvements",
        "performance": "Performance Improvements",
        "docs": "Documentation",
        "dependencies": "Dependencies",
        "deps": "Dependencies",
        "chore": "Maintenance & Refactoring",
        "refactor": "Maintenance & Refactoring",
        "test": "Maintenance & Refactoring",
        "style": "Maintenance & Refactoring",
        "ci": "Maintenance & Refactoring",
        "build": "Maintenance & Refactoring",
    }

    pattern = re.compile(r"^([a-zA-Z0-9_\-]+)(?:\(([^)]+)\))?!?:\s*(.+)$")

    for h, s_raw in commits:
        s = sanitize_commit_message(s_raw)
        if should_ignore_commit(s):
            continue

        match = pattern.match(s)
        if match:
            ctype, scope, desc = match.groups()
            ctype_lower = ctype.lower()
            scope_lower = scope.lower() if scope else ""
            desc = uncapitalize_first(desc)

            if repo:
                desc = re.sub(
                    r"#(\d+)", rf"[#\1](https://github.com/{repo}/pull/\1)", desc
                )

            if (
                ctype_lower.startswith("deps")
                or ctype_lower == "dependencies"
                or "deps" in scope_lower
                or "dependencies" in scope_lower
            ):
                category = "Dependencies"
            else:
                category = type_mapping.get(ctype_lower, "Other Changes")

            link = (
                f"([`{h}`](https://github.com/{repo}/commit/{h}))" if repo else f"({h})"
            )
            if scope:
                item = f"- **{scope_lower}**: {desc} {link}"
            else:
                item = f"- {desc} {link}"

            categories[category].append(item)
        else:
            s_uncap = uncapitalize_first(s)
            category = classify_unprefixed_commit(s)
            if repo:
                s_uncap = re.sub(
                    r"#(\d+)", rf"[#\1](https://github.com/{repo}/pull/\1)", s_uncap
                )
            link = (
                f"([`{h}`](https://github.com/{repo}/commit/{h}))" if repo else f"({h})"
            )
            item = f"- {s_uncap} {link}"
            categories[category].append(item)
    return categories


CATEGORY_HEADINGS = {
    "Features": "🚀 Features",
    "Bug Fixes": "🐛 Bug Fixes",
    "Performance Improvements": "⚡ Performance",
    "Documentation": "📝 Documentation",
    "Dependencies": "📦 Dependencies",
    "Maintenance & Refactoring": "🛠️ Maintenance & Refactoring",
    "Other Changes": "Other Changes",
}


def get_repo(cli_repo: str | None = None) -> str | None:
    if cli_repo and cli_repo.strip():
        return cli_repo.strip()
    env_repo = os.environ.get("GITHUB_REPOSITORY")
    if env_repo and env_repo.strip():
        return env_repo.strip()
    try:
        remote_url = run_git(["remote", "get-url", "origin"])
        match = re.search(r"github\.com[:/]([^/]+)/([^/\.]+?)(?:\.git)?$", remote_url)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    except Exception:
        pass
    return None


def format_changelog(
    categories: dict[str, list[str]],
    repo: str | None = None,
    prev_ref: str | None = None,
    clean_tag: str = "",
    custom_body: str = "",
    collapse_maintenance: bool = True,
) -> str:
    lines: list[str] = []
    if custom_body:
        lines.append(f"{custom_body}\n")

    lines.append("## Changes\n")

    has_content = False

    primary_categories = [
        "Features",
        "Bug Fixes",
        "Performance Improvements",
        "Documentation",
        "Other Changes",
    ]
    for cat in primary_categories:
        items = categories.get(cat, [])
        if items:
            heading = CATEGORY_HEADINGS.get(cat, cat)
            lines.append(f"### {heading}")
            for item in items:
                lines.append(item)
            lines.append("")
            has_content = True

    has_primary_content = any(
        len(categories.get(cat, [])) > 0
        for cat in [
            "Features",
            "Bug Fixes",
            "Performance Improvements",
            "Documentation",
        ]
    )

    collapsible_categories = ["Dependencies", "Maintenance & Refactoring"]
    collapsible_items = {
        cat: categories.get(cat, [])
        for cat in collapsible_categories
        if categories.get(cat)
    }

    if collapsible_items:
        has_content = True
        total_internal = sum(len(items) for items in collapsible_items.values())
        if collapse_maintenance:
            dep_count = len(collapsible_items.get("Dependencies", []))
            maint_count = len(collapsible_items.get("Maintenance & Refactoring", []))
            if dep_count > 0 and maint_count > 0:
                summary_label = "Maintenance & Dependencies"
            elif dep_count > 0:
                summary_label = "Dependencies"
            else:
                summary_label = "Maintenance & Refactoring"

            unit = "change" if total_internal == 1 else "changes"
            if not has_primary_content:
                lines.append("<details open>")
                lines.append(
                    f"<summary>🛠️ <b>{summary_label}</b> ({total_internal} {unit})</summary>\n"
                )
                lines.append(
                    "*This release contains maintenance and dependency updates only.*\n"
                )
            else:
                lines.append("<details>")
                lines.append(
                    f"<summary>🛠️ <b>{summary_label}</b> ({total_internal} {unit})</summary>\n"
                )

            for cat, items in collapsible_items.items():
                heading = CATEGORY_HEADINGS.get(cat, cat)
                lines.append(f"### {heading}")
                for item in items:
                    lines.append(item)
                lines.append("")
            lines.append("</details>\n")
        else:
            for cat, items in collapsible_items.items():
                heading = CATEGORY_HEADINGS.get(cat, cat)
                lines.append(f"### {heading}")
                for item in items:
                    lines.append(item)
                lines.append("")

    if not has_content:
        lines.append("* No changes\n")

    if repo and prev_ref:
        lines.append(
            f"**Full Changelog**: https://github.com/{repo}/compare/{prev_ref}...{clean_tag}\n"
        )

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate release notes from git commits."
    )
    parser.add_argument(
        "--tag", required=True, help="The current tag/ref for the release."
    )
    parser.add_argument(
        "--custom-body",
        default="",
        help="Optional custom message to prepend to the release notes.",
    )
    parser.add_argument(
        "--highlights",
        default="",
        help="Alias for custom-body: optional highlights/summary to prepend.",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repository (owner/repo). Defaults to GITHUB_REPOSITORY env var or git remote.",
    )
    parser.add_argument(
        "--no-collapse",
        action="store_true",
        help="Disable collapsible details for dependencies and maintenance.",
    )
    parser.add_argument(
        "--max-commits",
        type=int,
        default=0,
        help="Maximum number of commits to include in changelog (0 for unlimited).",
    )
    parser.add_argument(
        "--output", required=True, help="Path to write the markdown output."
    )
    args = parser.parse_args()

    tag = args.tag

    # Ensure tags are fetched
    try:
        run_git(["fetch", "--tags", "--force"])
    except Exception:
        pass

    commits = get_commits(tag, max_commits=args.max_commits)
    repo = get_repo(args.repo)
    categories = categorize_commits(commits, repo)

    clean_tag = tag[len("refs/tags/") :] if tag.startswith("refs/tags/") else tag
    try:
        run_git(["rev-parse", "--verify", clean_tag])
        resolved_tag = clean_tag
    except Exception:
        resolved_tag = "HEAD"
    prev_ref = get_previous_tag(resolved_tag, current_tag=clean_tag)

    # Determine custom body to prepend if explicitly provided
    env_body = os.environ.get("CUSTOM_RELEASE_BODY")
    raw_custom_body = (
        args.highlights
        or (env_body.strip() if env_body and env_body.strip() else "")
        or args.custom_body
    ).strip()

    output_text = format_changelog(
        categories=categories,
        repo=repo,
        prev_ref=prev_ref,
        clean_tag=clean_tag,
        custom_body=raw_custom_body,
        collapse_maintenance=not args.no_collapse,
    )

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(output_text)

    print(f"Changelog written to {args.output}")


if __name__ == "__main__":
    main()

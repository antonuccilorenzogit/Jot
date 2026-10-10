"""Tests for scripts/generate_changelog.py"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.generate_changelog import (
    categorize_commits,
    classify_unprefixed_commit,
    format_changelog,
    get_commits,
    get_previous_tag,
    get_repo,
    main,
    run_git,
    sanitize_commit_message,
    should_ignore_commit,
    uncapitalize_first,
)


class TestGenerateChangelog(unittest.TestCase):
    def test_uncapitalize_first(self) -> None:
        self.assertEqual(uncapitalize_first(""), "")
        self.assertEqual(uncapitalize_first("Foo"), "foo")
        self.assertEqual(uncapitalize_first("bar"), "bar")
        self.assertEqual(uncapitalize_first("DPAPI test"), "DPAPI test")

    def test_categorize_commits(self) -> None:
        commits = [
            ("abc1234", "feat(UI): Add new dialog (#42)"),
            ("def5678", "fix: Fix bug in player"),
            ("ghi9012", "docs: update readme"),
            ("jkl3456", "deps: bump react"),
            ("mno7890", "chore: clean up code"),
            ("pqr1111", "random commit message (#100)"),
        ]
        categories = categorize_commits(commits, repo="owner/repo")
        self.assertEqual(len(categories["Features"]), 1)
        self.assertIn(
            "add new dialog ([#42](https://github.com/owner/repo/pull/42))",
            categories["Features"][0],
        )
        self.assertIn("owner/repo/commit/abc1234", categories["Features"][0])

        self.assertEqual(len(categories["Bug Fixes"]), 1)
        self.assertEqual(len(categories["Documentation"]), 1)
        self.assertEqual(len(categories["Dependencies"]), 1)
        self.assertEqual(len(categories["Maintenance & Refactoring"]), 1)
        self.assertEqual(len(categories["Other Changes"]), 1)
        self.assertIn(
            "[#100](https://github.com/owner/repo/pull/100)",
            categories["Other Changes"][0],
        )

    @patch("subprocess.run")
    def test_run_git_errors_replace(self, mock_run) -> None:
        mock_run.return_value.stdout = "  test output  \n"
        output = run_git(["status"])
        self.assertEqual(output, "test output")
        mock_run.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        self.assertEqual(kwargs.get("errors"), "replace")

    @patch("scripts.generate_changelog.run_git")
    def test_get_previous_tag(self, mock_run_git) -> None:
        mock_run_git.return_value = "v0.9.0"
        prev = get_previous_tag("v1.0.0", current_tag="v1.0.0")
        self.assertEqual(prev, "v0.9.0")
        mock_run_git.assert_called_once_with(
            ["describe", "--tags", "--abbrev=0", "--exclude", "v1.0.0", "v1.0.0^"]
        )

    def test_main_custom_release_body_empty_env_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "changelog.md")
            test_args = [
                "generate_changelog.py",
                "--tag",
                "v1.0.0",
                "--custom-body",
                "CLI Custom Body",
                "--output",
                output_file,
            ]

            def mock_git(args):
                if args[0] == "cat-file":
                    return "commit"
                if args[0] == "rev-parse":
                    return "v1.0.0"
                if args[0] == "describe":
                    return "v0.9.0"
                if args[0] == "log":
                    return "abc1234|feat: add foo"
                return ""

            with (
                patch.object(sys, "argv", test_args),
                patch("scripts.generate_changelog.run_git", side_effect=mock_git),
                patch.dict(
                    os.environ,
                    {"CUSTOM_RELEASE_BODY": "", "GITHUB_REPOSITORY": "owner/repo"},
                    clear=False,
                ),
            ):
                main()

            with open(output_file, encoding="utf-8") as f:
                content = f.read()

            self.assertIn("CLI Custom Body", content)
            self.assertIn(
                "**Full Changelog**: https://github.com/owner/repo/compare/v0.9.0...v1.0.0",
                content,
            )

    @patch("scripts.generate_changelog.run_git")
    def test_get_commits_git_log_command_args(self, mock_run_git) -> None:
        mock_run_git.side_effect = ["v1.0.0", "v0.9.0", "abc1234|feat: new feature"]
        commits = get_commits("v1.0.0", max_commits=10)
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0], ("abc1234", "feat: new feature"))
        log_call_args = mock_run_git.call_args_list[-1][0][0]
        self.assertEqual(
            log_call_args, ["log", "--format=%h|%s", "-n", "10", "v0.9.0..v1.0.0"]
        )
        self.assertNotIn("--", log_call_args)

    def test_main_tag_message_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "changelog.md")
            test_args = [
                "generate_changelog.py",
                "--tag",
                "v1.0.0",
                "--output",
                output_file,
            ]

            # Tag message exists but should be ignored; output starts with ## Changes
            def mock_git(args):
                if args[0] == "cat-file":
                    return "tag"
                if args[0] == "tag" and args[1] == "-l":
                    return "Custom announcement or highlights in tag"
                if args[0] == "rev-parse":
                    return "v1.0.0"
                if args[0] == "describe":
                    return "v0.9.0"
                if args[0] == "log":
                    return "abc1234|feat: add foo"
                return ""

            with (
                patch.object(sys, "argv", test_args),
                patch("scripts.generate_changelog.run_git", side_effect=mock_git),
                patch.dict(
                    os.environ, {"GITHUB_REPOSITORY": "owner/repo"}, clear=False
                ),
            ):
                main()

            with open(output_file, encoding="utf-8") as f:
                content = f.read()
            self.assertNotIn("Custom announcement or highlights in tag", content)
            self.assertTrue(content.startswith("## Changes\n\n"))

    def test_categorize_commits_deps_prefix(self) -> None:
        commits = [
            ("1111111", "deps-dev: bump ruff to 0.16.6"),
            ("2222222", "dependencies: update requests"),
        ]
        categories = categorize_commits(commits, repo="owner/repo")
        self.assertEqual(len(categories["Dependencies"]), 2)

    def test_get_repo(self) -> None:
        # CLI override takes precedence
        self.assertEqual(get_repo("cli/repo"), "cli/repo")

        # Fallback to env var
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "env/repo"}, clear=False):
            self.assertEqual(get_repo(), "env/repo")

        # Fallback to git remote
        with (
            patch.dict(os.environ, {"GITHUB_REPOSITORY": ""}, clear=False),
            patch(
                "scripts.generate_changelog.run_git",
                return_value="https://github.com/gitowner/gitrepo.git",
            ),
        ):
            self.assertEqual(get_repo(), "gitowner/gitrepo")

        # When git remote has SSH format
        with (
            patch.dict(os.environ, {"GITHUB_REPOSITORY": ""}, clear=False),
            patch(
                "scripts.generate_changelog.run_git",
                return_value="git@github.com:gitowner/sshrepo.git",
            ),
        ):
            self.assertEqual(get_repo(), "gitowner/sshrepo")

    def test_format_changelog_collapsed_details(self) -> None:
        categories = {
            "Features": ["- feat item ([`123`](https://...))"],
            "Bug Fixes": ["- fix item ([`456`](https://...))"],
            "Documentation": [],
            "Dependencies": [
                "- dep 1 ([`789`](https://...))",
                "- dep 2 ([`abc`](https://...))",
            ],
            "Maintenance & Refactoring": ["- maint 1 ([`def`](https://...))"],
            "Other Changes": [],
        }
        output = format_changelog(
            categories=categories,
            repo="owner/repo",
            prev_ref="v1.0.0",
            clean_tag="v1.1.0",
            custom_body="## 🌟 Highlights\n* Awesome update",
            collapse_maintenance=True,
        )

        self.assertIn("## 🌟 Highlights\n* Awesome update", output)
        self.assertIn("### 🚀 Features", output)
        self.assertIn("### 🐛 Bug Fixes", output)
        self.assertIn(
            "<details>\n<summary>🛠️ <b>Maintenance & Dependencies</b> (3 changes)</summary>",
            output,
        )
        self.assertIn("### 📦 Dependencies", output)
        self.assertIn("### 🛠️ Maintenance & Refactoring", output)
        self.assertIn("</details>", output)
        self.assertIn(
            "**Full Changelog**: https://github.com/owner/repo/compare/v1.0.0...v1.1.0",
            output,
        )

    def test_format_changelog_no_collapse(self) -> None:
        categories = {
            "Features": ["- feat item"],
            "Bug Fixes": [],
            "Documentation": [],
            "Dependencies": ["- dep 1"],
            "Maintenance & Refactoring": [],
            "Other Changes": [],
        }
        output = format_changelog(
            categories=categories,
            repo="owner/repo",
            prev_ref="v1.0.0",
            clean_tag="v1.1.0",
            collapse_maintenance=False,
        )

        self.assertNotIn("<details>", output)
        self.assertIn("### 📦 Dependencies", output)

    def test_sanitize_commit_message(self) -> None:
        self.assertEqual(
            sanitize_commit_message("``` fix: resolve issue ```"),
            "fix: resolve issue",
        )
        self.assertEqual(
            sanitize_commit_message("`feat: add widget`"),
            "feat: add widget",
        )
        self.assertEqual(
            sanitize_commit_message('  "chore: clean code"  '),
            "chore: clean code",
        )

    def test_should_ignore_commit(self) -> None:
        self.assertTrue(
            should_ignore_commit("Merge branch 'main' of https://github.com/...")
        )
        self.assertTrue(should_ignore_commit("Merge pull request #42 from foo/bar"))
        self.assertTrue(should_ignore_commit("#"))
        self.assertTrue(should_ignore_commit("---"))
        self.assertTrue(should_ignore_commit("   "))
        self.assertFalse(should_ignore_commit("fix: resolve bug in audio player"))

    def test_classify_unprefixed_commit(self) -> None:
        self.assertEqual(
            classify_unprefixed_commit("Fix post-review regressions"), "Bug Fixes"
        )
        self.assertEqual(
            classify_unprefixed_commit("Harden boundary revision"), "Bug Fixes"
        )
        self.assertEqual(
            classify_unprefixed_commit("Update images in README.md"), "Documentation"
        )
        self.assertEqual(classify_unprefixed_commit("Revamp app pipeline"), "Features")
        self.assertEqual(classify_unprefixed_commit("Preserve queue state"), "Features")
        self.assertEqual(
            classify_unprefixed_commit("Optimize react hot paths"),
            "Performance Improvements",
        )
        self.assertEqual(
            classify_unprefixed_commit("Bump vite from 6 to 8"), "Dependencies"
        )
        self.assertEqual(
            classify_unprefixed_commit("Clean up temp files"),
            "Maintenance & Refactoring",
        )
        self.assertEqual(
            classify_unprefixed_commit("Random unknown title"), "Other Changes"
        )

    def test_categorize_commits_perf_and_ui(self) -> None:
        commits = [
            ("1111111", "perf(webui): memoize editor extensions"),
            ("2222222", "ui: add floating TOC sidebar"),
            ("3333333", "ux: prevent prompt overflow"),
            ("4444444", "Fix post-review regressions"),
        ]
        categories = categorize_commits(commits, repo="owner/repo")
        self.assertEqual(len(categories["Performance Improvements"]), 1)
        self.assertEqual(len(categories["Features"]), 2)
        self.assertEqual(len(categories["Bug Fixes"]), 1)

    def test_format_changelog_maintenance_only_details_open(self) -> None:
        categories = {
            "Features": [],
            "Bug Fixes": [],
            "Performance Improvements": [],
            "Documentation": [],
            "Dependencies": ["- dep item"],
            "Maintenance & Refactoring": ["- chore item"],
            "Other Changes": [],
        }
        output = format_changelog(
            categories=categories,
            repo="owner/repo",
            prev_ref="v1.0.0",
            clean_tag="v1.0.1",
            collapse_maintenance=True,
        )
        self.assertIn("<details open>", output)
        self.assertIn(
            "*This release contains maintenance and dependency updates only.*", output
        )


if __name__ == "__main__":
    unittest.main()

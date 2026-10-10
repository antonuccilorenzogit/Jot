# Contributing to jot

Thank you for contributing to jot! This document outlines development setup, testing, and packaging procedures.

## Building Native Packages

To build native executable packages without using the command line, double-click the included automation scripts:

- **Windows:** `packaging/Costruisci_EXE_Windows.bat`
- **macOS:** `packaging/Costruisci_APP_Mac.command`

The WebUI is the only supported interface for releases. Legacy desktop entrypoints remain solely as compatibility aliases.

## Prerequisites

| Tool | Required version |
|------|-----------------|
| Python | 3.11 (exact — matches CI) |
| Node.js | 24 (exact — matches CI) |
| pip | bundled with Python |
| npm | bundled with Node.js |

No `.env` or API key is needed to develop or build. Keys are entered at runtime inside the app's Settings screen.

## Installation & Setup

```bash
# Install all dependencies (runtime + dev tools: ruff, pyinstaller, etc.)
python scripts/build_release.py deps --ui webui --dev

# Install git hooks (runs ruff, whitespace, YAML, and JSON checks before every commit)
pre-commit install
```

## Testing & Quality Checks

```bash
# Verify all tooling and dependencies are present
python scripts/build_release.py deps --ui webui --dev

# Run linter (ruff) + full test suite (pytest + Vitest) — skips npm install if already done
python scripts/build_release.py check --skip-npm-install
```

Run both before opening a PR. The GitHub Actions CI workflow runs these exact commands.

## Build Commands

```bash
# Windows (creates standalone installer exe)
python scripts/build_release.py build --target windows --ui webui --install-deps --dev-deps

# macOS (creates standalone DMG)
python scripts/build_release.py build --target macos --ui webui --install-deps --dev-deps
```

## Repository Structure

| Path | Description |
|------|-------------|
| `jot/` | Python package, pipeline orchestration, and PyWebView backend |
| `webui/` | React + TypeScript frontend (Vite, Tailwind CSS, TipTap) |
| `scripts/build_release.py` | Authoritative automation entrypoint (lint, test, build, packaging) |
| `tests/` | Python unittest suite |
| `launchers/` | PyInstaller desktop entrypoint (`jot_WebUI.pyw`) |
| `packaging/` | Platform-specific installer scripts (Inno Setup for Windows, create-dmg for macOS) |
| `docs/` | Developer architecture, IPC bridge protocol, and pipeline documentation |

## Pull Request Guidelines

- All automated checks must pass: `python scripts/build_release.py check --skip-npm-install` exits 0.
- Keep commits focused: one logical change per PR. Follow Conventional Commits format (`feat:`, `fix:`, `refactor:`, `chore:`).
- When adding new features or fixing bugs, add corresponding unit or DOM tests.
- Do not weaken or delete existing tests without justification.

## Developer Documentation

- [docs/architecture.md](docs/architecture.md) — Python/React module map, runtime flow, and threading model.
- [docs/pipeline.md](docs/pipeline.md) — Pipeline phases, retry mechanisms, and Gemini model fallback chain.
- [docs/session_model.md](docs/session_model.md) — On-disk session layout and `session.json` schema.
- [docs/bridge_protocol.md](docs/bridge_protocol.md) — Python ↔ React IPC event and API contracts.

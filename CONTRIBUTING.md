# Contributing to HawkTranscriber

Thank you for considering contributing! This document explains how to set up a
development environment, the project's conventions, and how to submit changes.

## Getting started

1. Fork the repository and clone it locally.
2. Install Python 3.11 or newer (check *"Add python.exe to PATH"* during setup).
3. Install FFmpeg (see the README for instructions).
4. Set up the virtual environment and install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

5. Run the tests to confirm everything works:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Development workflow

1. Create a feature branch from `main`.
2. Make your changes.
3. Run the test suite locally.
4. Open a pull request describing the change.

## Pull request guidelines

- **Keep changes focused.** One PR should address one concern. If you are fixing a bug,
  reference the issue number in the description.
- **Write clear commit messages.** Explain *why* a change was made, not just *what*.
- **Run the tests.** All tests must pass before a PR is merged.
- **Update documentation.** If you change behavior, update the relevant docs
  (`README.md`, `docs/DEVELOPMENT.md`, `docs/TROUBLESHOOTING.md`).

## Code style

- Python 3.11+ with type hints throughout.
- The frontend is vanilla JavaScript — no framework, no build step.
- CSS uses a lightweight custom system with CSS variables for theming.
- Avoid introducing new dependencies without discussing it first.

## Reporting issues

When reporting a bug, please include:

- HawkTranscriber version
- Operating system and Python version
- FFmpeg version
- Steps to reproduce
- Expected vs. actual behavior
- Any relevant log excerpts from `data/logs/whisperdesk.log`

## Licensing

By contributing, you agree that your contributions will be licensed under the same
license as the project. **Note:** the project does not yet have a license file.
This will be resolved before the repository is published.
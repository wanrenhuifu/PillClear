#!/usr/bin/env python3
"""Install the pre-commit hook that enforces AGENTS.md「改动后的最小验证」.

``.git/hooks/`` is not version-controlled, so run this once after cloning:

    python scripts/install_hooks.py

The installed hook delegates to ``scripts/pre_commit_check.py`` (versioned),
so hook logic stays reviewable and up to date on every pull.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

HOOK_BODY = """#!/bin/sh
# PillClear pre-commit: AGENTS.md minimal post-change validation.
# Runs affected pytest files + ruff check app tests; failure blocks the commit.
# Keep ASCII-only: sh/cmd codepage differences corrupt non-ASCII hook text.
# Installed by scripts/install_hooks.py; logic lives in scripts/pre_commit_check.py.
exec python scripts/pre_commit_check.py "$@"
"""


def main() -> int:
    hooks_dir = REPO_ROOT / ".git" / "hooks"
    if not hooks_dir.parent.is_dir():
        print("[install-hooks] ERROR: .git not found; run this from the repo working tree.")
        return 1
    hooks_dir.mkdir(exist_ok=True)

    hook_path = hooks_dir / "pre-commit"
    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8")
        if "pre_commit_check.py" in existing:
            print(f"[install-hooks] Already installed: {hook_path}")
            return 0
        print(f"[install-hooks] ERROR: {hook_path} exists and is not ours; refusing to overwrite.")
        return 1

    hook_path.write_text(HOOK_BODY, encoding="utf-8", newline="\n")
    hook_path.chmod(0o755)
    print(f"[install-hooks] Installed: {hook_path}")
    print("[install-hooks] Every commit now runs: affected pytest files + ruff check app tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())

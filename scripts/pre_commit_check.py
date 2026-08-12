#!/usr/bin/env python3
"""Pre-delivery minimal validation (AGENTS.md「改动后的最小验证」).

Runs before every commit as the git pre-commit hook:

1. pytest on test files affected by the staged change (fallback: full suite);
2. ``ruff check app tests``.

Any step failing blocks the commit. Commands and expected results come
directly from AGENTS.md conventions; no new tooling is introduced.
Only stdlib is used, so the hook works in any Python env that runs the tests.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _staged_files() -> list[str]:
    """Return staged file paths relative to the repo root (diff includes renames)."""
    try:
        raw = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    # git -z separates entries with NUL; a trailing rename payload also uses NUL
    return [p for p in raw.split("\0") if p]


def _affected_test_files(staged: list[str]) -> list[str]:
    """Map staged paths to affected test files (deterministic, no guessing).

    Convention verified against tests/: app/<pkg>/<mod>.py is covered by
    tests/test_<pkg>_<mod>.py or tests/test_<mod>.py; candidates that do not
    exist are dropped, never invented. Unmappable changes fall back to the
    full suite in main().
    """
    affected: set[str] = set()
    for path in staged:
        norm = path.replace("\\", "/")
        if norm.startswith("tests/") and norm.endswith(".py"):
            affected.add(norm)
        elif norm.startswith("app/") and norm.endswith(".py"):
            parts = Path(norm).parts  # ('app', pkg?, module.py)
            module = parts[-1][:-3]
            candidates = []
            if len(parts) == 3:
                candidates.append(f"tests/test_{parts[1]}_{module}.py")
            candidates.append(f"tests/test_{module}.py")
            affected.update(c for c in candidates if (REPO_ROOT / c).is_file())
    return sorted(affected)


def _run(label: str, cmd: list[str]) -> bool:
    print(f"[pre-commit] {label}: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=REPO_ROOT)
    if proc.returncode != 0:
        print(f"[pre-commit] FAILED: {label} (exit {proc.returncode}). Commit blocked.")
        return False
    print(f"[pre-commit] PASSED: {label}")
    return True


def main() -> int:
    staged = _staged_files()
    affected = _affected_test_files(staged)

    if affected:
        targets = affected
        label = f"affected tests ({len(targets)} file(s))"
    else:
        # Nothing mappable (docs-only change, no app/tests mapping, or hooks run
        # outside git): fall back to the full suite per AGENTS.md baseline 405.
        targets = ["tests"]
        label = "full test suite (no affected test file mapped)"

    if not _run(label, [sys.executable, "-m", "pytest", *targets]):
        print("[pre-commit] Fix the failures, then commit again.")
        print("[pre-commit] Emergency bypass (takes responsibility): git commit --no-verify")
        return 1

    if not _run("ruff check app tests", [sys.executable, "-m", "ruff", "check", "app", "tests"]):
        print("[pre-commit] Fix lint errors, then commit again.")
        print("[pre-commit] Emergency bypass (takes responsibility): git commit --no-verify")
        return 1

    print("[pre-commit] Minimal validation passed (AGENTS.md 改动后的最小验证).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import subprocess
from pathlib import Path


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=False,
    )


def is_git_repo(repo_root: Path) -> bool:
    proc = _run_git(repo_root, "rev-parse", "--is-inside-work-tree")
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def assert_not_tracked(repo_root: Path, path: Path) -> None:
    if not is_git_repo(repo_root):
        return
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return
    proc = _run_git(repo_root, "ls-files", "--error-unmatch", str(rel))
    if proc.returncode == 0:
        raise RuntimeError(f"Refusing to run: {rel} is tracked by git (must be ignored).")


def panic_check_runtime_secrets(repo_root: Path, runtime_root: Path) -> None:
    # Refuse to run if anything under .tako/ is tracked.
    if not is_git_repo(repo_root):
        return
    proc = _run_git(repo_root, "ls-files", str(runtime_root.relative_to(repo_root)))
    if proc.returncode == 0 and proc.stdout.strip():
        raise RuntimeError("Refusing to run: files under .tako/ are tracked by git.")


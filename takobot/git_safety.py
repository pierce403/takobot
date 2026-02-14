from __future__ import annotations

from dataclasses import dataclass
import subprocess
from pathlib import Path


def _run_git(repo_root: Path, *args: str, timeout_s: float = 15.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_s,
        )
    except Exception:
        return subprocess.CompletedProcess(args=["git", *args], returncode=124, stdout="", stderr="git invocation failed")


@dataclass(frozen=True)
class GitAutoCommitResult:
    ok: bool
    committed: bool
    summary: str
    commit: str = ""


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


def auto_commit_pending(repo_root: Path, *, message: str) -> GitAutoCommitResult:
    if not is_git_repo(repo_root):
        return GitAutoCommitResult(False, False, "auto-commit skipped: not a git repo")

    status = _run_git(repo_root, "status", "--porcelain")
    if status.returncode != 0:
        detail = " ".join(status.stderr.strip().split()) or f"exit={status.returncode}"
        return GitAutoCommitResult(False, False, f"auto-commit status failed: {detail}")
    if not status.stdout.strip():
        return GitAutoCommitResult(True, False, "no pending changes")

    add = _run_git(repo_root, "add", "-A")
    if add.returncode != 0:
        detail = " ".join(add.stderr.strip().split()) or f"exit={add.returncode}"
        return GitAutoCommitResult(False, False, f"auto-commit add failed: {detail}")

    staged = _run_git(repo_root, "diff", "--cached", "--quiet")
    if staged.returncode == 0:
        return GitAutoCommitResult(True, False, "no staged changes after add")
    if staged.returncode not in {1}:
        detail = " ".join(staged.stderr.strip().split()) or f"exit={staged.returncode}"
        return GitAutoCommitResult(False, False, f"auto-commit staged-diff failed: {detail}")

    commit = _run_git(repo_root, "commit", "-m", message)
    if commit.returncode != 0:
        detail = " ".join(commit.stderr.strip().split()) or "commit failed"
        if "Author identity unknown" in detail:
            detail = "git user.name/user.email are not configured"
        return GitAutoCommitResult(False, False, f"auto-commit failed: {detail}")

    head = _run_git(repo_root, "rev-parse", "--short", "HEAD")
    sha = head.stdout.strip() if head.returncode == 0 else ""
    return GitAutoCommitResult(True, True, "auto-commit created", commit=sha)

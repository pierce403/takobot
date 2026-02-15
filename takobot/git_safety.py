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


def git_identity_status(repo_root: Path) -> tuple[bool, str]:
    if not is_git_repo(repo_root):
        return True, "git repo not initialized"

    name_proc = _run_git(repo_root, "config", "--get", "user.name")
    email_proc = _run_git(repo_root, "config", "--get", "user.email")
    name = name_proc.stdout.strip() if name_proc.returncode == 0 else ""
    email = email_proc.stdout.strip() if email_proc.returncode == 0 else ""

    if name and email:
        return True, f"{name} <{email}>"
    if not name and not email:
        return False, "git user.name/user.email are not configured"
    if not name:
        return False, "git user.name is not configured"
    return False, "git user.email is not configured"


def _ensure_local_git_identity(repo_root: Path) -> tuple[bool, str, bool]:
    ok, detail = git_identity_status(repo_root)
    if ok:
        return True, detail, False
    set_name = _run_git(repo_root, "config", "user.name", "Takobot")
    if set_name.returncode != 0:
        err = " ".join(set_name.stderr.strip().split()) or f"exit={set_name.returncode}"
        return False, f"failed to set local git user.name: {err}", False
    set_email = _run_git(repo_root, "config", "user.email", "takobot@local")
    if set_email.returncode != 0:
        err = " ".join(set_email.stderr.strip().split()) or f"exit={set_email.returncode}"
        return False, f"failed to set local git user.email: {err}", False
    ok2, detail2 = git_identity_status(repo_root)
    return ok2, detail2, True


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
        detail_lower = detail.lower()
        if "author identity unknown" in detail_lower or "unable to auto-detect email address" in detail_lower:
            ensured, ensured_detail, changed = _ensure_local_git_identity(repo_root)
            if not ensured:
                return GitAutoCommitResult(False, False, f"auto-commit failed: {ensured_detail}")
            retry = _run_git(repo_root, "commit", "-m", message)
            if retry.returncode != 0:
                retry_detail = " ".join(retry.stderr.strip().split()) or "commit failed"
                return GitAutoCommitResult(False, False, f"auto-commit failed: {retry_detail}")
            post_retry_status = _run_git(repo_root, "status", "--porcelain")
            if post_retry_status.returncode != 0:
                detail_status = " ".join(post_retry_status.stderr.strip().split()) or f"exit={post_retry_status.returncode}"
                return GitAutoCommitResult(False, False, f"auto-commit verify failed: {detail_status}")
            if post_retry_status.stdout.strip():
                return GitAutoCommitResult(False, False, "auto-commit verify failed: pending changes remain after commit")
            head = _run_git(repo_root, "rev-parse", "--short", "HEAD")
            sha = head.stdout.strip() if head.returncode == 0 else ""
            summary = "auto-commit created"
            if changed:
                summary = f"auto-commit created (git identity auto-configured: {ensured_detail})"
            return GitAutoCommitResult(True, True, summary, commit=sha)
        return GitAutoCommitResult(False, False, f"auto-commit failed: {detail}")

    post_status = _run_git(repo_root, "status", "--porcelain")
    if post_status.returncode != 0:
        detail_status = " ".join(post_status.stderr.strip().split()) or f"exit={post_status.returncode}"
        return GitAutoCommitResult(False, False, f"auto-commit verify failed: {detail_status}")
    if post_status.stdout.strip():
        return GitAutoCommitResult(False, False, "auto-commit verify failed: pending changes remain after commit")

    head = _run_git(repo_root, "rev-parse", "--short", "HEAD")
    sha = head.stdout.strip() if head.returncode == 0 else ""
    return GitAutoCommitResult(True, True, "auto-commit created", commit=sha)

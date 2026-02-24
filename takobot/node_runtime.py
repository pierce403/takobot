from __future__ import annotations

import contextlib
from dataclasses import dataclass
import os
import shlex
import shutil
import subprocess
import tarfile
from pathlib import Path
from urllib import request as urllib_request

from .paths import ensure_runtime_dirs, runtime_paths


NVM_VERSION = "v0.40.1"
NODE_RUNTIME_MIN_MAJOR = 22


@dataclass(frozen=True)
class WorkspaceNodeRuntime:
    ok: bool
    detail: str
    env: dict[str, str]
    node_bin_dir: Path | None
    npm_executable: str | None
    using_workspace_node: bool


def ensure_workspace_node_runtime(
    *,
    min_major: int = NODE_RUNTIME_MIN_MAJOR,
    require_npm: bool = True,
) -> WorkspaceNodeRuntime:
    paths = ensure_runtime_dirs(runtime_paths())
    tmp_dir = paths.tmp_dir

    env = os.environ.copy()
    tmp_value = str(tmp_dir)
    env["TMPDIR"] = tmp_value
    env["TMP"] = tmp_value
    env["TEMP"] = tmp_value

    node_bin_dir = workspace_node_bin_dir(min_major=min_major)
    system_node = shutil.which("node")
    system_npm = shutil.which("npm")
    system_node_compatible = node_path_meets_min_major(system_node, min_major=min_major)

    need_workspace_node = node_bin_dir is None and (
        (not system_node_compatible) or (require_npm and not system_npm)
    )
    if need_workspace_node:
        ok, detail = install_workspace_nvm_node_lts(tmp_dir=tmp_dir, min_major=min_major)
        if not ok:
            return WorkspaceNodeRuntime(
                ok=False,
                detail=detail,
                env=env,
                node_bin_dir=None,
                npm_executable=None,
                using_workspace_node=False,
            )
        node_bin_dir = workspace_node_bin_dir(min_major=min_major)

    if node_bin_dir is not None:
        current_path = env.get("PATH", "")
        env["PATH"] = f"{node_bin_dir}{os.pathsep}{current_path}" if current_path else str(node_bin_dir)
        env["NVM_DIR"] = str(workspace_nvm_dir())

    npm_exec = workspace_npm_executable(node_bin_dir=node_bin_dir, min_major=min_major)
    if not npm_exec and system_node_compatible:
        npm_exec = system_npm
    if require_npm and not npm_exec:
        return WorkspaceNodeRuntime(
            ok=False,
            detail="npm is unavailable after node runtime bootstrap",
            env=env,
            node_bin_dir=node_bin_dir,
            npm_executable=None,
            using_workspace_node=node_bin_dir is not None,
        )

    if node_bin_dir is not None:
        detail = f"workspace-local node runtime ready ({node_bin_dir})"
    elif system_node_compatible:
        detail = f"system node runtime is compatible ({system_node})"
    else:
        detail = f"compatible node runtime missing (requires node >= {min_major})"

    return WorkspaceNodeRuntime(
        ok=bool(node_bin_dir is not None or system_node_compatible),
        detail=detail,
        env=env,
        node_bin_dir=node_bin_dir,
        npm_executable=npm_exec,
        using_workspace_node=node_bin_dir is not None,
    )


def workspace_nvm_dir() -> Path:
    paths = ensure_runtime_dirs(runtime_paths())
    return paths.root / "nvm"


def workspace_node_bin_dir(*, min_major: int = NODE_RUNTIME_MIN_MAJOR) -> Path | None:
    versions_dir = workspace_nvm_dir() / "versions" / "node"
    return latest_node_bin_dir(versions_dir=versions_dir, min_major=min_major)


def latest_node_bin_dir(*, versions_dir: Path, min_major: int = NODE_RUNTIME_MIN_MAJOR) -> Path | None:
    if not versions_dir.exists() or not versions_dir.is_dir():
        return None
    node_name = "node.exe" if os.name == "nt" else "node"
    candidates: list[tuple[tuple[int, int, int], Path]] = []
    for child in versions_dir.iterdir():
        if not child.is_dir():
            continue
        version_key = _node_version_sort_key(child.name)
        if version_key is None or version_key[0] < min_major:
            continue
        bin_dir = child / "bin"
        if not (bin_dir / node_name).exists():
            continue
        candidates.append((version_key, bin_dir))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def workspace_npm_executable(
    *,
    node_bin_dir: Path | None = None,
    min_major: int = NODE_RUNTIME_MIN_MAJOR,
) -> str | None:
    bin_dir = node_bin_dir or workspace_node_bin_dir(min_major=min_major)
    if bin_dir is None:
        return None
    names = ("npm.cmd", "npm") if os.name == "nt" else ("npm", "npm.cmd")
    for name in names:
        candidate = bin_dir / name
        if candidate.exists():
            return str(candidate)
    return None


def install_workspace_nvm_node_lts(*, tmp_dir: Path, min_major: int = NODE_RUNTIME_MIN_MAJOR) -> tuple[bool, str]:
    nvm_dir = workspace_nvm_dir()
    nvm_sh = nvm_dir / "nvm.sh"
    if not nvm_sh.exists():
        ok, detail = download_workspace_nvm(tmp_dir=tmp_dir, nvm_dir=nvm_dir)
        if not ok:
            return False, detail

    bash_path = shutil.which("bash")
    if not bash_path:
        return False, "bash is required to bootstrap workspace-local nvm/node"

    env = os.environ.copy()
    tmp_value = str(tmp_dir)
    env["TMPDIR"] = tmp_value
    env["TMP"] = tmp_value
    env["TEMP"] = tmp_value

    script = (
        "set -euo pipefail; "
        f"export NVM_DIR={shlex.quote(str(nvm_dir))}; "
        "source \"$NVM_DIR/nvm.sh\"; "
        "nvm install --lts >/dev/null; "
        "nvm use --lts >/dev/null"
    )
    proc = subprocess.run(
        [bash_path, "-lc", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=900,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit={proc.returncode}"
        return False, f"workspace-local nvm/node install failed: {summarize_error_text(detail)}"

    node_bin_dir = workspace_node_bin_dir(min_major=min_major)
    if node_bin_dir is None:
        return False, "workspace-local nvm completed but compatible node binary was not found under `.tako/nvm`"
    return True, f"workspace-local node runtime ready ({node_bin_dir})"


def download_workspace_nvm(*, tmp_dir: Path, nvm_dir: Path) -> tuple[bool, str]:
    archive_name = f"nvm-{NVM_VERSION.lstrip('v')}.tar.gz"
    archive_path = tmp_dir / archive_name
    unpack_dir = tmp_dir / f"nvm-{NVM_VERSION.lstrip('v')}"
    url = f"https://github.com/nvm-sh/nvm/archive/refs/tags/{NVM_VERSION}.tar.gz"

    with contextlib.suppress(Exception):
        archive_path.unlink(missing_ok=True)
    with contextlib.suppress(Exception):
        if unpack_dir.exists():
            shutil.rmtree(unpack_dir)

    try:
        with urllib_request.urlopen(url, timeout=60) as response:
            archive_path.write_bytes(response.read())
    except Exception as exc:  # noqa: BLE001
        return False, f"failed to download nvm archive: {summarize_error_text(str(exc))}"

    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(tmp_dir)
    except Exception as exc:  # noqa: BLE001
        return False, f"failed to unpack nvm archive: {summarize_error_text(str(exc))}"

    if not unpack_dir.exists():
        return False, f"unpacked nvm directory missing: {unpack_dir}"

    with contextlib.suppress(Exception):
        if nvm_dir.exists():
            shutil.rmtree(nvm_dir)
    try:
        shutil.move(str(unpack_dir), str(nvm_dir))
    except Exception as exc:  # noqa: BLE001
        return False, f"failed to place nvm under workspace runtime: {summarize_error_text(str(exc))}"
    return True, f"workspace-local nvm ready ({nvm_dir})"


def node_path_meets_min_major(node_path: str | None, *, min_major: int = NODE_RUNTIME_MIN_MAJOR) -> bool:
    if not node_path:
        return False
    try:
        proc = subprocess.run(
            [node_path, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=4.0,
        )
    except Exception:
        return False
    raw = (proc.stdout or proc.stderr or "").strip()
    major = node_major_from_version(raw)
    return major is not None and major >= min_major


def node_major_from_version(raw: str) -> int | None:
    cleaned = (raw or "").strip().lower()
    if cleaned.startswith("v"):
        cleaned = cleaned[1:]
    token = cleaned.split(".", 1)[0].strip()
    if not token.isdigit():
        return None
    return int(token)


def summarize_error_text(value: str, limit: int = 220) -> str:
    text = " ".join((value or "").split())
    if not text:
        return "no details available"
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _node_version_sort_key(raw: str) -> tuple[int, int, int] | None:
    value = str(raw).strip()
    if value.startswith("v"):
        value = value[1:]
    if not value:
        return None
    parts = value.split(".")
    numbers: list[int] = []
    for part in parts[:3]:
        token = part.strip()
        if not token.isdigit():
            return None
        numbers.append(int(token))
    while len(numbers) < 3:
        numbers.append(0)
    return numbers[0], numbers[1], numbers[2]

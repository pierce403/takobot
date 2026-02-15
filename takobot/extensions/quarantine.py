from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tarfile
import urllib.parse
from urllib.request import Request, urlopen
import zipfile

from .model import QuarantineProvenance


FETCH_TIMEOUT_S = 25.0


_ARCHIVE_SUFFIXES = (".zip", ".tar.gz", ".tgz")


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _safe_member_path(name: str) -> Path | None:
    # Normalize and reject traversal/absolute paths.
    if not name:
        return None
    name = name.replace("\\", "/")
    if name.startswith("/") or name.startswith("~"):
        return None
    parts = [p for p in name.split("/") if p and p != "."]
    if any(p == ".." for p in parts):
        return None
    return Path(*parts)


def _looks_like_archive(url: str, content_type: str) -> bool:
    lowered = url.lower()
    if any(lowered.endswith(suffix) for suffix in _ARCHIVE_SUFFIXES):
        return True
    ct = (content_type or "").lower()
    return any(token in ct for token in ("zip", "tar", "gzip"))


def _default_filename(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        name = os.path.basename(parsed.path)
        if name:
            return name
    except Exception:  # noqa: BLE001
        pass
    return "download.bin"


def _make_quarantine_id() -> str:
    # Deterministic IDs aren't required; this is runtime-only.
    import secrets
    import time

    return f"q-{int(time.time())}-{secrets.token_hex(4)}"


class QuarantineError(RuntimeError):
    pass


def fetch_to_quarantine(
    url: str,
    *,
    quarantine_root: Path,
    max_bytes: int,
    allowlist_domains: list[str] | None,
) -> tuple[Path, QuarantineProvenance]:
    target = (url or "").strip()
    if not target:
        raise QuarantineError("missing URL")

    parsed = urllib.parse.urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise QuarantineError("URL must be http(s) with a host")
    if parsed.scheme != "https":
        raise QuarantineError("non-HTTPS downloads are disabled by policy")

    host = parsed.netloc.split("@")[-1]
    if allowlist_domains:
        ok = any(host == dom or host.endswith("." + dom) for dom in allowlist_domains)
        if not ok:
            raise QuarantineError(f"domain not allowed by policy: {host}")

    quarantine_id = _make_quarantine_id()
    qdir = quarantine_root / quarantine_id
    files_dir = qdir / "files"
    qdir.mkdir(parents=True, exist_ok=True)
    files_dir.mkdir(parents=True, exist_ok=True)

    req = Request(
        target,
        headers={
            "User-Agent": "tako/0.1 (+https://tako.bot)",
            "Accept": "*/*",
        },
        method="GET",
    )

    try:
        with urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:
            final_url = resp.geturl() or target
            content_type = resp.headers.get("Content-Type") or ""
            raw = resp.read(max_bytes + 1)
    except Exception as exc:  # noqa: BLE001
        raise QuarantineError(f"download failed: {exc}") from exc

    if len(raw) > max_bytes:
        raise QuarantineError(f"download too large (> {max_bytes} bytes)")

    sha256 = _sha256_bytes(raw)
    filename = _default_filename(final_url)
    archive_path = qdir / filename
    archive_path.write_bytes(raw)

    provenance = QuarantineProvenance(
        source_url=target,
        fetched_at=QuarantineProvenance.now_iso(),
        final_url=final_url,
        content_type=content_type,
        sha256=sha256,
        bytes=len(raw),
    )

    if _looks_like_archive(final_url, content_type):
        _extract_archive(archive_path, files_dir)
    else:
        safe_name = _safe_member_path(filename) or Path("download.bin")
        (files_dir / safe_name).parent.mkdir(parents=True, exist_ok=True)
        (files_dir / safe_name).write_bytes(raw)

    # Write provenance record for offline review.
    (qdir / "provenance.txt").write_text(
        "\n".join(
            [
                f"source_url={provenance.source_url}",
                f"final_url={provenance.final_url}",
                f"fetched_at={provenance.fetched_at}",
                f"content_type={provenance.content_type}",
                f"bytes={provenance.bytes}",
                f"sha256={provenance.sha256}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    return qdir, provenance


def _extract_archive(archive_path: Path, out_dir: Path) -> None:
    name = archive_path.name.lower()
    if name.endswith(".zip"):
        _extract_zip(archive_path, out_dir)
        return
    if name.endswith(".tar.gz") or name.endswith(".tgz") or name.endswith(".tar"):
        _extract_tar(archive_path, out_dir)
        return

    # Best-effort: try zip then tar.
    try:
        _extract_zip(archive_path, out_dir)
        return
    except Exception:  # noqa: BLE001
        pass
    _extract_tar(archive_path, out_dir)


def _extract_zip(path: Path, out_dir: Path) -> None:
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            rel = _safe_member_path(info.filename)
            if rel is None:
                continue
            if info.is_dir():
                (out_dir / rel).mkdir(parents=True, exist_ok=True)
                continue
            # Reject obvious executable permission bits (coarse; still allow .py etc).
            # This is not a security boundary; analysis + enablement gates are.
            data = zf.read(info)
            target = out_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


def _extract_tar(path: Path, out_dir: Path) -> None:
    mode = "r:gz" if path.name.lower().endswith((".tar.gz", ".tgz")) else "r:*"
    with tarfile.open(path, mode) as tf:
        for member in tf.getmembers():
            rel = _safe_member_path(member.name)
            if rel is None:
                continue
            if member.issym() or member.islnk():
                continue
            if member.isdir():
                (out_dir / rel).mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            handle = tf.extractfile(member)
            if handle is None:
                continue
            data = handle.read()
            target = out_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

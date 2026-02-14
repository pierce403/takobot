from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator


@contextmanager
def instance_lock(lock_path: Path) -> Iterator[IO[str]]:
    """Acquire an exclusive, non-blocking instance lock.

    This prevents multiple `tako run` processes from using the same `.tako/` state.
    """

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        try:
            import fcntl  # type: ignore

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ModuleNotFoundError:
            raise RuntimeError("Instance locks require fcntl (not available on this platform).")
        except OSError as exc:
            raise RuntimeError(f"Another Tako instance is already running (lock: {lock_path}).") from exc
        yield handle
    finally:
        try:
            import fcntl  # type: ignore

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        handle.close()


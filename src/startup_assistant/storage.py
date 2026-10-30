"""Shared file helpers for the JSON-backed stores."""

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock

LOCK_TIMEOUT_SECONDS = 10


@contextmanager
def locked(path: Path | None) -> Iterator[None]:
    """Hold an exclusive cross-process lock for read-modify-write of `path`.

    The lock file sits next to `path` (`<name>.lock`). Plain reads don't need it, because
    writes go through atomic_write_text. A path of None (in-memory test fakes) takes no lock.
    """
    if path is None:
        yield
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock", timeout=LOCK_TIMEOUT_SECONDS):
        yield


def atomic_write_text(path: Path, text: str) -> None:
    """Write text to path via a temp file in the same dir, so readers never see a partial file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise

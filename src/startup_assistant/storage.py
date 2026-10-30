"""Shared file helpers for the JSON-backed stores."""

import os
import tempfile
from pathlib import Path


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

"""Versioned campaign briefs, stored as JSON."""

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from startup_assistant.contracts import BriefDraft, BriefRecord


class BriefsFile(BaseModel):
    records: list[BriefRecord] = []


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class BriefStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> BriefsFile:
        if not self.path.exists():
            return BriefsFile()
        return BriefsFile.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(
        self,
        draft: BriefDraft,
        markdown: str,
        kind: str,
        revises: int | None,
        knowledge_version: int,
        request: str,
    ) -> BriefRecord:
        data = self._load()
        record = BriefRecord(
            version=len(data.records) + 1,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            kind=kind,
            revises=revises,
            knowledge_version=knowledge_version,
            request=request,
            draft=draft,
            markdown=markdown,
        )
        data.records.append(record)
        _atomic_write(self.path, data.model_dump_json(indent=2))
        return record

    def latest(self) -> BriefRecord | None:
        records = self._load().records
        return records[-1] if records else None

    def get(self, version: int) -> BriefRecord | None:
        return next((r for r in self._load().records if r.version == version), None)

    def list(self) -> list[BriefRecord]:
        return list(self._load().records)

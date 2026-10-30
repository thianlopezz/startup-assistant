"""Versioned campaign briefs, stored as JSON."""

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from startup_assistant.contracts import BriefDraft, BriefRecord
from startup_assistant.storage import atomic_write_text


class BriefsFile(BaseModel):
    records: list[BriefRecord] = []


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
        atomic_write_text(self.path, data.model_dump_json(indent=2))
        return record

    def latest(self) -> BriefRecord | None:
        records = self._load().records
        return records[-1] if records else None

    def get(self, version: int) -> BriefRecord | None:
        return next((r for r in self._load().records if r.version == version), None)

    def list(self) -> list[BriefRecord]:
        return list(self._load().records)

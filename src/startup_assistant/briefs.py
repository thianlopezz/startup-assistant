"""Versioned campaign briefs, stored as JSON, filed under named campaigns.

Each campaign numbers its own versions (v1, v2, ...). Campaign names match case-insensitively,
ignoring surrounding whitespace; the name used on a campaign's first save is its display name.
"""

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from startup_assistant.contracts import DEFAULT_CAMPAIGN, BriefDraft, BriefRecord
from startup_assistant.storage import atomic_write_text

__all__ = ["DEFAULT_CAMPAIGN", "BriefStore", "BriefsFile", "campaign_key"]


def campaign_key(name: str) -> str:
    """What two campaign names must share to be the same campaign."""
    return name.strip().casefold()


class BriefsFile(BaseModel):
    records: list[BriefRecord] = []


class BriefStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> BriefsFile:
        if not self.path.exists():
            return BriefsFile()
        return BriefsFile.model_validate_json(self.path.read_text(encoding="utf-8"))

    def _write(self, data: BriefsFile) -> None:
        atomic_write_text(self.path, data.model_dump_json(indent=2))

    @staticmethod
    def _in(records: list[BriefRecord], campaign: str) -> list[BriefRecord]:
        key = campaign_key(campaign)
        return [r for r in records if campaign_key(r.campaign) == key]

    def save(
        self,
        draft: BriefDraft,
        markdown: str,
        kind: str,
        revises: int | None,
        knowledge_version: int,
        request: str,
        campaign: str = DEFAULT_CAMPAIGN,
    ) -> BriefRecord:
        """Save the next version in `campaign`. Raises ValueError if `revises` names a version
        that campaign doesn't have."""
        data = self._load()
        name = campaign.strip() or DEFAULT_CAMPAIGN
        existing = self._in(data.records, name)
        if existing:
            name = existing[0].campaign  # keep the display name from the first save
        if revises is not None and not any(r.version == revises for r in existing):
            raise ValueError(f'Campaign "{name}" has no brief v{revises} to revise.')
        record = BriefRecord(
            version=len(existing) + 1,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            kind=kind,
            revises=revises,
            knowledge_version=knowledge_version,
            request=request,
            draft=draft,
            markdown=markdown,
            campaign=name,
        )
        data.records.append(record)
        self._write(data)
        return record

    def latest(self, campaign: str | None = None) -> BriefRecord | None:
        """The most recently saved brief in `campaign`, or in any campaign when None."""
        records = self.list(campaign)
        return records[-1] if records else None

    def get(self, version: int, campaign: str = DEFAULT_CAMPAIGN) -> BriefRecord | None:
        return next((r for r in self.list(campaign) if r.version == version), None)

    def list(self, campaign: str | None = None) -> list[BriefRecord]:
        """Records in save order; all campaigns when `campaign` is None."""
        records = self._load().records
        return list(records) if campaign is None else self._in(records, campaign)

    def campaigns(self) -> list[str]:
        """Campaign display names in order of first save."""
        seen: dict[str, str] = {}
        for r in self._load().records:
            seen.setdefault(campaign_key(r.campaign), r.campaign)
        return list(seen.values())

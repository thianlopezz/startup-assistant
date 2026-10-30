"""In-memory stand-ins for Track A's stores, matching the stub signatures exactly.

Track B tests use these so they don't depend on knowledge.py / briefs.py being implemented.
"""

from datetime import datetime, timezone
from pathlib import Path

from startup_assistant.contracts import BriefDraft, BriefRecord, KnowledgeUpdate
from startup_assistant.seed import SEED_MARKETING_NOTES, SEED_PROFILE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FakeKnowledgeStore:
    def __init__(self, path: Path | None = None):
        self.path = path
        self._updates: list[KnowledgeUpdate] = []

    @property
    def version(self) -> int:
        return len(self._updates)

    @property
    def pricing_restricted(self) -> bool:
        if any("pricing" in u.field_changes for u in self._updates):
            return True
        return any("price" in r.lower() for u in self._updates for r in u.new_rules)

    def current_profile(self) -> dict[str, str]:
        profile = dict(SEED_PROFILE)
        for u in self._updates:
            profile.update(u.field_changes)
        return profile

    def rules(self) -> list[str]:
        return list(SEED_MARKETING_NOTES) + [r for u in self._updates for r in u.new_rules]

    def updates(self) -> list[KnowledgeUpdate]:
        return list(self._updates)

    def apply_update(
        self, source_text: str, summary: str, field_changes: dict[str, str], new_rules: list[str]
    ) -> KnowledgeUpdate:
        update = KnowledgeUpdate(
            version=self.version + 1,
            created_at=_now(),
            source_text=source_text,
            summary=summary,
            field_changes=dict(field_changes),
            new_rules=list(new_rules),
        )
        self._updates.append(update)
        return update

    def render(self) -> str:
        lines = [f"Knowledge version: v{self.version}", "", "Profile:"]
        lines += [f"- {k}: {v}" for k, v in self.current_profile().items()]
        lines += ["", "Marketing notes and rules:"]
        lines += [f"- {r}" for r in self.rules()]
        return "\n".join(lines)


class FakeBriefStore:
    def __init__(self, path: Path | None = None):
        self.path = path
        self._records: list[BriefRecord] = []

    def save(
        self,
        draft: BriefDraft,
        markdown: str,
        kind: str,
        revises: int | None,
        knowledge_version: int,
        request: str,
    ) -> BriefRecord:
        record = BriefRecord(
            version=len(self._records) + 1,
            created_at=_now(),
            kind=kind,
            revises=revises,
            knowledge_version=knowledge_version,
            request=request,
            draft=draft,
            markdown=markdown,
        )
        self._records.append(record)
        return record

    def latest(self) -> BriefRecord | None:
        return self._records[-1] if self._records else None

    def get(self, version: int) -> BriefRecord | None:
        return next((r for r in self._records if r.version == version), None)

    def list(self) -> list[BriefRecord]:
        return list(self._records)

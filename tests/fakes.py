"""In-memory stand-ins for the stores, so tool tests touch no files.

FakeBriefStore reuses BriefStore's campaign/version logic over an in-memory BriefsFile.
"""

from datetime import datetime, timezone
from pathlib import Path

from startup_assistant.briefs import BriefsFile, BriefStore
from startup_assistant.contracts import KnowledgeUpdate
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


class FakeBriefStore(BriefStore):
    """The real BriefStore's campaign and version logic, kept in memory instead of a file."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self._data = BriefsFile()

    def _load(self) -> BriefsFile:
        return self._data

    def _write(self, data: BriefsFile) -> None:
        self._data = data

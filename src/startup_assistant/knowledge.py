"""Versioned company knowledge: the seed profile plus founder updates, stored as JSON."""

import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from startup_assistant.contracts import KnowledgeUpdate
from startup_assistant.seed import SEED_MARKETING_NOTES, SEED_PROFILE


_PRICE_RULE = re.compile(r"\bpric(?:e|es|ing)\b", re.IGNORECASE)


class KnowledgeFile(BaseModel):
    updates: list[KnowledgeUpdate] = []


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


class KnowledgeStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> KnowledgeFile:
        if not self.path.exists():
            return KnowledgeFile()
        return KnowledgeFile.model_validate_json(self.path.read_text(encoding="utf-8"))

    @property
    def version(self) -> int:
        return len(self._load().updates)

    @property
    def pricing_restricted(self) -> bool:
        updates = self._load().updates
        if any("pricing" in u.field_changes for u in updates):
            return True
        # A rule like "leave prices out of campaign materials" also turns it on.
        return any(_PRICE_RULE.search(rule) for u in updates for rule in u.new_rules)

    def current_profile(self) -> dict[str, str]:
        profile = dict(SEED_PROFILE)
        for update in self._load().updates:
            profile.update(update.field_changes)
        return profile

    def rules(self) -> list[str]:
        rules = list(SEED_MARKETING_NOTES)
        for update in self._load().updates:
            rules.extend(update.new_rules)
        return rules

    def updates(self) -> list[KnowledgeUpdate]:
        return list(self._load().updates)

    def apply_update(
        self, source_text: str, summary: str, field_changes: dict[str, str], new_rules: list[str]
    ) -> KnowledgeUpdate:
        data = self._load()
        update = KnowledgeUpdate(
            version=len(data.updates) + 1,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            source_text=source_text,
            summary=summary,
            field_changes=dict(field_changes),
            new_rules=list(new_rules),
        )
        data.updates.append(update)
        _atomic_write(self.path, data.model_dump_json(indent=2))
        return update

    def render(self) -> str:
        data = self._load()
        last_changed: dict[str, int] = {}
        for update in data.updates:
            for key in update.field_changes:
                last_changed[key] = update.version
        lines = [f"Company knowledge (v{len(data.updates)})", "", "Profile:"]
        for key, value in self.current_profile().items():
            mark = f" [updated in v{last_changed[key]}]" if key in last_changed else ""
            lines.append(f"- {key}: {value}{mark}")
        lines += ["", "Marketing rules:"]
        lines += [f"- {rule}" for rule in self.rules()]
        return "\n".join(lines)

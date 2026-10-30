"""Track A: versioned campaign briefs. Stub."""

from pathlib import Path

from startup_assistant.contracts import BriefDraft, BriefRecord


class BriefStore:
    def __init__(self, path: Path):
        self.path = path

    def save(
        self,
        draft: BriefDraft,
        markdown: str,
        kind: str,
        revises: int | None,
        knowledge_version: int,
        request: str,
    ) -> BriefRecord:
        raise NotImplementedError

    def latest(self) -> BriefRecord | None:
        raise NotImplementedError

    def get(self, version: int) -> BriefRecord | None:
        raise NotImplementedError

    def list(self) -> list[BriefRecord]:
        raise NotImplementedError

"""Track A: versioned company knowledge (seed + founder updates). Stub."""

from pathlib import Path

from startup_assistant.contracts import KnowledgeUpdate


class KnowledgeStore:
    def __init__(self, path: Path):
        self.path = path

    @property
    def version(self) -> int:
        raise NotImplementedError

    @property
    def pricing_restricted(self) -> bool:
        raise NotImplementedError

    def current_profile(self) -> dict[str, str]:
        raise NotImplementedError

    def rules(self) -> list[str]:
        raise NotImplementedError

    def updates(self) -> list[KnowledgeUpdate]:
        raise NotImplementedError

    def apply_update(
        self, source_text: str, summary: str, field_changes: dict[str, str], new_rules: list[str]
    ) -> KnowledgeUpdate:
        raise NotImplementedError

    def render(self) -> str:
        raise NotImplementedError

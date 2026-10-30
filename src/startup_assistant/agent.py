"""Track B: the Assistant. Stub."""

from pathlib import Path
from typing import Literal

from startup_assistant.contracts import Reply


def auth_mode() -> Literal["api-key", "claude-session"]:
    raise NotImplementedError


class Assistant:
    def __init__(self, data_dir: Path, model: str | None = None):
        self.data_dir = data_dir
        self.model = model

    async def __aenter__(self) -> "Assistant":
        raise NotImplementedError

    async def __aexit__(self, *exc) -> None:
        raise NotImplementedError

    async def handle(self, text: str) -> Reply:
        raise NotImplementedError

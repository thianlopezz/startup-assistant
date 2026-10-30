"""Track C: rich REPL. Stub."""

import argparse
from pathlib import Path

from rich.console import Console

from startup_assistant.contracts import Reply


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    raise NotImplementedError


def render_reply(console: Console, reply: Reply) -> None:
    raise NotImplementedError


def reset_data(data_dir: Path) -> None:
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError

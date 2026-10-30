"""Calls the real model through the Claude Agent SDK. Needs the real stores (Track A).

Run with: RUN_LIVE=1 .venv/bin/pytest -q -m live
"""

import asyncio
import os

import pytest

from startup_assistant.agent import Assistant

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to call the model"),
]


def test_answer_needs_no_tool(tmp_path):
    async def go():
        async with Assistant(tmp_path) as assistant:
            return await assistant.handle("Who is our primary buyer?")

    reply = asyncio.run(go())
    assert reply.actions == []
    assert "founder" in reply.text.lower() or "operations" in reply.text.lower()

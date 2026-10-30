"""Track B: the Assistant — one Claude Agent SDK session with four in-process tools."""

import asyncio
import os
from pathlib import Path
from typing import Literal

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookContext,
    HookInput,
    HookJSONOutput,
    HookMatcher,
    ResultMessage,
    TextBlock,
)

from startup_assistant.briefs import BriefStore
from startup_assistant.contracts import Reply
from startup_assistant.knowledge import KnowledgeStore
from startup_assistant.prompts import SYSTEM_PROMPT, build_turn_message
from startup_assistant.tools import SERVER_NAME, TOOL_NAMES, TurnLog, brief_index, build_server

MAX_TURNS = 8
DRAIN_TIMEOUT_S = 10


def auth_mode() -> Literal["api-key", "claude-session"]:
    """The SDK uses ANTHROPIC_API_KEY when set, otherwise the local Claude Code login."""
    return "api-key" if os.environ.get("ANTHROPIC_API_KEY") else "claude-session"


class Assistant:
    def __init__(self, data_dir: Path, model: str | None = None):
        self.data_dir = Path(data_dir)
        self.model = model or os.environ.get("ASSISTANT_MODEL") or None
        self.turn = TurnLog()
        self.knowledge: KnowledgeStore | None = None
        self.briefs: BriefStore | None = None
        self._client: ClaudeSDKClient | None = None
        # Knowledge version the model has already seen in full in this client session.
        self._sent_knowledge_version: int | None = None

    def _options(self) -> ClaudeAgentOptions:
        server = build_server(self.knowledge, self.briefs, self.turn)
        return ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={SERVER_NAME: server},
            strict_mcp_config=True,  # ignore any other MCP servers configured on this machine
            tools=[],  # no built-in Claude Code tools (Bash, Read, Write, WebSearch, ...)
            allowed_tools=TOOL_NAMES,
            setting_sources=[],  # don't load user/project settings or CLAUDE.md
            permission_mode="dontAsk",  # never prompt; anything not pre-approved is denied
            max_turns=MAX_TURNS,
            model=self.model,
            hooks={"PreCompact": [HookMatcher(hooks=[self._on_pre_compact])]},
        )

    async def _on_pre_compact(
        self, input: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        """Compaction may summarise away the full knowledge block we sent earlier, so the next
        turn must resend it rather than say "Unchanged since vN"."""
        self._sent_knowledge_version = None
        return {}

    def _make_client(self) -> ClaudeSDKClient:
        """Seam for tests: they return a fake client here."""
        return ClaudeSDKClient(options=self._options())

    async def __aenter__(self) -> "Assistant":
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.knowledge = KnowledgeStore(self.data_dir / "knowledge.json")
        self.briefs = BriefStore(self.data_dir / "briefs.json")
        self._client = self._make_client()
        self._sent_knowledge_version = None
        await self._client.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    async def _abort_turn(self) -> None:
        """Best effort: stop the in-flight turn and drain its messages up to the ResultMessage,
        so they don't leak into the next turn. Never raises."""
        client = self._client
        if client is None:
            return
        try:
            async with asyncio.timeout(DRAIN_TIMEOUT_S):
                await client.interrupt()
                async for _ in client.receive_response():
                    pass
        except BaseException:
            pass

    async def handle(self, text: str) -> Reply:
        if self._client is None:
            raise RuntimeError("Assistant is not connected; use `async with Assistant(...)`.")
        # Reset in place: the tool handlers hold a reference to this TurnLog.
        self.turn.user_text = text
        self.turn.actions.clear()
        self.turn.artifacts.clear()

        # Send the full knowledge only when the model hasn't seen this version yet (first turn,
        # after a change, including one a tool made last turn, or after an aborted turn).
        version = self.knowledge.version
        knowledge_text = None if version == self._sent_knowledge_version else self.knowledge.render()
        parts: list[str] = []
        try:
            # Set before query(): a PreCompact hook may reset it while the turn runs.
            self._sent_knowledge_version = version
            await self._client.query(
                build_turn_message(knowledge_text, brief_index(self.briefs), text, version)
            )
            async for message in self._client.receive_response():
                if isinstance(message, AssistantMessage):
                    if message.error:
                        parts.append(f"[Model error: {message.error}]")
                    parts += [b.text for b in message.content if isinstance(b, TextBlock)]
                elif isinstance(message, ResultMessage) and message.is_error:
                    detail = "; ".join(message.errors or []) or message.subtype
                    parts.append(f"[The request did not finish cleanly: {detail}]")
        except BaseException:  # includes CancelledError / KeyboardInterrupt
            self._sent_knowledge_version = None  # unsure what the model saw; resend next turn
            await self._abort_turn()
            raise

        return Reply(
            text="\n\n".join(p.strip() for p in parts if p.strip()),
            artifacts=list(self.turn.artifacts),
            actions=list(self.turn.actions),
        )

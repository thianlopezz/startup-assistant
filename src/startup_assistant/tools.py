"""Track B: tool definitions, brief validation and rendering. Stub."""

from pydantic import BaseModel

from startup_assistant.briefs import BriefStore
from startup_assistant.contracts import BriefDraft, BriefRecord
from startup_assistant.knowledge import KnowledgeStore

SERVER_NAME = "harbordesk"
TOOL_NAMES: list[str] = [
    f"mcp__{SERVER_NAME}__update_company_knowledge",
    f"mcp__{SERVER_NAME}__save_brief",
    f"mcp__{SERVER_NAME}__get_latest_brief",
    f"mcp__{SERVER_NAME}__list_briefs",
]


class TurnLog(BaseModel):
    user_text: str = ""
    actions: list[str] = []
    artifacts: list[str] = []


def word_count(text: str) -> int:
    raise NotImplementedError


def validate_brief(draft: BriefDraft, pricing_restricted: bool) -> list[str]:
    raise NotImplementedError


def render_brief_markdown(draft: BriefDraft) -> str:
    raise NotImplementedError


def render_record_header(record: BriefRecord, latest_version: int) -> str:
    raise NotImplementedError


def build_server(knowledge: KnowledgeStore, briefs: BriefStore, turn: TurnLog):
    raise NotImplementedError

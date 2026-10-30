"""Shared data types. Every track codes against these."""

from typing import Literal

from pydantic import BaseModel, Field


class Channel(BaseModel):
    name: str
    reason: str


class BriefDraft(BaseModel):
    """What the model submits to save_brief."""

    title: str
    audience: str
    buyer: str
    main_message: str
    channels: list[Channel] = Field(min_length=2, max_length=2)
    email_subject: str
    email_body: str
    assumptions: list[str]
    open_questions: list[str]


class BriefRecord(BaseModel):
    """What BriefStore persists. `markdown` is rendered once at save time."""

    version: int
    created_at: str
    kind: Literal["created", "revised"]
    revises: int | None
    knowledge_version: int
    request: str
    draft: BriefDraft
    markdown: str


class KnowledgeUpdate(BaseModel):
    version: int
    created_at: str
    source_text: str
    summary: str
    field_changes: dict[str, str]
    new_rules: list[str]


class Reply(BaseModel):
    """What Assistant.handle returns to the CLI."""

    text: str
    artifacts: list[str] = []
    actions: list[str] = []

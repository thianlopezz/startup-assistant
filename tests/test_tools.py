import asyncio

import pytest
from fakes import FakeBriefStore, FakeKnowledgeStore

from startup_assistant.contracts import BriefDraft, Channel
from startup_assistant.tools import (
    TOOL_NAMES,
    TurnLog,
    build_server,
    make_tools,
    render_brief_markdown,
    render_record_header,
    validate_brief,
    word_count,
)


def make_draft(**overrides) -> BriefDraft:
    data = dict(
        title="Onboarding handoffs, without the spreadsheet",
        audience="Agencies and consultancies with 10–50 employees",
        buyer="Founder or operations lead",
        main_message="Clear ownership and visibility at every onboarding step.",
        channels=[
            Channel(name="LinkedIn posts", reason="Used before; reaches founders directly."),
            Channel(name="Targeted email", reason="Used before; lets us speak to one segment."),
        ],
        email_subject="Fewer missed onboarding handoffs",
        email_body="Hi Sam, onboarding often lives in email threads and spreadsheets. "
        "HarborDesk gives every step an owner and a reminder. Worth a short call?",
        assumptions=["Buyers feel the pain of missed handoffs."],
        open_questions=["Which segment do we start with?"],
    )
    data.update(overrides)
    return BriefDraft(**data)


def words(n: int) -> str:
    return " ".join(["word"] * n)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def stores():
    return FakeKnowledgeStore(), FakeBriefStore()


# --- pure functions -------------------------------------------------------------------


def test_word_count():
    assert word_count("one two  three\nfour") == 4
    assert word_count("") == 0


def test_validate_ok():
    assert validate_brief(make_draft(), pricing_restricted=False) == []


def test_validate_long_email():
    errors = validate_brief(make_draft(email_body=words(151)), pricing_restricted=False)
    assert len(errors) == 1
    assert "150" in errors[0]


def test_validate_150_words_is_ok():
    assert validate_brief(make_draft(email_body=words(150)), pricing_restricted=False) == []


def test_validate_pricing():
    priced_body = make_draft(email_body="Plans start at $299/month. Want a demo?")
    assert validate_brief(priced_body, pricing_restricted=True)
    priced_message = make_draft(main_message="Simple pricing, clear ownership.")
    assert validate_brief(priced_message, pricing_restricted=True)
    assert validate_brief(priced_body, pricing_restricted=False) == []
    assert validate_brief(priced_message, pricing_restricted=False) == []


def test_validate_half_claim():
    for field in ("main_message", "email_body", "title"):
        draft = make_draft(**{field: "HarborDesk cuts onboarding time in half."})
        errors = validate_brief(draft, pricing_restricted=False)
        assert errors, field
        assert any("half" in e.lower() for e in errors)


def test_render_sections_in_order():
    md = render_brief_markdown(make_draft())
    headings = [
        "# Onboarding handoffs, without the spreadsheet",
        "## Audience",
        "## Buyer",
        "## Main message",
        "## Recommended channels (proposals)",
        "## Draft email",
        "## Assumptions",
        "## Open questions",
    ]
    positions = [md.index(h) for h in headings]
    assert positions == sorted(positions)
    assert "Draft for review — not sent." in md
    assert "LinkedIn posts" in md and "Targeted email" in md


def test_record_header_current_and_superseded(stores):
    _, briefs = stores
    draft = make_draft()
    r1 = briefs.save(draft, "md", "created", None, 0, "make a brief")
    r2 = briefs.save(draft, "md", "revised", 1, 1, "revise it")
    h1 = render_record_header(r1, latest_version=2)
    h2 = render_record_header(r2, latest_version=2)
    assert h1.startswith("Brief v1 — superseded by v2")
    assert "knowledge v0" in h1
    assert h2.startswith("Brief v2 — CURRENT")
    assert "revises v1" in h2 and "knowledge v1" in h2 and r2.created_at in h2


def test_tool_names_and_server(stores):
    knowledge, briefs = stores
    assert TOOL_NAMES == [
        "mcp__harbordesk__update_company_knowledge",
        "mcp__harbordesk__save_brief",
        "mcp__harbordesk__get_latest_brief",
        "mcp__harbordesk__list_briefs",
    ]
    server = build_server(knowledge, briefs, TurnLog())
    assert server["type"] == "sdk" and server["name"] == "harbordesk"


def test_save_brief_schema_has_no_refs(stores):
    knowledge, briefs = stores
    schema = make_tools(knowledge, briefs, TurnLog())["save_brief"].input_schema
    assert "$ref" not in str(schema)
    assert schema["properties"]["draft"]["properties"]["channels"]["minItems"] == 2


# --- tool handlers --------------------------------------------------------------------


def test_save_brief_tool_records_action_and_artifact(stores):
    knowledge, briefs = stores
    turn = TurnLog(user_text="Create a campaign brief")
    tools = make_tools(knowledge, briefs, turn)
    result = run(tools["save_brief"].handler({"draft": make_draft().model_dump()}))
    assert not result.get("is_error")
    assert turn.actions == ["Brief v1 saved (new)"]
    record = briefs.latest()
    assert record.kind == "created" and record.revises is None
    assert record.request == "Create a campaign brief"
    assert record.markdown in turn.artifacts[0]
    assert turn.artifacts[0].startswith("Brief v1 — CURRENT")


def test_save_brief_revision(stores):
    knowledge, briefs = stores
    turn = TurnLog(user_text="first")
    tools = make_tools(knowledge, briefs, turn)
    run(tools["save_brief"].handler({"draft": make_draft().model_dump()}))
    turn.actions.clear()
    turn.artifacts.clear()
    run(tools["get_latest_brief"].handler({}))
    result = run(tools["save_brief"].handler({"draft": make_draft().model_dump(), "revises": 1}))
    assert not result.get("is_error")
    assert turn.actions == ["Brief v2 saved (revises v1)"]
    assert briefs.latest().kind == "revised" and briefs.latest().revises == 1
    # the v1 copy fetched for revising is dropped; the founder sees the new version
    assert len(turn.artifacts) == 1 and turn.artifacts[0].startswith("Brief v2 — CURRENT")


def test_save_brief_revises_unknown_version(stores):
    knowledge, briefs = stores
    turn = TurnLog()
    tools = make_tools(knowledge, briefs, turn)
    result = run(tools["save_brief"].handler({"draft": make_draft().model_dump(), "revises": 7}))
    assert result["is_error"] is True
    assert briefs.list() == [] and turn.actions == []


def test_save_brief_invalid_saves_nothing(stores):
    knowledge, briefs = stores
    turn = TurnLog()
    tools = make_tools(knowledge, briefs, turn)
    draft = make_draft(email_body=words(170)).model_dump()
    result = run(tools["save_brief"].handler({"draft": draft}))
    assert result["is_error"] is True
    assert "150" in result["content"][0]["text"]
    assert briefs.list() == []
    assert turn.actions == [] and turn.artifacts == []


def test_save_brief_pydantic_error_saves_nothing(stores):
    knowledge, briefs = stores
    turn = TurnLog()
    tools = make_tools(knowledge, briefs, turn)
    draft = make_draft().model_dump()
    draft["channels"] = draft["channels"][:1]
    result = run(tools["save_brief"].handler({"draft": draft}))
    assert result["is_error"] is True
    assert briefs.list() == [] and turn.actions == []


def test_save_brief_enforces_pricing_after_update(stores):
    knowledge, briefs = stores
    knowledge.apply_update("x", "pricing under review", {"pricing": "Under review"}, [])
    turn = TurnLog()
    tools = make_tools(knowledge, briefs, turn)
    draft = make_draft(email_body="Plans start at $299 per month.").model_dump()
    result = run(tools["save_brief"].handler({"draft": draft}))
    assert result["is_error"] is True
    assert briefs.list() == []


def test_update_knowledge_tool(stores):
    knowledge, briefs = stores
    briefs.save(make_draft(), "md", "created", None, 0, "make a brief")
    founder = "We're shifting our target to B2B software companies with 100–500 employees."
    turn = TurnLog(user_text=founder)
    tools = make_tools(knowledge, briefs, turn)
    result = run(
        tools["update_company_knowledge"].handler(
            {
                "summary": "New target and buyer; pricing out of campaign materials.",
                "field_changes": {
                    "target_customers": "B2B software companies with 100–500 employees.",
                    "primary_buyer": "Head of Customer Success.",
                },
                "new_rules": ["Leave prices out of campaign materials."],
            }
        )
    )
    assert not result.get("is_error")
    assert knowledge.version == 1
    assert knowledge.updates()[0].source_text == founder
    assert turn.actions == ["Company knowledge updated → v1"]
    text = result["content"][0]["text"]
    assert "v1" in text and "stale" in text.lower()
    assert briefs.list()[0].version == 1  # nothing revised


def test_update_knowledge_no_briefs(stores):
    knowledge, briefs = stores
    tools = make_tools(knowledge, briefs, TurnLog(user_text="x"))
    result = run(
        tools["update_company_knowledge"].handler(
            {"summary": "s", "field_changes": {}, "new_rules": ["r"]}
        )
    )
    assert "no saved briefs" in result["content"][0]["text"].lower()


def test_get_latest_brief_empty_and_present(stores):
    knowledge, briefs = stores
    turn = TurnLog()
    tools = make_tools(knowledge, briefs, turn)
    result = run(tools["get_latest_brief"].handler({}))
    assert "No brief saved yet." in result["content"][0]["text"]
    assert turn.artifacts == [] and turn.actions == []

    md = render_brief_markdown(make_draft())
    briefs.save(make_draft(), md, "created", None, 0, "r")
    briefs.save(make_draft(), md + "\nv2", "revised", 1, 0, "r")
    run(tools["get_latest_brief"].handler({}))
    assert turn.actions == []
    assert turn.artifacts == [render_record_header(briefs.latest(), 2) + "\n\n" + md + "\nv2"]
    assert len(briefs.list()) == 2


def test_list_briefs(stores):
    knowledge, briefs = stores
    turn = TurnLog()
    tools = make_tools(knowledge, briefs, turn)
    assert "No briefs saved yet." in run(tools["list_briefs"].handler({}))["content"][0]["text"]
    briefs.save(make_draft(), "md", "created", None, 0, "r")
    text = run(tools["list_briefs"].handler({}))["content"][0]["text"]
    assert "v1" in text and make_draft().title in text
    assert turn.actions == [] and turn.artifacts == []


# --- fix round 1 ----------------------------------------------------------------------


def test_pricing_restricted_by_rule_only(tmp_path):
    from startup_assistant.knowledge import KnowledgeStore

    knowledge, briefs = KnowledgeStore(tmp_path / "k.json"), FakeBriefStore()
    assert knowledge.pricing_restricted is False
    knowledge.apply_update("x", "no prices", {}, ["Leave Prices out of campaign materials."])
    assert knowledge.pricing_restricted is True
    turn = TurnLog()
    tools = make_tools(knowledge, briefs, turn)
    draft = make_draft(email_body="Plans start at $299/month.").model_dump()
    result = run(tools["save_brief"].handler({"draft": draft}))
    assert result["is_error"] is True
    assert briefs.list() == [] and turn.actions == []


@pytest.mark.parametrize(
    "claim",
    ["It cuts onboarding time by half.", "Onboard in half the time.", "Saves 50 percent of effort."],
)
def test_validate_half_claim_rewordings(claim):
    errors = validate_brief(make_draft(main_message=claim), pricing_restricted=False)
    assert any("half" in e.lower() for e in errors)


@pytest.mark.parametrize(
    "body",
    ["Only $ a little each month.", "Just 299 per month.", "From 299/mo for teams."],
)
def test_validate_pricing_any_dollar_and_per_month(body):
    assert validate_brief(make_draft(email_body=body), pricing_restricted=True)
    assert validate_brief(make_draft(email_body=body), pricing_restricted=False) == []


def test_save_brief_drops_all_retrieved_artifacts(stores):
    knowledge, briefs = stores
    briefs.save(make_draft(), "md", "created", None, 0, "r")
    turn = TurnLog()
    tools = make_tools(knowledge, briefs, turn)
    run(tools["get_latest_brief"].handler({}))
    run(tools["save_brief"].handler({"draft": make_draft().model_dump()}))  # new, not a revision
    assert len(turn.artifacts) == 1 and turn.artifacts[0].startswith("Brief v2 — CURRENT")

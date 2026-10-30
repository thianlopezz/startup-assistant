import asyncio

import pytest
from fakes import FakeBriefStore, FakeKnowledgeStore

from startup_assistant import checker
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


@pytest.fixture(autouse=True)
def no_ai_checker(monkeypatch):
    """Unit tests never call the model; the checker tests below turn it back on."""
    monkeypatch.setattr(checker, "checker_enabled", lambda: False)


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
    assert h1.startswith('Brief "Customer acquisition" v1 — superseded by v2')
    assert "knowledge v0" in h1
    assert h2.startswith('Brief "Customer acquisition" v2 — CURRENT')
    assert "revises v1" in h2 and "knowledge v1" in h2 and r2.created_at in h2


def test_tool_names_and_server(stores):
    knowledge, briefs = stores
    assert TOOL_NAMES == [
        "mcp__harbordesk__update_company_knowledge",
        "mcp__harbordesk__save_brief",
        "mcp__harbordesk__get_latest_brief",
        "mcp__harbordesk__list_briefs",
        "mcp__harbordesk__get_brief",
        "mcp__harbordesk__compare_briefs",
    ]
    assert len(TOOL_NAMES) == 6
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
    assert turn.actions == ['Brief "Customer acquisition" v1 saved (new)']
    record = briefs.latest()
    assert record.kind == "created" and record.revises is None
    assert record.request == "Create a campaign brief"
    assert record.markdown in turn.artifacts[0]
    assert turn.artifacts[0].startswith('Brief "Customer acquisition" v1 — CURRENT')


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
    assert turn.actions == ['Brief "Customer acquisition" v2 saved (revises v1)']
    assert briefs.latest().kind == "revised" and briefs.latest().revises == 1
    # the v1 copy fetched for revising is dropped; the founder sees the new version
    assert len(turn.artifacts) == 1 and turn.artifacts[0].startswith('Brief "Customer acquisition" v2 — CURRENT')


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
    assert len(turn.artifacts) == 1 and turn.artifacts[0].startswith('Brief "Customer acquisition" v2 — CURRENT')


# --- phase 2 track 1 ------------------------------------------------------------------


@pytest.mark.parametrize(
    "claim",
    [
        "HarborDesk cuts onboarding time in half.",
        "It reduces setup effort by half.",
        "Slashes handoff time in half.",
        "Saves your team time in half the cases.",
        "Onboard in half the time.",
        "It halves onboarding time.",
        "Time is halved.",
        "Halving the busywork.",
        "Cut busywork by 50%.",
        "Save 50 percent of the effort.",
    ],
)
def test_validate_rejects_reduction_claims(claim):
    errors = validate_brief(make_draft(main_message=claim), pricing_restricted=False)
    assert any("half" in e.lower() for e in errors), claim


@pytest.mark.parametrize(
    "text",
    [
        "Join a half-day kickoff workshop.",
        "Book a half hour with us.",
        "In the second half of Q1 we start.",
        "I write on behalf of the team.",
    ],
)
def test_validate_allows_innocent_half(text):
    assert validate_brief(make_draft(email_body=text), pricing_restricted=False) == []


@pytest.mark.parametrize(
    "text",
    ["Commercial terms are left out.", "We will share Commercial Term details later."],
)
def test_validate_commercial_terms_when_restricted(text):
    errors = validate_brief(make_draft(assumptions=[text]), pricing_restricted=True)
    assert any(e.startswith("assumptions[1]:") and "pricing" in e for e in errors)
    assert validate_brief(make_draft(assumptions=[text]), pricing_restricted=False) == []


def test_get_brief_superseded_version(stores):
    knowledge, briefs = stores
    briefs.save(make_draft(), "V1 MARKDOWN", "created", None, 0, "r")
    briefs.save(make_draft(), "V2 MARKDOWN", "revised", 1, 0, "r")
    turn = TurnLog()
    tools = make_tools(knowledge, briefs, turn)
    result = run(tools["get_brief"].handler({"version": 1}))
    assert not result.get("is_error")
    assert turn.actions == []
    assert len(turn.artifacts) == 1
    assert "superseded by v2" in turn.artifacts[0]
    assert turn.artifacts[0].endswith("V1 MARKDOWN")
    assert turn.artifacts[0] == (
        render_record_header(briefs.get(1), 2) + "\n\n" + briefs.get(1).markdown
    )


def test_get_brief_missing_version(stores):
    knowledge, briefs = stores
    briefs.save(make_draft(), "md", "created", None, 0, "r")
    turn = TurnLog()
    tools = make_tools(knowledge, briefs, turn)
    result = run(tools["get_brief"].handler({"version": 5}))
    assert "No brief v5 saved." in result["content"][0]["text"]
    assert turn.artifacts == [] and turn.actions == []


def test_get_brief_copy_dropped_when_new_version_saved(stores):
    knowledge, briefs = stores
    briefs.save(make_draft(), "md", "created", None, 0, "r")
    turn = TurnLog()
    tools = make_tools(knowledge, briefs, turn)
    run(tools["get_brief"].handler({"version": 1}))
    run(tools["save_brief"].handler({"draft": make_draft().model_dump(), "revises": 1}))
    assert len(turn.artifacts) == 1 and turn.artifacts[0].startswith('Brief "Customer acquisition" v2 — CURRENT')


def test_retrieved_copies_do_not_accumulate_across_turns(stores):
    knowledge, briefs = stores
    briefs.save(make_draft(), "md", "created", None, 0, "r")
    turn = TurnLog(user_text="turn 1")
    tools = make_tools(knowledge, briefs, turn)
    run(tools["get_latest_brief"].handler({}))
    run(tools["get_brief"].handler({"version": 1}))
    assert len(turn.retrieved) == 2
    # Assistant.handle resets the turn in place
    turn.user_text = "turn 2"
    turn.actions.clear()
    turn.artifacts.clear()
    run(tools["get_brief"].handler({"version": 1}))
    assert len(turn.retrieved) == 1  # only this turn's copy
    run(tools["save_brief"].handler({"draft": make_draft().model_dump(), "revises": 1}))
    assert len(turn.artifacts) == 1 and turn.artifacts[0].startswith('Brief "Customer acquisition" v2 — CURRENT')
    assert turn.retrieved == []


# --- phase 3: named campaigns ---------------------------------------------------------


def _text(result) -> str:
    return result["content"][0]["text"]


def test_save_brief_named_campaign_actions_and_header(stores):
    knowledge, briefs = stores
    turn = TurnLog(user_text="spring")
    tools = make_tools(knowledge, briefs, turn)
    draft = make_draft().model_dump()
    run(tools["save_brief"].handler({"draft": draft}))
    run(tools["save_brief"].handler({"draft": draft, "campaign": "Spring launch"}))
    run(tools["save_brief"].handler({"draft": draft, "campaign": " spring LAUNCH", "revises": 1}))
    assert turn.actions == [
        'Brief "Customer acquisition" v1 saved (new)',
        'Brief "Spring launch" v1 saved (new)',
        'Brief "Spring launch" v2 saved (revises v1)',
    ]
    assert turn.artifacts[-1].startswith('Brief "Spring launch" v2 — CURRENT · revises v1 · ')
    assert briefs.campaigns() == ["Customer acquisition", "Spring launch"]


def test_save_brief_revises_version_from_other_campaign(stores):
    knowledge, briefs = stores
    briefs.save(make_draft(), "a1", "created", None, 0, "r")
    briefs.save(make_draft(), "a2", "revised", 1, 0, "r")
    briefs.save(make_draft(), "b1", "created", None, 0, "r", campaign="Spring launch")
    turn = TurnLog()
    tools = make_tools(knowledge, briefs, turn)
    result = run(
        tools["save_brief"].handler(
            {"draft": make_draft().model_dump(), "campaign": "Spring launch", "revises": 2}
        )
    )
    assert result["is_error"] is True
    assert "Spring launch" in _text(result)
    assert len(briefs.list()) == 3 and turn.actions == [] and turn.artifacts == []


def test_get_latest_brief_default_is_most_recent_and_names_other_campaigns(stores):
    knowledge, briefs = stores
    briefs.save(make_draft(), "A1", "created", None, 0, "r")
    briefs.save(make_draft(), "B1", "created", None, 0, "r", campaign="Spring launch")
    turn = TurnLog()
    tools = make_tools(knowledge, briefs, turn)
    text = _text(run(tools["get_latest_brief"].handler({})))
    assert turn.artifacts == [render_record_header(briefs.latest(), 1) + "\n\nB1"]
    assert turn.artifacts[0].startswith('Brief "Spring launch" v1 — CURRENT')
    after = text.split("B1", 1)[1]
    assert '"Customer acquisition"' in after
    turn.artifacts.clear()
    run(tools["get_latest_brief"].handler({"campaign": "customer acquisition"}))
    assert turn.artifacts[0].endswith("A1")
    assert turn.actions == []


def test_get_latest_brief_single_campaign_names_no_others(stores):
    knowledge, briefs = stores
    briefs.save(make_draft(), "A1", "created", None, 0, "r")
    text = _text(run(make_tools(knowledge, briefs, TurnLog())["get_latest_brief"].handler({})))
    assert "other campaign" not in text.lower()


def test_get_latest_brief_unknown_campaign(stores):
    knowledge, briefs = stores
    briefs.save(make_draft(), "A1", "created", None, 0, "r")
    turn = TurnLog()
    result = run(
        make_tools(knowledge, briefs, turn)["get_latest_brief"].handler({"campaign": "Nope"})
    )
    assert '"Nope"' in _text(result) and '"Customer acquisition"' in _text(result)
    assert turn.artifacts == []


def test_get_brief_with_campaign(stores):
    knowledge, briefs = stores
    briefs.save(make_draft(), "A1", "created", None, 0, "r")
    briefs.save(make_draft(), "A2", "revised", 1, 0, "r")
    briefs.save(make_draft(), "B1", "created", None, 0, "r", campaign="Spring launch")
    turn = TurnLog()
    tools = make_tools(knowledge, briefs, turn)
    run(tools["get_brief"].handler({"version": 1, "campaign": "Spring launch"}))
    run(tools["get_brief"].handler({"version": 1, "campaign": "Customer acquisition"}))
    assert turn.artifacts[0].startswith('Brief "Spring launch" v1 — CURRENT')
    assert turn.artifacts[0].endswith("B1")
    assert turn.artifacts[1].startswith('Brief "Customer acquisition" v1 — superseded by v2')
    result = run(tools["get_brief"].handler({"version": 2, "campaign": "Spring launch"}))
    assert "v2" in _text(result) and "Spring launch" in _text(result)
    assert len(turn.artifacts) == 2


def test_list_briefs_grouped_by_campaign(stores):
    knowledge, briefs = stores
    briefs.save(make_draft(title="A one"), "A1", "created", None, 0, "r")
    briefs.save(make_draft(title="B one"), "B1", "created", None, 0, "r", campaign="Spring launch")
    briefs.save(make_draft(title="A two"), "A2", "revised", 1, 0, "r")
    text = _text(run(make_tools(knowledge, briefs, TurnLog())["list_briefs"].handler({})))
    ca, sl = text.index('"Customer acquisition"'), text.index('"Spring launch"')
    assert ca < text.index("A one") < text.index("A two") < sl < text.index("B one")
    a_section = text[ca:sl]
    assert "v1 · superseded by v2" in a_section and "v2 · CURRENT" in a_section
    assert "v1 · CURRENT" in text[sl:]


def test_update_knowledge_names_stale_briefs_with_campaign(stores):
    knowledge, briefs = stores
    briefs.save(make_draft(), "A1", "created", None, 0, "r")
    briefs.save(make_draft(), "B1", "created", None, 0, "r", campaign="Spring launch")
    tools = make_tools(knowledge, briefs, TurnLog(user_text="x"))
    text = _text(
        run(
            tools["update_company_knowledge"].handler(
                {"summary": "s", "field_changes": {}, "new_rules": ["r"]}
            )
        )
    )
    assert '"Customer acquisition" v1' in text and '"Spring launch" v1' in text


# --- phase 3: compare_briefs ----------------------------------------------------------


def test_compare_briefs_artifact(stores):
    knowledge, briefs = stores
    md1 = render_brief_markdown(make_draft())
    md2 = render_brief_markdown(make_draft(buyer="Head of Customer Success"))
    briefs.save(make_draft(), md1, "created", None, 0, "r")
    briefs.save(make_draft(), md2, "revised", 1, 1, "r")
    turn = TurnLog()
    tools = make_tools(knowledge, briefs, turn)
    result = run(tools["compare_briefs"].handler({"from_version": 1, "to_version": 2}))
    assert not result.get("is_error")
    assert turn.actions == []
    assert len(turn.artifacts) == 1
    art = turn.artifacts[0]
    assert art.startswith('Changes in "Customer acquisition": v1 → v2')
    assert "```diff\n" in art and art.rstrip().endswith("```")
    lines = art.splitlines()
    assert "--- v1" in lines and "+++ v2" in lines
    assert "-Founder or operations lead" in lines
    assert "+Head of Customer Success" in lines
    assert "+Head of Customer Success" in _text(result)


def test_compare_briefs_named_campaign(stores):
    knowledge, briefs = stores
    briefs.save(make_draft(), "A1", "created", None, 0, "r")
    briefs.save(make_draft(), "B one\n", "created", None, 0, "r", campaign="Spring launch")
    briefs.save(make_draft(), "B two\n", "revised", 1, 0, "r", campaign="Spring launch")
    turn = TurnLog()
    tools = make_tools(knowledge, briefs, turn)
    run(
        tools["compare_briefs"].handler(
            {"from_version": 1, "to_version": 2, "campaign": "spring launch"}
        )
    )
    art = turn.artifacts[0]
    assert art.startswith('Changes in "Spring launch": v1 → v2')
    assert "-B one" in art.splitlines() and "+B two" in art.splitlines()


def test_compare_briefs_missing_version(stores):
    knowledge, briefs = stores
    briefs.save(make_draft(), "A1", "created", None, 0, "r")
    turn = TurnLog()
    tools = make_tools(knowledge, briefs, turn)
    result = run(tools["compare_briefs"].handler({"from_version": 1, "to_version": 3}))
    assert result["is_error"] is True
    assert "v3" in _text(result)
    assert turn.artifacts == [] and turn.actions == []


def test_compare_briefs_fence_survives_backticks_in_markdown(stores):
    knowledge, briefs = stores
    briefs.save(make_draft(), "a\n```\ncode\n```\n", "created", None, 0, "r")
    briefs.save(make_draft(), "b\n```\ncode\n```\n", "revised", 1, 0, "r")
    turn = TurnLog()
    run(
        make_tools(knowledge, briefs, turn)["compare_briefs"].handler(
            {"from_version": 1, "to_version": 2}
        )
    )
    art = turn.artifacts[0]
    assert "````diff\n" in art and art.rstrip().endswith("````")


# --- phase 3: AI checker wiring -------------------------------------------------------


def test_checker_problems_block_the_save(stores, monkeypatch):
    knowledge, briefs = stores
    calls = []

    async def fake_check(draft, knowledge_text, pricing_restricted, model=None):
        calls.append((draft, knowledge_text, pricing_restricted))
        return ["main_message: invented statistic", "buyer: contradicts knowledge"]

    monkeypatch.setattr(checker, "checker_enabled", lambda: True)
    monkeypatch.setattr(checker, "check_brief", fake_check)
    turn = TurnLog()
    result = run(
        make_tools(knowledge, briefs, turn)["save_brief"].handler(
            {"draft": make_draft().model_dump()}
        )
    )
    assert result["is_error"] is True
    text = _text(result)
    assert "Brief check found problems:" in text
    assert "invented statistic" in text and "contradicts knowledge" in text
    assert briefs.list() == [] and turn.actions == [] and turn.artifacts == []
    assert calls == [(make_draft(), knowledge.render(), knowledge.pricing_restricted)]


def test_checker_not_called_when_code_checks_fail(stores, monkeypatch):
    knowledge, briefs = stores
    calls = []

    async def fake_check(*a, **k):
        calls.append(a)
        return []

    monkeypatch.setattr(checker, "checker_enabled", lambda: True)
    monkeypatch.setattr(checker, "check_brief", fake_check)
    draft = make_draft(email_body=words(170)).model_dump()
    run(make_tools(knowledge, briefs, TurnLog())["save_brief"].handler({"draft": draft}))
    assert calls == []


def test_checker_none_saves_with_note(stores, monkeypatch):
    knowledge, briefs = stores

    async def fake_check(*a, **k):
        return None

    monkeypatch.setattr(checker, "checker_enabled", lambda: True)
    monkeypatch.setattr(checker, "check_brief", fake_check)
    turn = TurnLog()
    result = run(
        make_tools(knowledge, briefs, turn)["save_brief"].handler(
            {"draft": make_draft().model_dump()}
        )
    )
    assert not result.get("is_error")
    assert len(briefs.list()) == 1
    assert turn.actions == ['Brief "Customer acquisition" v1 saved (new)']
    assert (
        "Note: the AI brief check could not run; saved after the code checks only."
        in _text(result)
    )


def test_checker_empty_list_saves_without_note(stores, monkeypatch):
    knowledge, briefs = stores

    async def fake_check(*a, **k):
        return []

    monkeypatch.setattr(checker, "checker_enabled", lambda: True)
    monkeypatch.setattr(checker, "check_brief", fake_check)
    result = run(
        make_tools(knowledge, briefs, TurnLog())["save_brief"].handler(
            {"draft": make_draft().model_dump()}
        )
    )
    assert not result.get("is_error")
    assert len(briefs.list()) == 1
    assert "could not run" not in _text(result)


def test_checker_disabled_is_never_called(stores, monkeypatch):
    knowledge, briefs = stores

    async def boom(*a, **k):
        raise AssertionError("check_brief must not be called when disabled")

    monkeypatch.setattr(checker, "checker_enabled", lambda: False)
    monkeypatch.setattr(checker, "check_brief", boom)
    result = run(
        make_tools(knowledge, briefs, TurnLog())["save_brief"].handler(
            {"draft": make_draft().model_dump()}
        )
    )
    assert not result.get("is_error")
    assert len(briefs.list()) == 1


# --- phase 3 fix round ----------------------------------------------------------------


def _always_problems(monkeypatch, calls):
    async def fake_check(*a, **k):
        calls.append(a)
        return ["main_message: invented statistic"]

    monkeypatch.setattr(checker, "checker_enabled", lambda: True)
    monkeypatch.setattr(checker, "check_brief", fake_check)


def test_checker_rejections_capped_per_turn(stores, monkeypatch):
    knowledge, briefs = stores
    calls = []
    _always_problems(monkeypatch, calls)
    turn = TurnLog(user_text="make a brief")
    save = make_tools(knowledge, briefs, turn)["save_brief"].handler
    draft = {"draft": make_draft().model_dump()}
    for _ in range(2):
        result = run(save(draft))
        assert result["is_error"] is True
        assert "Brief check found problems:" in _text(result)
        assert briefs.list() == [] and turn.actions == []
    result = run(save(draft))
    assert not result.get("is_error")
    assert len(briefs.list()) == 1
    assert turn.actions == ['Brief "Customer acquisition" v1 saved (new)']
    text = _text(result)
    assert "The AI brief check still reported: main_message: invented statistic." in text
    assert "Saved after 2 rejected attempts; review these points." in text
    assert len(calls) == 3


def test_checker_rejection_count_resets_with_the_turn(stores, monkeypatch):
    knowledge, briefs = stores
    _always_problems(monkeypatch, [])
    turn = TurnLog(user_text="turn 1")
    save = make_tools(knowledge, briefs, turn)["save_brief"].handler
    draft = {"draft": make_draft().model_dump()}
    run(save(draft))
    run(save(draft))
    # Assistant.handle resets the turn in place (same user text twice must still reset)
    turn.user_text = "turn 1"
    turn.actions.clear()
    turn.artifacts.clear()
    assert run(save(draft))["is_error"] is True
    assert briefs.list() == []


def test_revise_without_campaign_uses_latest_briefs_campaign(stores):
    knowledge, briefs = stores
    briefs.save(make_draft(), "B1", "created", None, 0, "r", campaign="Spring launch")
    turn = TurnLog()
    tools = make_tools(knowledge, briefs, turn)
    result = run(tools["save_brief"].handler({"draft": make_draft().model_dump(), "revises": 1}))
    assert not result.get("is_error")
    assert turn.actions == ['Brief "Spring launch" v2 saved (revises v1)']
    # a new brief with no campaign still goes to the default campaign
    run(tools["save_brief"].handler({"draft": make_draft().model_dump()}))
    assert turn.actions[-1] == 'Brief "Customer acquisition" v1 saved (new)'

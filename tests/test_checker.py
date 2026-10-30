import asyncio
import os

import pytest

from startup_assistant import checker
from startup_assistant.contracts import BriefDraft, Channel
from startup_assistant.knowledge import KnowledgeStore


def make_draft(**overrides) -> BriefDraft:
    base = dict(
        title="Agency onboarding campaign",
        audience="Agencies and consultancies with 10-50 employees.",
        buyer="Founder or operations lead.",
        main_message=(
            "HarborDesk gives your team clearer ownership and visibility throughout customer "
            "onboarding, with shared checklists, task owners and reminders."
        ),
        channels=[
            Channel(name="LinkedIn posts", reason="Proposal: used before; no data on performance."),
            Channel(name="Targeted email outreach", reason="Proposal: used before; test it."),
        ],
        email_subject="Onboarding handoffs, without the spreadsheet",
        email_body=(
            "Hi, if client onboarding lives across email and spreadsheets, handoffs get missed. "
            "HarborDesk gives each task an owner, sends reminders and shows progress. "
            "Worth a short call?"
        ),
        assumptions=["Assumption: agency founders feel the handoff problem most."],
        open_questions=["Which channel should we test first?"],
    )
    base.update(overrides)
    return BriefDraft(**base)


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("value", ["0", "false", "off", "FALSE", "Off"])
def test_disabled_values(monkeypatch, value):
    monkeypatch.setenv("ASSISTANT_BRIEF_CHECK", value)
    assert checker.checker_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "on", ""])
def test_enabled_values(monkeypatch, value):
    monkeypatch.setenv("ASSISTANT_BRIEF_CHECK", value)
    assert checker.checker_enabled() is True


def test_enabled_when_unset(monkeypatch):
    monkeypatch.delenv("ASSISTANT_BRIEF_CHECK", raising=False)
    assert checker.checker_enabled() is True


def fake_ask(answer=None, exc=None, seen=None):
    async def _ask(prompt, system, model):
        if seen is not None:
            seen.append((prompt, system, model))
        if exc:
            raise exc
        return answer

    return _ask


def check(monkeypatch, answer=None, exc=None, seen=None, pricing=False, model=None):
    monkeypatch.setattr(checker, "_ask", fake_ask(answer, exc, seen))
    return run(checker.check_brief(make_draft(), "KNOWLEDGE TEXT", pricing, model))


def test_valid_json(monkeypatch):
    out = check(monkeypatch, '{"problems": ["main_message: invented stat", "email_body: x"]}')
    assert out == ["main_message: invented stat", "email_body: x"]


def test_empty_problems(monkeypatch):
    assert check(monkeypatch, '{"problems": []}') == []


def test_json_wrapped_in_prose(monkeypatch):
    assert check(monkeypatch, 'Sure! {"problems": ["a: b"]} Hope that helps.') == ["a: b"]


def test_json_in_code_fence(monkeypatch):
    assert check(monkeypatch, '```json\n{"problems": ["a: b"]}\n```') == ["a: b"]


def test_first_object_wins_and_nested_braces(monkeypatch):
    out = check(monkeypatch, 'x {"problems": ["a {curly} b"]} y {"problems": ["z"]}')
    assert out == ["a {curly} b"]


@pytest.mark.parametrize(
    "answer",
    [
        "no json here",
        "",
        "{not json}",
        '{"problems": "a string"}',
        '{"problems": [1, 2]}',
        '{"other": []}',
        '["a"]',
        None,
    ],
)
def test_garbage_returns_none(monkeypatch, answer):
    assert check(monkeypatch, answer) is None


def test_ask_raises_returns_none(monkeypatch):
    assert check(monkeypatch, exc=RuntimeError("boom")) is None


def test_timeout_returns_none(monkeypatch):
    async def slow(prompt, system, model):
        await asyncio.sleep(5)
        return '{"problems": []}'

    monkeypatch.setattr(checker, "_ask", slow)
    monkeypatch.setattr(checker, "TIMEOUT_S", 0.05)
    assert run(checker.check_brief(make_draft(), "K", False)) is None


def test_prompt_contents(monkeypatch):
    seen = []
    check(monkeypatch, '{"problems": []}', seen=seen, pricing=True)
    prompt, system, model = seen[0]
    draft = make_draft()
    assert "KNOWLEDGE TEXT" in prompt
    assert draft.model_dump_json(indent=2) in prompt
    assert "PRICING RESTRICTED: yes" in prompt
    assert system
    assert model == "claude-sonnet-5-5"


def test_prompt_unrestricted_marker(monkeypatch):
    seen = []
    check(monkeypatch, '{"problems": []}', seen=seen, pricing=False)
    assert "PRICING RESTRICTED: no" in seen[0][0]


def test_model_selection(monkeypatch):
    seen = []
    monkeypatch.setenv("ASSISTANT_CHECK_MODEL", "env-model")
    check(monkeypatch, '{"problems": []}', seen=seen)
    assert seen[-1][2] == "env-model"
    check(monkeypatch, '{"problems": []}', seen=seen, model="arg-model")
    assert seen[-1][2] == "arg-model"


# ---- live ----

live = pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="set RUN_LIVE=1")


def seed_knowledge_text(tmp_path, restricted: bool) -> str:
    store = KnowledgeStore(tmp_path / "knowledge.json")
    text = store.render()
    if restricted:
        text += (
            "\n\nPricing restricted: leave prices and any mention of pricing out of all "
            "campaign materials."
        )
    return text


def _live_check(draft, restricted, tmp_path, label):
    import time

    text = seed_knowledge_text(tmp_path, restricted)
    start = time.perf_counter()
    out = run(checker.check_brief(draft, text, restricted))
    print(f"\n[live:{label}] {time.perf_counter() - start:.1f}s -> {out}")
    return out


@pytest.mark.live
@live
def test_live_clean_brief(tmp_path):
    assert _live_check(make_draft(), False, tmp_path, "clean") == []


@pytest.mark.live
@live
def test_live_invented_stat(tmp_path):
    draft = make_draft(
        main_message="Acme Corp cut onboarding time by 40% with HarborDesk's shared checklists."
    )
    out = _live_check(draft, False, tmp_path, "invented-stat")
    assert out


@pytest.mark.live
@live
def test_live_pricing_hint(tmp_path):
    draft = make_draft(
        assumptions=["Assumption: commercial terms are left out while under review."]
    )
    out = _live_check(draft, True, tmp_path, "pricing-hint")
    assert out

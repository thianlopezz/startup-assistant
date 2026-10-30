"""Assistant.handle with a fake SDK client: turn cleanup and knowledge resend, no model."""

import asyncio

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from startup_assistant.agent import Assistant

FULL_KNOWLEDGE = "Company knowledge (v"
UNCHANGED = "Unchanged since v"


def _text(text: str) -> AssistantMessage:
    return AssistantMessage(content=[TextBlock(text=text)], model="fake")


def _result() -> ResultMessage:
    return ResultMessage(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
        session_id="fake",
    )


class _Hang:
    """Script step: block until cancelled."""


class FakeClient:
    """Stands in for ClaudeSDKClient. Each receive_response() call plays the next script:
    a list of messages, exceptions to raise, or _Hang."""

    def __init__(self):
        self.queries: list[str] = []
        self.interrupted = 0
        self.scripts: list[list] = []
        self.yielded: list = []

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def query(self, prompt: str):
        self.queries.append(prompt)

    async def interrupt(self):
        self.interrupted += 1

    async def receive_response(self):
        script = self.scripts.pop(0) if self.scripts else [_text("ok"), _result()]
        for step in script:
            if isinstance(step, BaseException):
                raise step
            if step is _Hang:
                await asyncio.Event().wait()
            self.yielded.append(step)
            yield step


class FakeClientAssistant(Assistant):
    def __init__(self, data_dir, client: FakeClient):
        super().__init__(data_dir)
        self.fake = client

    def _make_client(self):
        return self.fake


def _knowledge_section(prompt: str) -> str:
    return prompt.split("## Current company knowledge", 1)[1].split("## Saved briefs", 1)[0]


def test_error_mid_stream_interrupts_drains_and_reraises(tmp_path):
    client = FakeClient()
    leftover = [_text("late"), _result()]
    client.scripts = [[_text("partial"), RuntimeError("stream broke")], leftover]

    async def go():
        async with FakeClientAssistant(tmp_path, client) as assistant:
            with pytest.raises(RuntimeError, match="stream broke"):
                await assistant.handle("hello")

    asyncio.run(go())
    assert client.queries and "hello" in client.queries[0]
    assert client.interrupted == 1
    assert client.scripts == []  # the cleanup consumed the leftover response
    assert client.yielded[-2:] == leftover


def test_cancel_mid_stream_interrupts_drains_and_reraises(tmp_path):
    client = FakeClient()
    leftover = [_text("late"), _result()]
    client.scripts = [[_text("partial"), _Hang], leftover]

    async def go():
        async with FakeClientAssistant(tmp_path, client) as assistant:
            task = asyncio.create_task(assistant.handle("hello"))
            while not client.yielded:
                await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(go())
    assert client.interrupted == 1
    assert client.scripts == []
    assert client.yielded[-2:] == leftover


def test_knowledge_sent_only_when_changed(tmp_path):
    client = FakeClient()

    async def go():
        async with FakeClientAssistant(tmp_path, client) as assistant:
            await assistant.handle("turn 1")
            await assistant.handle("turn 2")
            assistant.knowledge.apply_update(
                source_text="We sell to clinics now.", summary="New audience",
                field_changes={"target_audience": "clinics"}, new_rules=[],
            )
            await assistant.handle("turn 3")
            await assistant.handle("turn 4")

    asyncio.run(go())
    q1, q2, q3, q4 = client.queries
    assert FULL_KNOWLEDGE in _knowledge_section(q1)
    assert _knowledge_section(q2).strip() == "Unchanged since v0 (sent earlier in this conversation)."
    assert FULL_KNOWLEDGE in _knowledge_section(q3) and "clinics" in _knowledge_section(q3)
    assert _knowledge_section(q4).strip() == "Unchanged since v1 (sent earlier in this conversation)."
    assert all("## Saved briefs" in q for q in client.queries)


def test_knowledge_resent_after_aborted_turn(tmp_path):
    client = FakeClient()
    client.scripts = [[_text("ok"), _result()], [RuntimeError("boom")], [_result()]]

    async def go():
        async with FakeClientAssistant(tmp_path, client) as assistant:
            await assistant.handle("turn 1")
            with pytest.raises(RuntimeError):
                await assistant.handle("turn 2")
            await assistant.handle("turn 3")

    asyncio.run(go())
    q1, q2, q3 = client.queries
    assert FULL_KNOWLEDGE in _knowledge_section(q1)
    assert UNCHANGED in _knowledge_section(q2)
    assert FULL_KNOWLEDGE in _knowledge_section(q3)


def test_knowledge_resent_after_compaction(tmp_path):
    client = FakeClient()

    async def go():
        async with FakeClientAssistant(tmp_path, client) as assistant:
            await assistant.handle("turn 1")
            await assistant.handle("turn 2")
            [matcher] = assistant._options().hooks["PreCompact"]
            [hook] = matcher.hooks
            out = await hook(
                {"hook_event_name": "PreCompact", "trigger": "auto", "custom_instructions": None,
                 "session_id": "fake", "transcript_path": "", "cwd": str(tmp_path)},
                None, {"signal": None},
            )
            assert isinstance(out, dict)
            await assistant.handle("turn 3")

    asyncio.run(go())
    q1, q2, q3 = client.queries
    assert FULL_KNOWLEDGE in _knowledge_section(q1)
    assert UNCHANGED in _knowledge_section(q2)
    assert FULL_KNOWLEDGE in _knowledge_section(q3)


# --- pricing guard on chat replies ---

PRICE_REPLY = "HarborDesk costs $299 per month."
CLEAN_REPLY = "Pricing is under review, so I can't quote a price."
NOTE = "_Note: pricing is under review; any figure above is not a current price._"


def _restrict(assistant):
    assistant.knowledge.apply_update(
        source_text="Pricing is under review.", summary="Pricing change",
        field_changes={"pricing": "Under review"}, new_rules=[],
    )


def _run_guarded(tmp_path, scripts, restricted=True):
    client = FakeClient()
    client.scripts = scripts

    async def go():
        async with FakeClientAssistant(tmp_path, client) as assistant:
            if restricted:
                _restrict(assistant)
            first = await assistant.handle("What does it cost?")
            await assistant.handle("and again?")
            return first

    return client, asyncio.run(go())


def test_restricted_price_reply_gets_one_followup_and_rewrite(tmp_path):
    client, reply = _run_guarded(tmp_path, [
        [_text(PRICE_REPLY), _result()],
        [_text(CLEAN_REPLY), _result()],
    ])
    assert len(client.queries) == 3  # turn 1, follow-up, turn 2
    followup = client.queries[1]
    assert followup.startswith(
        'Your last reply presented a price as current: "HarborDesk costs $299 per month".'
    )
    assert "Do not call any tools." in followup
    assert reply.text == CLEAN_REPLY


def test_followup_does_not_disturb_knowledge_resend(tmp_path):
    client, _ = _run_guarded(tmp_path, [
        [_text(PRICE_REPLY), _result()],
        [_text(CLEAN_REPLY), _result()],
        [_text(CLEAN_REPLY), _result()],
    ])
    q1, followup, q2 = client.queries
    assert FULL_KNOWLEDGE in _knowledge_section(q1)
    assert "## Current company knowledge" not in followup
    assert UNCHANGED in _knowledge_section(q2)


def test_restricted_still_bad_rewrite_appends_note(tmp_path):
    client, reply = _run_guarded(tmp_path, [
        [_text(PRICE_REPLY), _result()],
        [_text("Sorry: it is $299/mo."), _result()],
    ])
    assert len(client.queries) == 3  # never more than one follow-up
    assert reply.text == f"Sorry: it is $299/mo.\n\n{NOTE}"


def test_restricted_followup_error_keeps_original_with_note(tmp_path):
    client, reply = _run_guarded(tmp_path, [
        [_text(PRICE_REPLY), _result()],
        [RuntimeError("boom")],
    ])
    assert reply.text == f"{PRICE_REPLY}\n\n{NOTE}"
    assert client.interrupted == 1  # the broken follow-up was cleaned up
    assert len(client.queries) == 3


def test_not_restricted_no_followup(tmp_path):
    client, reply = _run_guarded(tmp_path, [[_text(PRICE_REPLY), _result()]], restricted=False)
    assert len(client.queries) == 2
    assert reply.text == PRICE_REPLY


def test_restricted_clean_reply_no_followup(tmp_path):
    client, reply = _run_guarded(tmp_path, [[_text(CLEAN_REPLY), _result()]])
    assert len(client.queries) == 2
    assert reply.text == CLEAN_REPLY


def test_followup_keeps_original_actions(tmp_path):
    client = FakeClient()
    client.scripts = [[_text(PRICE_REPLY), _result()], [_text(CLEAN_REPLY), _result()]]

    async def go():
        async with FakeClientAssistant(tmp_path, client) as assistant:
            _restrict(assistant)
            orig_query = client.query

            async def query(prompt):
                await orig_query(prompt)
                # a tool sneaking in during the follow-up must not leak into the reply
                assistant.turn.actions.append("first" if len(client.queries) == 1 else "sneaky")

            client.query = query
            return await assistant.handle("What does it cost?")

    assert asyncio.run(go()).actions == ["first"]

from startup_assistant.prompts import SYSTEM_PROMPT, build_turn_message


HEADINGS = ["## Current company knowledge", "## Saved briefs", "## Founder's message"]


def test_turn_message_sections():
    msg = build_turn_message("KNOWLEDGE", "INDEX", "Who is our buyer?", knowledge_version=1)
    positions = [msg.index(h) for h in HEADINGS]
    assert positions == sorted(positions)
    assert msg.index("KNOWLEDGE") < msg.index("INDEX") < msg.index("Who is our buyer?")
    assert msg.rstrip().endswith("Who is our buyer?")
    assert "Unchanged since" not in msg


def test_turn_message_unchanged_knowledge():
    msg = build_turn_message(None, "INDEX", "Who is our buyer?", knowledge_version=1)
    positions = [msg.index(h) for h in HEADINGS]
    assert positions == sorted(positions)
    section = msg.split("## Current company knowledge", 1)[1].split("## Saved briefs", 1)[0]
    assert section.strip() == "Unchanged since v1 (sent earlier in this conversation)."
    assert msg.index("Unchanged since v1") < msg.index("INDEX") < msg.index("Who is our buyer?")
    assert msg.rstrip().endswith("Who is our buyer?")


def test_system_prompt_covers_anti_goals():
    p = SYSTEM_PROMPT.lower()
    for phrase in (
        "testimonial",
        "statistic",
        "integration",
        "in half",
        "proposal",
        "pricing",
        "get_latest_brief",
        "save_brief",
        "update_company_knowledge",
        "150 words",
        "assumption",
        "open question",
    ):
        assert phrase in p, phrase

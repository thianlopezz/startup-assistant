from startup_assistant.prompts import SYSTEM_PROMPT, build_turn_message


def test_turn_message_sections():
    msg = build_turn_message("KNOWLEDGE", "INDEX", "Who is our buyer?")
    headings = ["## Current company knowledge", "## Saved briefs", "## Founder's message"]
    positions = [msg.index(h) for h in headings]
    assert positions == sorted(positions)
    assert msg.index("KNOWLEDGE") < msg.index("INDEX") < msg.index("Who is our buyer?")
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


def test_system_prompt_get_brief_and_implicit_pricing():
    p = SYSTEM_PROMPT.lower()
    assert "get_brief" in p
    assert "commercial terms" in p
    assert "under review" in p and "leave the topic out" in p

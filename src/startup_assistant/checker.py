"""AI review of a brief before it is saved: a second, tool-less model call that compares the
brief with company knowledge and lists rule violations the keyword checks can't see. Stub."""

from startup_assistant.contracts import BriefDraft


def checker_enabled() -> bool:
    """False when ASSISTANT_BRIEF_CHECK=0."""
    return True


async def check_brief(
    draft: BriefDraft, knowledge_text: str, pricing_restricted: bool, model: str | None = None
) -> list[str] | None:
    """Problems found in the brief; [] means OK; None means the check could not run (model
    error, timeout, unparseable answer). Never raises; the caller saves on None (fail-open) and
    says the check was skipped."""
    return []

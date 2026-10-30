import pytest
from pydantic import ValidationError

from startup_assistant.contracts import BriefDraft, Channel
from startup_assistant.seed import SEED_MARKETING_NOTES, SEED_PROFILE


def test_seed_keys():
    assert set(SEED_PROFILE) == {
        "company", "product", "capabilities", "target_customers", "primary_buyer",
        "problem", "main_benefit", "pricing", "brand_voice",
    }
    assert "$299" in SEED_PROFILE["pricing"]
    assert len(SEED_MARKETING_NOTES) == 5


def test_brief_requires_two_channels():
    with pytest.raises(ValidationError):
        BriefDraft(
            title="t", audience="a", buyer="b", main_message="m",
            channels=[Channel(name=f"c{i}", reason="r") for i in range(3)],
            email_subject="s", email_body="b", assumptions=[], open_questions=[],
        )

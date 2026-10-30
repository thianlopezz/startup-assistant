import pytest

from startup_assistant.reply_guard import current_price_claims


@pytest.mark.parametrize(
    "text",
    [
        "It starts at $299 per month.",
        "Plans cost $299/mo.",
        "We charge 299 per month.",
        "Billed at 299/month for everyone.",
        "The subscription is 299 a month.",
        "It's USD 299 monthly.",
        "Costs $ 299 today.",
    ],
)
def test_flags_current_prices(text):
    assert current_price_claims(text) == [text.rstrip(".")]


@pytest.mark.parametrize(
    "text",
    [
        "It used to start at $299 per month, but pricing is under review.",
        "Pricing is under review.",
        "We have 100–500 employees.",
        "The old price was $299.",
        "Previously $299/mo.",
        "It is no longer $299 a month.",
        "We send 4 updates per month.",
        "We run 4 per month.",  # number directly before "per month" (old false positive)
        "Expect 2 a month.",
        "Do 3/mo check-ins.",
        "Expect 2 check-ins a month.",
    ],
)
def test_ignores_past_or_unrelated(text):
    assert current_price_claims(text) == []


def test_splits_sentences_and_newlines():
    text = "Hello there!\nIt costs $299 per month. Pricing is under review? Yes.\n- $5/mo extra"
    assert current_price_claims(text) == ["It costs $299 per month", "- $5/mo extra"]


def test_empty():
    assert current_price_claims("") == []

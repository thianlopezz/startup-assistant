"""Pricing guard for chat replies: spot sentences that present a price as current."""

import re

_MONEY = re.compile(
    r"\$\s?\d"
    r"|\d\s*(?:/\s?mo(?:nth)?\b|per\s+month\b|a\s+month\b)",
    re.IGNORECASE,
)
# Past tense or "under review" wording means the sentence is not claiming a current price.
_PAST_OR_REVIEW = re.compile(
    r"\b(?:previous(?:ly)?|used\s+to|was|were|old|former|earlier|no\s+longer"
    r"|under\s+review|not\s+current|out\s+of\s+date)\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"[.!?\n]")


def current_price_claims(text: str) -> list[str]:
    """Sentences that state a price as current: a money amount and no past/under-review marker."""
    claims = []
    for sentence in _SENTENCE_END.split(text):
        sentence = sentence.strip()
        if sentence and _MONEY.search(sentence) and not _PAST_OR_REVIEW.search(sentence):
            claims.append(sentence)
    return claims

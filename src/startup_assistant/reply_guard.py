"""Pricing guard for chat replies: spot sentences that present a price as current."""

import re

_CURRENCY = re.compile(
    r"(?:[$€£]|\b(?:USD|EUR)\b)\s?\d"
    r"|\d\s?(?:(?:USD|EUR|dollars?|euros?|bucks)\b|[€£])",
    re.IGNORECASE,
)
_PER_PERIOD = re.compile(
    r"\d\s*(?:/\s?mo(?:nth)?\b|per\s+month\b|a\s+month\b|monthly\b)",
    re.IGNORECASE,
)
_MONEY_WORD = re.compile(
    r"\b(?:starts?\s+at|starting\s+at|prices?|pricing|costs?|charges?|fees?|plans?|subscriptions?|pay|paid|billed|billing)\b",
    re.IGNORECASE,
)
# Past tense or "under review" wording means the sentence is not claiming a current price.
_PAST_OR_REVIEW = re.compile(
    r"\b(?:previous(?:ly)?|used\s+to|was|were|old|former|earlier|no\s+longer"
    r"|under\s+review|not\s+current|out\s+of\s+date)\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"[.!?\n]")


def _is_price_claim(sentence: str, previous: str = "") -> bool:
    if _CURRENCY.search(sentence):
        return True
    if not _PER_PERIOD.search(sentence):
        return False
    if _MONEY_WORD.search(sentence):
        return True
    # Money word in the immediately preceding sentence, unless that one is past/under review.
    return bool(_MONEY_WORD.search(previous) and not _PAST_OR_REVIEW.search(previous))


def current_price_claims(text: str) -> list[str]:
    """Sentences that state a price as current: a money amount and no past/under-review marker."""
    claims = []
    previous = ""
    for sentence in _SENTENCE_END.split(text):
        sentence = sentence.strip()
        before, previous = previous, sentence or previous
        if sentence and _is_price_claim(sentence, before) and not _PAST_OR_REVIEW.search(sentence):
            claims.append(sentence)
    return claims

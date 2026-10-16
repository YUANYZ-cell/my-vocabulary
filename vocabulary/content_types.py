from __future__ import annotations


ITEM_TYPES = {"word", "phrase", "sentence"}
LONG_SENTENCE_MIN_WORDS = 5
LONG_SENTENCE_MIN_CHARS = 35


def infer_item_type(term: str) -> str:
    """Infer only when a caller did not explicitly choose a content type.

    The sentence threshold is deliberately conservative: short fixed phrases and
    compact everyday sentences stay in the phrase bucket, while clearly long
    expression patterns can be separated from them.
    """
    clean = " ".join(str(term or "").strip().split())
    if clean.casefold() == "game changer":
        return "word"
    if " " not in clean:
        return "word"
    if len(clean) >= LONG_SENTENCE_MIN_CHARS and len(clean.split()) >= LONG_SENTENCE_MIN_WORDS:
        return "sentence"
    return "phrase"

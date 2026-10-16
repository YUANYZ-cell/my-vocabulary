from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta


RATINGS = {"unrecalled", "forgot", "fuzzy", "remembered", "easy"}
RATING_ERROR_WEIGHTS = {"fuzzy": 1.0, "forgot": 1.5, "unrecalled": 2.0}


@dataclass(frozen=True)
class ReviewState:
    interval_days: int
    ease_factor: float
    successful_streak: int
    status: str
    review_count: int


@dataclass(frozen=True)
class ReviewResult:
    interval_days: int
    ease_factor: float
    successful_streak: int
    status: str
    next_review_at: date


def _round_interval(value: float) -> int:
    return max(1, min(180, math.floor(value + 0.5)))


def derive_status(interval_days: int, review_count: int, recent_ratings: list[str]) -> str:
    if review_count == 0:
        return "new"
    if recent_ratings and recent_ratings[-1] in {"forgot", "unrecalled"}:
        return "learning"
    if interval_days >= 45 and not {"forgot", "unrecalled"}.intersection(recent_ratings[-3:]):
        return "mastered"
    last_two = recent_ratings[-2:]
    if interval_days >= 14 and not (len(last_two) == 2 and all(rating in {"forgot", "unrecalled"} for rating in last_two)):
        return "familiar"
    return "learning"


def schedule_review(state: ReviewState, rating: str, today: date, recent_ratings: list[str]) -> ReviewResult:
    if rating not in RATINGS:
        raise ValueError("复习评分无效。")
    if rating in {"forgot", "unrecalled"}:
        interval, ease, streak = 1, max(1.3, state.ease_factor - 0.20), 0
    elif rating == "fuzzy":
        interval = 2 if state.review_count == 0 else _round_interval(max(2, state.interval_days * 0.60))
        ease, streak = max(1.3, state.ease_factor - 0.05), state.successful_streak
    elif rating == "remembered":
        interval = 4 if state.review_count == 0 else _round_interval(state.interval_days * 1.80)
        ease, streak = min(2.8, state.ease_factor + 0.05), state.successful_streak + 1
    else:
        interval = 7 if state.review_count == 0 else _round_interval(state.interval_days * 2.50)
        ease, streak = min(2.8, state.ease_factor + 0.10), state.successful_streak + 1
    ratings = [*recent_ratings[-2:], rating]
    status = derive_status(interval, state.review_count + 1, ratings)
    return ReviewResult(interval, ease, streak, status, today + timedelta(days=interval))


def normalize_spelling(value: str) -> str:
    return " ".join(value.strip().lower().split())


def spelling_matches(expected: str, actual: str) -> bool:
    return normalize_spelling(expected) == normalize_spelling(actual)


def make_cloze(term: str) -> str:
    words = term.strip().split()
    if len(words) > 1:
        hidden = {1}
        if len(words) >= 4:
            hidden.add(len(words) - 2)
        return " ".join("___" if index in hidden else word for index, word in enumerate(words))
    word = words[0] if words else ""
    if len(word) <= 2:
        return "_" * len(word)
    return "".join("_" if 0 < index < len(word) - 1 and index % 2 == 1 else char for index, char in enumerate(word))

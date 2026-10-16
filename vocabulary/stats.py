from __future__ import annotations

from contextlib import closing
from datetime import date, timedelta

from .database import Database
from .items import ValidationError
from .srs import RATING_ERROR_WEIGHTS


# The error map's four bands are the four slices of its ring, so the thresholds live beside the
# scan that feeds them rather than in the page. They are derived from the same two numbers the
# ranking prints (errors, error rate), which is what keeps the ring, the ranking and the totals
# describing one set of records instead of three.
ERROR_BANDS = (("high", "高频错词"), ("mid", "中频错词"), ("low", "低频错词"), ("rare", "偶发错误"))


def _is_error(row) -> bool:
    """A review counts as wrong when it was graded wrong or rated as a failed recall."""
    return row["first_try_correct"] == 0 or row["rating"] in {"forgot", "fuzzy", "unrecalled"}


def _error_band(errors: int, error_rate: int) -> str:
    if errors >= 4:
        return "high"
    if errors >= 2:
        return "mid"
    return "low" if error_rate >= 40 else "rare"


def _relative_change(current: int | float | None, previous: int | float | None) -> int | None:
    """Percentage change against the previous period, or None when there is nothing to compare."""
    if current is None or previous is None or not previous:
        return None
    return round((current - previous) / previous * 100)


class StatsRepository:
    def __init__(self, database: Database):
        self.database = database

    def dashboard(self, today: date) -> dict:
        start = today - timedelta(days=today.weekday())
        with closing(self.database.connect()) as connection:
            return {
                "total": connection.execute("SELECT COUNT(*) c FROM vocabulary_items").fetchone()["c"],
                "added_today": connection.execute(
                    "SELECT COUNT(*) c FROM vocabulary_items WHERE date(created_at)=?", (today.isoformat(),)
                ).fetchone()["c"],
                "due_today": connection.execute(
                    "SELECT COUNT(*) c FROM vocabulary_items WHERE next_review_at<=?", (today.isoformat(),)
                ).fetchone()["c"],
                "learned_this_week": connection.execute(
                    "SELECT COUNT(*) c FROM review_history WHERE date(reviewed_at)>=?", (start.isoformat(),)
                ).fetchone()["c"],
                "mastered": connection.execute(
                    "SELECT COUNT(*) c FROM vocabulary_items WHERE status='mastered'"
                ).fetchone()["c"],
            }

    def _error_rows(self, connection, start: str, end: str) -> list:
        """Every graded review in the window, ordered so streaks can be read straight off it."""
        return connection.execute(
            """SELECT h.item_id,v.term,v.chinese_meaning,h.reviewed_at,h.rating,h.first_try_correct
            FROM review_history h JOIN vocabulary_items v ON v.id=h.item_id
            WHERE date(h.reviewed_at) BETWEEN ? AND ?
            ORDER BY h.item_id,h.reviewed_at,h.id""",
            (start, end),
        ).fetchall()

    def _error_map(self, rows) -> dict:
        """Aggregate one window of reviews into the error map's ranking, totals and bands.

        One pass over the ordered rows produces all of it, so the ranking, the four figures and
        the ring can never disagree about which answers were wrong.
        """
        items: dict[int, dict] = {}
        attempts = 0
        for row in rows:
            attempts += 1
            entry = items.get(row["item_id"])
            if entry is None:
                entry = items[row["item_id"]] = {
                    "id": row["item_id"],
                    "term": row["term"],
                    "chinese_meaning": row["chinese_meaning"],
                    "attempts": 0,
                    "errors": 0,
                    "last_error_at": None,
                    "run": 0,
                    "runs": 0,
                    "run_length": 0,
                }
            entry["attempts"] += 1
            if _is_error(row):
                entry["errors"] += 1
                entry["run"] += 1
                entry["last_error_at"] = row["reviewed_at"]
            elif entry["run"]:
                # A correctly answered (or ungraded) review ends the current run of errors.
                entry["runs"] += 1
                entry["run_length"] += entry["run"]
                entry["run"] = 0
        words = []
        for entry in items.values():
            if entry["run"]:
                entry["runs"] += 1
                entry["run_length"] += entry["run"]
            if not entry["errors"]:
                continue
            entry["error_rate"] = round(entry["errors"] / entry["attempts"] * 100)
            entry["band"] = _error_band(entry["errors"], entry["error_rate"])
            words.append(entry)
        errors = sum(entry["errors"] for entry in words)
        runs = sum(entry["runs"] for entry in words)
        run_length = sum(entry["run_length"] for entry in words)
        # Errors first, then the rate, then how recently the word last went wrong. The second sort
        # is stable, so the more recent wording wins the ties the earlier one leaves open.
        words.sort(key=lambda entry: entry["last_error_at"] or "", reverse=True)
        words.sort(key=lambda entry: (entry["errors"], entry["error_rate"]), reverse=True)
        counts = {key: 0 for key, _ in ERROR_BANDS}
        for entry in words:
            counts[entry["band"]] += 1
        return {
            "attempts": attempts,
            "summary": {
                "errors": errors,
                "words": len(words),
                # Total errors over total attempts, not the mean of the per-word rates: one very
                # short word must not weigh as much as one practised twenty times.
                "error_rate": round(errors / attempts * 100) if attempts else None,
                # Mean length of a run of consecutive errors. A single isolated mistake is a run
                # of one, which is why a word that is only ever wrong once still counts here.
                "avg_streak": round(run_length / runs, 1) if runs else None,
            },
            "bands": [{"key": key, "label": label, "value": counts[key]} for key, label in ERROR_BANDS],
            "words": [
                {
                    "id": entry["id"],
                    "term": entry["term"],
                    "chinese_meaning": entry["chinese_meaning"],
                    "errors": entry["errors"],
                    "attempts": entry["attempts"],
                    "error_rate": entry["error_rate"],
                    "last_error_at": entry["last_error_at"],
                    "band": entry["band"],
                }
                for entry in words
            ],
        }

    def period(self, days: int | str, today: date) -> dict:
        all_time = days == "all"
        if not all_time and days not in {7, 30}:
            raise ValidationError("统计周期只能是 7 天、30 天或全部。")
        with closing(self.database.connect()) as connection:
            if all_time:
                first = connection.execute(
                    """SELECT MIN(day) day FROM (
                        SELECT date(created_at) day FROM vocabulary_items
                        UNION ALL SELECT date(reviewed_at) day FROM review_history
                    ) WHERE day IS NOT NULL"""
                ).fetchone()["day"]
                start = min(today, date.fromisoformat(first)) if first else today
                period_days = (today - start).days + 1
            else:
                period_days = int(days)
                start = today - timedelta(days=period_days - 1)
            added = {row["day"]: row["count"] for row in connection.execute(
                "SELECT date(created_at) day,COUNT(*) count FROM vocabulary_items "
                "WHERE date(created_at)>=? GROUP BY date(created_at)", (start.isoformat(),)
            )}
            reviewed = {row["day"]: row["count"] for row in connection.execute(
                "SELECT date(reviewed_at) day,COUNT(*) count FROM review_history "
                "WHERE date(reviewed_at)>=? GROUP BY date(reviewed_at)", (start.isoformat(),)
            )}
            mastered = connection.execute(
                "SELECT COUNT(*) c FROM vocabulary_items WHERE status='mastered'"
            ).fetchone()["c"]
            mistakes = [dict(row) for row in connection.execute(
                f"""SELECT v.id,v.term,v.chinese_meaning,COUNT(h.id) attempts,
                SUM(CASE WHEN h.first_try_correct=0 OR h.rating IN ('forgot','fuzzy','unrecalled') THEN 1 ELSE 0 END) errors,
                SUM(CASE
                    WHEN h.rating='unrecalled' THEN {RATING_ERROR_WEIGHTS['unrecalled']}
                    WHEN h.rating='forgot' THEN {RATING_ERROR_WEIGHTS['forgot']}
                    WHEN h.rating='fuzzy' OR h.first_try_correct=0 THEN {RATING_ERROR_WEIGHTS['fuzzy']}
                    ELSE 0.0 END) priority_score
                FROM vocabulary_items v JOIN review_history h ON h.item_id=v.id
                GROUP BY v.id HAVING errors>0 ORDER BY priority_score DESC,errors DESC,attempts DESC,v.term LIMIT 20"""
            )]
            status = {row["status"]: row["count"] for row in connection.execute(
                "SELECT status,COUNT(*) count FROM vocabulary_items GROUP BY status"
            )}
            # reviewed_at is written with an explicit UTC offset and SQLite normalises an
            # offset-bearing stamp to UTC before reading it, so a plain strftime('%H') would
            # describe UTC rather than the learner's clock. The offset is appended when it is
            # missing and handed back to the function, which lands each row in the block of the
            # day the learner actually practised.
            hours = {int(row["bucket"]): row["count"] for row in connection.execute(
                """SELECT CAST(strftime('%H', reviewed_at, substr(reviewed_at || '+00:00', 20, 6)) AS INTEGER)/6 bucket,
                COUNT(*) count FROM review_history WHERE date(reviewed_at)>=? GROUP BY bucket""",
                (start.isoformat(),),
            )}
            graded = {row["day"]: (int(row["graded"] or 0), int(row["correct"] or 0)) for row in connection.execute(
                """SELECT date(reviewed_at) day,
                SUM(CASE WHEN first_try_correct IS NOT NULL THEN 1 ELSE 0 END) graded,
                SUM(CASE WHEN first_try_correct=1 THEN 1 ELSE 0 END) correct
                FROM review_history WHERE date(reviewed_at)>=? GROUP BY date(reviewed_at)""",
                (start.isoformat(),),
            )}
            window = connection.execute(
                """SELECT SUM(CASE WHEN first_try_correct IS NOT NULL THEN 1 ELSE 0 END) graded,
                SUM(CASE WHEN first_try_correct=1 THEN 1 ELSE 0 END) correct
                FROM review_history WHERE date(reviewed_at) BETWEEN ? AND ?""",
                ((today - timedelta(days=6)).isoformat(), today.isoformat()),
            ).fetchone()
            prior = connection.execute(
                """SELECT SUM(CASE WHEN first_try_correct IS NOT NULL THEN 1 ELSE 0 END) graded,
                SUM(CASE WHEN first_try_correct=1 THEN 1 ELSE 0 END) correct
                FROM review_history WHERE date(reviewed_at) BETWEEN ? AND ?""",
                ((today - timedelta(days=13)).isoformat(), (today - timedelta(days=7)).isoformat()),
            ).fetchone()
            error_rows = self._error_rows(connection, start.isoformat(), today.isoformat())
            if all_time:
                # Nothing precedes the first day of the collection, so the map reports no change
                # rather than comparing against a window that cannot exist.
                previous_rows, previous_window = None, None
            else:
                previous_end = start - timedelta(days=1)
                previous_start = previous_end - timedelta(days=period_days - 1)
                previous_rows = self._error_rows(connection, previous_start.isoformat(), previous_end.isoformat())
                previous_window = {"start": previous_start.isoformat(), "end": previous_end.isoformat()}
        error_map = self._error_map(error_rows)
        error_map["days"] = "all" if all_time else period_days
        error_map["start"] = start.isoformat()
        error_map["end"] = today.isoformat()
        error_map["previous"] = previous_window
        error_map["deltas"] = {key: None for key in ("errors", "words", "error_rate", "avg_streak")}
        if previous_rows is not None:
            prior_map = self._error_map(previous_rows)["summary"]
            error_map["deltas"] = {
                key: _relative_change(error_map["summary"][key], prior_map[key])
                for key in ("errors", "words", "error_rate", "avg_streak")
            }
        series, accuracy = [], []
        for offset in range(period_days):
            day = (start + timedelta(days=offset)).isoformat()
            series.append({"date": day, "added": added.get(day, 0), "reviews": reviewed.get(day, 0)})
            attempts, correct = graded.get(day, (0, 0))
            accuracy.append({"date": day, "attempts": attempts, "correct": correct})
        for item in mistakes:
            item["error_rate"] = round(item["errors"] / item["attempts"] * 100)

        def accuracy_rate(row: dict | None) -> int | None:
            if not row or not row["graded"]:
                return None
            return round(int(row["correct"] or 0) / int(row["graded"]) * 100)

        recent_rate, prior_rate = accuracy_rate(window), accuracy_rate(prior)
        return {
            "days": "all" if all_time else period_days,
            "series": series,
            "mastered": mastered,
            "mistakes": mistakes,
            "status": status,
            "hours": [
                {"label": label, "reviews": hours.get(index, 0)}
                for index, label in enumerate(("0–6时", "6–12时", "12–18时", "18–24时"))
            ],
            "accuracy": accuracy,
            "accuracy_summary": {
                "rate": recent_rate,
                "delta": None if recent_rate is None or prior_rate is None else recent_rate - prior_rate,
            },
            # The error map is windowed like everything else on the page. `mistakes` above is kept
            # for the all-time top list it always was, so a page served from a warm cache keeps
            # rendering its own card instead of silently losing the list it expected.
            "error_map": error_map,
        }

    def activity(self, today: date, days: int = 371) -> dict:
        if days < 28 or days > 371:
            raise ValidationError("活跃记录周期只能在 28 到 371 天之间。")
        start = today - timedelta(days=days - 1)
        with closing(self.database.connect()) as connection:
            additions = {
                row["day"]: row["count"]
                for row in connection.execute(
                    "SELECT date(created_at) day,COUNT(*) count FROM vocabulary_items "
                    "WHERE date(created_at)>=? AND date(created_at)<=? GROUP BY date(created_at)",
                    (start.isoformat(), today.isoformat()),
                )
            }
            reviews = {
                row["day"]: dict(row)
                for row in connection.execute(
                    """SELECT date(reviewed_at) day,COUNT(*) reviews,
                    SUM(CASE
                        WHEN rating='unrecalled' THEN 4
                        WHEN first_try_correct=0 OR rating IN ('forgot','fuzzy') THEN 3
                        WHEN affects_schedule=1 THEN 2
                        ELSE 1
                    END) review_score,
                    SUM(CASE WHEN first_try_correct IS NOT NULL THEN 1 ELSE 0 END) graded,
                    SUM(CASE WHEN first_try_correct=1 THEN 1 ELSE 0 END) correct
                    FROM review_history
                    WHERE date(reviewed_at)>=? AND date(reviewed_at)<=?
                    GROUP BY date(reviewed_at)""",
                    (start.isoformat(), today.isoformat()),
                )
            }
            expression_reads = {
                row["day"]: row["count"]
                for row in connection.execute(
                    "SELECT date(opened_at) day,COUNT(*) count FROM expression_read_history "
                    "WHERE date(opened_at)>=? AND date(opened_at)<=? GROUP BY date(opened_at)",
                    (start.isoformat(), today.isoformat()),
                )
            }

        series = []
        for offset in range(days):
            day = (start + timedelta(days=offset)).isoformat()
            added = additions.get(day, 0)
            review = reviews.get(day, {"reviews": 0, "review_score": 0, "graded": 0, "correct": 0})
            reading = expression_reads.get(day, 0)
            # Reading remains outside word accuracy and review totals, but it is still genuine
            # learning activity. One opened expression contributes one lightweight activity point.
            score = added * 2 + int(review["review_score"] or 0) + reading
            series.append({
                "date": day,
                "added": added,
                "reviews": review["reviews"],
                "expression_reads": reading,
                "score": score,
                "graded": int(review["graded"] or 0),
                "correct": int(review["correct"] or 0),
            })

        active_days = sum(point["score"] > 0 for point in series)
        current_streak = 0
        for point in reversed(series):
            if point["score"] <= 0:
                break
            current_streak += 1
        longest_streak = running = 0
        for point in series:
            running = running + 1 if point["score"] > 0 else 0
            longest_streak = max(longest_streak, running)
        return {
            "days": days,
            "series": series,
            "active_days": active_days,
            "current_streak": current_streak,
            "longest_streak": longest_streak,
        }

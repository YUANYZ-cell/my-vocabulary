from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from typing import Any

from .items import ValidationError


CATEGORIES = ("口语", "俚语", "习语", "谚语", "词汇")
LIMITS = {"phrase": 240, "meaning": 1000, "category": 20,
          "pronunciation": 240, "example": 2000, "translation": 2000,
          "usage": 2000, "source": 1000}

# Meanings, usage notes and examples are written for this app. Seed keys keep
# initialization idempotent and preserve later edits and favorites.
STARTER_EXPRESSIONS = (
    ("tomayto-tomahto", "Tomayto, tomahto.", "说法不同，但差别不大；差不多一回事。", "口语",
     "tə-MAY-toh / tə-MAH-toh（/təˈmeɪtoʊ/ / /təˈmɑːtəʊ/）",
     'A: It is a sofa, not a couch.\nB: Tomayto, tomahto.',
     "甲：这是 sofa，不是 couch。\n乙：叫法不一样，差不多啦。",
     "借 tomato 的两种读音开玩笑；也常写成 Tomato, tomahto。适合轻松聊天，认真讨论时可能让人觉得你不重视差别。",
     "https://grammarist.com/usage/tomayto-tomahto-and-potayto-potahto/"),
    ("same-difference", "Same difference.", "还不是一样；那点区别不重要。", "口语", "",
     'A: We waited twenty minutes, not nineteen.\nB: Same difference.',
     "甲：我们等了二十分钟，不是十九分钟。\n乙：差不多啦。",
     "回应细小差别时用。语气随意，有时带一点不以为然。", ""),
    ("fair-enough", "Fair enough.", "有道理；可以理解；那也行。", "口语", "",
     'A: I would rather stay home tonight.\nB: Fair enough.',
     "甲：今晚我更想待在家里。\n乙：可以理解。",
     "接受对方的理由或选择，不一定表示你完全赞同。", ""),
    ("no-worries", "No worries.", "没关系；别担心；不客气。", "口语", "",
     'A: Sorry I am a little late.\nB: No worries. We have not started yet.',
     "甲：抱歉，我迟到了几分钟。\n乙：没关系，我们还没开始。",
     "轻松回应道歉或感谢。含义随上下文变化。", ""),
    ("sounds-good", "Sounds good.", "听起来不错；好啊，就这样。", "口语", "",
     'A: Shall we meet at six?\nB: Sounds good.',
     "甲：六点见怎么样？\n乙：好啊。",
     "对建议或安排表示同意，日常聊天中很常见。", ""),
    ("you-bet", "You bet!", "当然；肯定；不客气。", "口语", "",
     'A: Can you help me carry this?\nB: You bet!',
     "甲：能帮我搬一下这个吗？\n乙：当然！",
     "语气热情、随意，常见于美式口语；也可用来回应感谢。", ""),
    ("my-bad", "My bad.", "我的错；是我搞错了。", "俚语", "",
     'I sent you the wrong address. My bad.', "我发错地址了，我的错。",
     "用于小失误的随意道歉。严重过错或正式场合应更认真地道歉。", ""),
    ("im-down", "I’m down.", "我愿意；算我一个。", "俚语", "",
     'A: Want to get pizza after work?\nB: I’m down.',
     "甲：下班后去吃披萨吗？\n乙：算我一个。",
     "回应邀请时表示愿意参加；常用 I’m down for that。其他语境中 down 也可能表示低落。", ""),
    ("no-biggie", "No biggie.", "没什么大不了；小事一桩。", "俚语", "",
     'You forgot your pen? No biggie. You can use mine.',
     "忘带笔了？没事，用我的就好。",
     "非常随意的说法，适合朋友之间；正式说法可用 It’s not a problem。", ""),
    ("hang-out", "Hang out.", "一起待着、闲逛或玩。", "俚语", "",
     'We usually hang out at the café on Saturdays.',
     "我们周六通常在咖啡馆聚一聚。",
     "强调轻松相处，不一定有具体活动；与人一起可说 hang out with someone。", ""),
    ("chill-out", "Chill out.", "放松一下；冷静点。", "俚语", "",
     'Let’s chill out at home this evening.', "今晚在家放松一下吧。",
     "谈休息时很自然；直接对生气的人说 Chill out! 可能显得不耐烦。", ""),
    ("catch-you-later", "Catch you later!", "回头见！", "俚语", "",
     'I have to head home. Catch you later!', "我得回家了，回头见！",
     "朋友之间随意的告别，通常不表示已经约好具体时间。", ""),
    ("piece-of-cake", "A piece of cake.", "轻而易举的事；小菜一碟。", "习语", "",
     'The setup was a piece of cake. It only took five minutes.',
     "安装很简单，只花了五分钟。", "形容事情很容易，不是字面上的一块蛋糕。", ""),
    ("under-the-weather", "Under the weather.", "身体不太舒服。", "习语", "",
     'I’m feeling under the weather, so I’ll stay home today.',
     "我有点不舒服，今天就待在家里了。", "常指轻微不适，不具体说明是什么病。", ""),
    ("break-the-ice", "Break the ice.", "打破沉默；让气氛轻松起来。", "习语", "",
     'She told a funny story to break the ice.',
     "她讲了个有趣的故事，缓和了陌生人之间的拘谨。",
     "常用于初次见面、聚会或会议开始时。", ""),
    ("on-the-same-page", "On the same page.", "理解一致；想法或安排对齐。", "习语", "",
     'Let’s check the plan so we’re on the same page.',
     "我们确认一下计划，确保大家理解一致。",
     "既可用于日常聊天，也常用于工作沟通。", ""),
    ("call-it-a-day", "Call it a day.", "今天就到这里；收工。", "习语", "",
     'We’ve done enough for today. Let’s call it a day.',
     "今天已经做得够多了，就到这里吧。", "结束当天或当前阶段的工作，不表示永远放弃。", ""),
    ("spill-the-beans", "Spill the beans.", "泄露秘密；把内情说出来。", "习语", "",
     'Don’t spill the beans about the surprise party.',
     "别把惊喜派对的事说漏嘴了。", "可以是无意泄密，也可以是被人追问后透露。", ""),
    ("better-late", "Better late than never.", "迟做总比不做好。", "谚语", "",
     'I finally replied to that email. Better late than never.',
     "我终于回复了那封邮件，迟回总比不回好。",
     "可以安慰别人，也可以自嘲；不宜用来敷衍严重的延误。", ""),
    ("actions-speak", "Actions speak louder than words.", "行动比言语更有说服力。", "谚语", "",
     'He promised to help, but actions speak louder than words.',
     "他说会帮忙，但还是要看实际行动。", "强调兑现承诺和实际行为。", ""),
    ("judge-a-book", "Don’t judge a book by its cover.", "别以貌取人；别只看表面。", "谚语", "",
     'The café looks plain, but the food is great. Don’t judge a book by its cover.',
     "这家咖啡馆看着普通，食物却很好吃，别只看表面。",
     "既可形容人，也可形容地点或事物。", ""),
    ("when-in-rome", "When in Rome, do as the Romans do.", "入乡随俗。", "谚语", "",
     'Everyone takes their shoes off here. When in Rome, do as the Romans do.',
     "这里大家都脱鞋，那就入乡随俗吧。", "聊天时也常缩短为 When in Rome。", ""),
    ("silver-lining", "Every cloud has a silver lining.", "困难中也可能有好的一面。", "谚语", "",
     'The trip was canceled, but we got a quiet weekend together. Every cloud has a silver lining.',
     "旅行取消了，不过我们一起过了个安静的周末，也算有好的一面。",
     "用于乐观地看待挫折；别人正难过时，要先理解对方感受。", ""),
    ("two-heads", "Two heads are better than one.", "两个人一起想，往往比一个人更好。", "谚语", "",
     'Let’s work on this together. Two heads are better than one.',
     "我们一起解决吧，多一个人多一份思路。", "用来邀请合作、讨论或共同解决问题。", ""),
)


def seed_daily_expressions(connection: sqlite3.Connection) -> None:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    connection.executemany(
        """INSERT INTO daily_expressions
           (seed_key, phrase, meaning, category, pronunciation, example,
            translation, usage, source, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(seed_key) DO NOTHING""",
        [(*entry, now, now) for entry in STARTER_EXPRESSIONS],
    )


class DailyExpressionRepository:
    """Only this table is writable; browsing never creates learning activity."""

    def __init__(self, database):
        self.database = database

    @staticmethod
    def _item(row):
        if row is None:
            return None
        item = dict(row)
        item["is_favorite"] = bool(item["is_favorite"])
        return item

    def list_items(self, deleted: bool = False) -> dict:
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM daily_expressions WHERE moved_at IS NULL AND deleted_at IS "
                + ("NOT NULL ORDER BY deleted_at DESC, id DESC" if deleted else
                   "NULL ORDER BY seed_key IS NULL DESC, id ASC")
            ).fetchall()
            deleted_total = connection.execute(
                "SELECT count(*) FROM daily_expressions WHERE moved_at IS NULL AND deleted_at IS NOT NULL"
            ).fetchone()[0]
        return {"items": [self._item(row) for row in rows], "total": len(rows),
                "deleted_total": deleted_total}

    def get_item(self, item_id: int) -> dict | None:
        with closing(self.database.connect()) as connection:
            return self._item(connection.execute(
                "SELECT * FROM daily_expressions WHERE id=? AND moved_at IS NULL AND deleted_at IS NULL", (item_id,)
            ).fetchone())

    def delete_item(self, item_id: int) -> bool:
        # Retain the row and seed_key: startup must not recreate deleted starter content.
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE daily_expressions SET deleted_at=? WHERE id=? AND moved_at IS NULL AND deleted_at IS NULL",
                (datetime.now().astimezone().isoformat(timespec="seconds"), item_id),
            )
        return bool(cursor.rowcount)

    def restore_item(self, item_id: int) -> dict | None:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE daily_expressions SET deleted_at=NULL WHERE id=? AND moved_at IS NULL AND deleted_at IS NOT NULL",
                (item_id,),
            )
        return self.get_item(item_id) if cursor.rowcount else None

    def save_item(self, payload: dict, item_id: int | None = None) -> dict | None:
        existing = self.get_item(item_id) if item_id is not None else None
        if item_id is not None and existing is None:
            return None
        merged = {**(existing or {}), **payload}
        values: dict[str, Any] = {}
        for field, limit in LIMITS.items():
            value = merged.get(field, "")
            if not isinstance(value, str):
                raise ValidationError("日常表达的文字字段必须是文本。")
            values[field] = value.strip()
            if len(values[field]) > limit:
                raise ValidationError("日常表达的内容过长。")
        if not values["phrase"] or not values["meaning"]:
            raise ValidationError("请填写英文表达和中文意思。")
        if values["category"] not in CATEGORIES:
            raise ValidationError("请选择口语、俚语、习语、谚语或词汇。")
        if not isinstance(merged.get("is_favorite", False), bool):
            raise ValidationError("收藏状态无效。")
        values["is_favorite"] = int(merged.get("is_favorite", False))
        values["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.database.transaction() as connection:
            group_id = merged.get("group_id")
            if group_id in (None, ""):
                group_id = None
            else:
                if isinstance(group_id, bool) or not str(group_id).isdigit() or int(group_id) <= 0:
                    raise ValidationError("合集无效，请重新选择。")
                group_id = int(group_id)
                if not connection.execute("SELECT 1 FROM daily_groups WHERE id=?", (group_id,)).fetchone():
                    raise ValidationError("合集不存在，请重新选择。")
            values["group_id"] = group_id
            if item_id is None:
                values["created_at"] = values["updated_at"]
                columns = ", ".join(values)
                marks = ", ".join("?" for _ in values)
                cursor = connection.execute(
                    f"INSERT INTO daily_expressions ({columns}) VALUES ({marks})", tuple(values.values())
                )
                item_id = cursor.lastrowid
            else:
                assignments = ", ".join(f"{field}=?" for field in values)
                connection.execute(
                    f"UPDATE daily_expressions SET {assignments} WHERE id=? AND moved_at IS NULL AND deleted_at IS NULL",
                    (*values.values(), item_id),
                )
        return self.get_item(item_id)

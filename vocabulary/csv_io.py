from __future__ import annotations

import csv
import io
from contextlib import closing

from .items import DuplicateItemError, ItemRepository, ValidationError, category_clause, normalize_term


COLUMNS = [
    ("单词 / 短语 / 长句", "term"), ("中文释义", "chinese_meaning"), ("音标", "phonetic"),
    ("词性", "part_of_speech"), ("英文释义", "english_definition"), ("原句", "source_sentence"),
    ("我的例句", "own_sentence"), ("常见搭配", "collocations"), ("来源", "source"),
    ("同义词 / 替换词", "synonyms"), ("词条类型", "item_type"), ("所属词库", "collection"),
    ("学术分类", "academic_category_name"),
    ("标签", "tags"), ("备注", "notes"), ("掌握状态", "status"),
]


class CsvImportError(ValueError):
    pass


class CsvService:
    def __init__(self, items: ItemRepository):
        self.items = items

    @staticmethod
    def _encode(rows: list[dict]) -> bytes:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=[label for label, _ in COLUMNS])
        writer.writeheader()
        writer.writerows(rows)
        return stream.getvalue().encode("utf-8-sig")

    def template(self) -> bytes:
        return self._encode([])

    def export_items(self, collection: str | None = None, category_id: object = None) -> bytes:
        rows = []
        data = [item for item in self.items.all_items() if collection is None or item["collection"] == collection]
        for item in self.items.filter_category(data, collection or "all", category_id):
            row = {}
            for label, field in COLUMNS:
                value = item.get(field, "")
                row[label] = " | ".join(value) if isinstance(value, list) else value
            rows.append(row)
        return self._encode(rows)

    @staticmethod
    def _decode(content: bytes) -> str:
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise CsvImportError("无法读取 CSV，请在表格软件中另存为 UTF-8 CSV。")

    def import_bytes(self, content: bytes, collection: str | None = None, category_id: object = None) -> dict:
        if not content:
            raise CsvImportError("请选择包含数据的 CSV 文件。")
        reader = csv.DictReader(io.StringIO(self._decode(content)))
        term_column = next(
            (name for name in (COLUMNS[0][0], "单词 / 词块") if reader.fieldnames and name in reader.fieldnames),
            None,
        )
        if not reader.fieldnames or not term_column or COLUMNS[1][0] not in reader.fieldnames:
            raise CsvImportError("CSV 缺少“单词 / 短语 / 长句”或“中文释义”列。")
        with closing(self.items.database.connect()) as connection:
            selected_clause, selected_params = category_clause(connection, collection or "all", category_id)
            selected_name = connection.execute("SELECT name FROM academic_categories WHERE id=?", selected_params).fetchone()["name"] if selected_params else ""
        result = {"created": 0, "skipped": 0, "failed": 0, "errors": []}
        reverse = {**dict(COLUMNS), "单词 / 词块": "term"}
        for row_number, row in enumerate(reader, start=2):
            payload = {}
            for label, value in row.items():
                field = reverse.get(label)
                if not field:
                    continue
                clean = (value or "").strip()
                payload[field] = [part.strip() for part in clean.split("|") if part.strip()] if field in {"tags", "collocations", "synonyms"} else clean
            try:
                if collection is not None:
                    if payload.get("collection") and payload["collection"] != collection:
                        raise ValidationError("CSV 词库与当前导入的词库不一致。")
                    payload["collection"] = collection
                if selected_clause:
                    if payload.get("academic_category_name") and normalize_term(payload["academic_category_name"]) != normalize_term(selected_name):
                        raise ValidationError("CSV 学术分类与当前分类不一致，请在“全部学术词汇”中导入。")
                    payload.pop("academic_category_name", None)
                    payload["academic_category_id"] = selected_params[0] if selected_params else None
                self.items.create_item(payload)
                result["created"] += 1
            except DuplicateItemError:
                result["skipped"] += 1
            except ValidationError as error:
                result["failed"] += 1
                result["errors"].append({"row": row_number, "message": str(error)})
        return result

"""Import a reviewed everyday intake once; retain later edits, deletion and moves."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vocabulary.database import Database
from vocabulary.daily_expressions import LIMITS, CATEGORIES


def import_groups(database_path, source_path):
    intake = json.loads(Path(source_path).read_text(encoding='utf-8'))
    keys = []
    for group in intake['groups']:
        if not isinstance(group['name'], str) or not 1 <= len(group['name'].strip()) <= 80:
            raise ValueError('Invalid group name')
        for item in group['items']:
            keys.append(item['import_key'])
            for field, limit in LIMITS.items():
                if not isinstance(item.get(field, ''), str) or len(item.get(field, '')) > limit:
                    raise ValueError(f'Invalid {field}')
            if not item['phrase'].strip() or not item['meaning'].strip() or item['category'] not in CATEGORIES:
                raise ValueError('Missing or invalid content')
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate intake keys')
    database = Database(database_path)
    database.initialize()
    now = datetime.now().astimezone().isoformat(timespec='seconds')
    result = []
    with database.transaction() as connection:
        for group in intake['groups']:
            normalized = group['name'].strip().casefold()
            row = connection.execute('SELECT id FROM daily_groups WHERE normalized_name=?', (normalized,)).fetchone()
            group_id = row['id'] if row else connection.execute(
                'INSERT INTO daily_groups(name,normalized_name,created_at,updated_at) VALUES(?,?,?,?)',
                (group['name'].strip(), normalized, now, now)).lastrowid
            added = 0
            for item in group['items']:
                key = item['import_key']
                if connection.execute('SELECT 1 FROM daily_expressions WHERE seed_key=?', (key,)).fetchone():
                    continue
                existing = connection.execute('SELECT * FROM daily_expressions WHERE lower(phrase)=lower(?) AND meaning=? AND deleted_at IS NULL AND moved_at IS NULL', (item['phrase'], item['meaning'])).fetchone()
                if existing:
                    # Existing content is never overwritten; an ungrouped exact match can join this collection.
                    if existing['group_id'] is None:
                        connection.execute('UPDATE daily_expressions SET group_id=? WHERE id=?', (group_id, existing['id']))
                    continue
                values = {field: item.get(field, '').strip() for field in LIMITS}
                values.update(seed_key=key, group_id=group_id, created_at=now, updated_at=now)
                connection.execute(f'INSERT INTO daily_expressions ({",".join(values)}) VALUES ({",".join("?" for _ in values)})', tuple(values.values()))
                added += 1
            total = connection.execute('SELECT count(*) FROM daily_expressions WHERE group_id=? AND deleted_at IS NULL AND moved_at IS NULL', (group_id,)).fetchone()[0]
            result.append(dict(id=group_id, name=group['name'], added=added, total=total))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--source', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(import_groups(args.database, args.source), ensure_ascii=False, indent=2))

"""Import completed fixed observations; never overwrite an existing patrol record."""
from .battle_timeline import SCHEMA
import json
import sqlite3
from pathlib import Path

def import_finished(source, target):
    source, target = Path(source), Path(target)
    if not source.exists():
        return {'imported': 0, 'skipped': 0}
    if not target.exists():
        raise ValueError('先に通常のPulseで収集を開始してください（取込先DBがありません）')
    counts = {'imported': 0, 'skipped': 0}
    with sqlite3.connect(source, timeout=10) as src, sqlite3.connect(target, timeout=10) as dst:
        dst.execute('PRAGMA busy_timeout=10000')
        dst.execute('BEGIN IMMEDIATE')
        dst.execute(SCHEMA)
        dst.execute('CREATE TABLE IF NOT EXISTS observation_sources (unique_id TEXT, battle_id INTEGER, source TEXT, PRIMARY KEY(unique_id,battle_id,source))')
        for row in src.execute("SELECT * FROM battles WHERE status='finished'"):
            uid,bid,first,last,status,raw = row
            payload = json.loads(raw)
            if payload.get('exclusion_flag') or payload.get('gameplay_option') == 'MATCH_OPTION_SPECIFIC_GIFT':
                counts['skipped'] += 1
                continue
            if dst.execute('SELECT 1 FROM battles WHERE unique_id=? AND battle_id=?',(uid,bid)).fetchone() or dst.execute('SELECT 1 FROM excluded_battles WHERE unique_id=? AND battle_id=?',(uid,bid)).fetchone():
                counts['skipped'] += 1
                continue
            dst.execute('INSERT INTO battles VALUES (?,?,?,?,?,?)', row)
            for table in ('snapshots','comments','viewer_samples'):
                for item in src.execute(f'SELECT * FROM {table} WHERE unique_id=? AND battle_id=?',(uid,bid)):
                    dst.execute(f'INSERT OR IGNORE INTO {table} VALUES ({",".join("?" for _ in item)})',item)
            dst.execute('INSERT OR IGNORE INTO observation_sources VALUES (?,?,?)',(uid,bid,'fixed'))
            counts['imported'] += 1
        if src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='battle_timeline'").fetchone():
            for event in src.execute('SELECT * FROM battle_timeline'):
                if dst.execute('SELECT 1 FROM battles WHERE unique_id=? AND battle_id=?', event[:2]).fetchone():
                    dst.execute('INSERT OR IGNORE INTO battle_timeline VALUES (?,?,?,?,?,?)', event)
    return counts

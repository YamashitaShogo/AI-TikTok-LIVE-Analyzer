"""Private, local observation notes, separate from collected comments."""
import sqlite3
import time
from pathlib import Path

class BattleNotes:
    def __init__(self, collection_database):
        self.path = Path(collection_database).with_name('battle_notes.sqlite3')

    def load(self, unique_id, battle_id):
        if not self.path.exists(): return ''
        with sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2) as db:
            row=db.execute('SELECT note FROM battle_notes WHERE unique_id=? AND battle_id=?',(str(unique_id),int(battle_id))).fetchone()
        return row[0] if row else ''

    def save(self, unique_id, battle_id, note):
        if not unique_id or int(battle_id)<=0: raise ValueError('バトルが未選択です')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path,timeout=2) as db:
            db.execute('CREATE TABLE IF NOT EXISTS battle_notes(unique_id TEXT NOT NULL,battle_id INTEGER NOT NULL,note TEXT NOT NULL,updated_at REAL NOT NULL,PRIMARY KEY(unique_id,battle_id))')
            db.execute('INSERT INTO battle_notes VALUES(?,?,?,?) ON CONFLICT(unique_id,battle_id) DO UPDATE SET note=excluded.note,updated_at=excluded.updated_at',(str(unique_id),int(battle_id),str(note),time.time()))

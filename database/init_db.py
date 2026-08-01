import sqlite3

conn = sqlite3.connect("database/history.db")

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS ai_history(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    score INTEGER,
    prompt TEXT,
    result TEXT
)
""")

conn.commit()
conn.close()

print("データベースを作成しました。")
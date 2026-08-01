import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class HistoryDB:
    """AI分析履歴を管理するSQLiteデータベース。"""

    APP_NAME = "AI-TikTok-LIVE-Analyzer"
    DB_NAME = "history.db"

    def __init__(self):
        self.db = str(self._resolve_database_path())
        self._create_table()

    # ==================================================
    # Database path / setup
    # ==================================================

    def _resolve_database_path(self) -> Path:
        """
        開発中はプロジェクト内の database フォルダ、
        EXE実行時はユーザーのLocalAppData配下を使用する。
        """

        if getattr(sys, "frozen", False):
            local_app_data = os.getenv("LOCALAPPDATA")

            if local_app_data:
                base_dir = Path(local_app_data) / self.APP_NAME
            else:
                base_dir = Path.home() / "AppData" / "Local" / self.APP_NAME
        else:
            project_root = Path(__file__).resolve().parent.parent
            base_dir = project_root / "database"

        base_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        return base_dir / self.DB_NAME

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db,
            timeout=30
        )
        conn.execute(
            "PRAGMA journal_mode=WAL"
        )
        conn.execute(
            "PRAGMA foreign_keys=ON"
        )
        return conn

    def _create_table(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_history(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    score REAL,
                    prompt TEXT,
                    result TEXT
                )
                """
            )

    # ==================================================
    # Create
    # ==================================================

    def save(self, score, prompt, result):
        created_at = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_history(
                    created_at,
                    score,
                    prompt,
                    result
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    created_at,
                    score,
                    prompt,
                    result
                )
            )

    # ==================================================
    # Read
    # ==================================================

    def get_all(self):
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT
                    id,
                    created_at,
                    score,
                    prompt,
                    result
                FROM ai_history
                ORDER BY id DESC
                """
            )
            return cursor.fetchall()

    def get_latest(self):
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT
                    id,
                    created_at,
                    score,
                    prompt,
                    result
                FROM ai_history
                ORDER BY id DESC
                LIMIT 1
                """
            )
            return cursor.fetchone()

    def get_count(self):
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM ai_history"
            )
            return cursor.fetchone()[0]

    def get_average(self):
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT AVG(score) FROM ai_history"
            )
            value = cursor.fetchone()[0]

        return round(value, 1) if value is not None else 0

    def get_max(self):
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT MAX(score) FROM ai_history"
            )
            value = cursor.fetchone()[0]

        return value if value is not None else 0

    def get_min(self):
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT MIN(score) FROM ai_history"
            )
            value = cursor.fetchone()[0]

        return value if value is not None else 0

    def get_today_count(self):
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT COUNT(*)
                FROM ai_history
                WHERE DATE(created_at) = DATE('now', 'localtime')
                """
            )
            return cursor.fetchone()[0]

    def get_by_id(self, history_id: int) -> Optional[tuple]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT
                    id,
                    created_at,
                    score,
                    prompt,
                    result
                FROM ai_history
                WHERE id = ?
                """,
                (history_id,)
            )
            return cursor.fetchone()

    # ==================================================
    # Delete
    # ==================================================

    def delete(self, history_id):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM ai_history WHERE id = ?",
                (history_id,)
            )

    def delete_all(self):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM ai_history"
            )

            conn.execute(
                """
                DELETE FROM sqlite_sequence
                WHERE name = 'ai_history'
                """
            )

    # ==================================================
    # Utility
    # ==================================================

    def get_database_path(self) -> str:
        """現在使用中のDBファイルパスを返す。"""
        return self.db
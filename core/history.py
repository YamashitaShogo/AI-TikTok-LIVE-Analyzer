import json
import os
import sqlite3
import sys
import shutil
import uuid
from contextlib import contextmanager
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

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(
            self.db,
            timeout=30
        )

        try:
            conn.execute(
                "PRAGMA journal_mode=WAL"
            )
            conn.execute(
                "PRAGMA foreign_keys=ON"
            )

            yield conn

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()

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

            columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(ai_history)"
                ).fetchall()
            }

            if "image_path" not in columns:
                conn.execute(
                    "ALTER TABLE ai_history ADD COLUMN image_path TEXT"
                )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gift_history(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    gift_id TEXT NOT NULL,
                    gift_name TEXT,
                    quantity INTEGER NOT NULL,
                    coins_each INTEGER,
                    total_coins INTEGER,
                    confidence REAL,
                    is_known INTEGER NOT NULL DEFAULT 1,
                    image_path TEXT,
                    sender_text TEXT,
                    bbox_json TEXT
                )
                """
            )

            gift_columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(gift_history)"
                ).fetchall()
            }

            if "sender_text" not in gift_columns:
                conn.execute(
                    "ALTER TABLE gift_history "
                    "ADD COLUMN sender_text TEXT"
                )

            if "bbox_json" not in gift_columns:
                conn.execute(
                    "ALTER TABLE gift_history "
                    "ADD COLUMN bbox_json TEXT"
                )
    # ==================================================
    # Create
    # ==================================================

    def save(
    self,
    score,
    prompt,
    result,
    image_path=None,
    ):
        created_at = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        saved_image_path = None

        if image_path:
            source = Path(image_path)

            if source.exists():
                history_images_dir = (
                    Path(self.db).parent
                    / "history_images"
                )
                history_images_dir.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                extension = source.suffix or ".png"

                filename = (
                    datetime.now().strftime("%Y%m%d_%H%M%S_")
                    + uuid.uuid4().hex[:8]
                    + extension
                )

                destination = (
                    history_images_dir / filename
                )

                shutil.copy2(
                    source,
                    destination,
                )

                saved_image_path = str(destination)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_history(
                    created_at,
                    score,
                    prompt,
                    result,
                    image_path
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    score,
                    prompt,
                    result,
                    saved_image_path,
                ),
            )

    def save_gift(
        self,
        gift_id: str,
        gift_name: Optional[str],
        quantity: int,
        coins_each: Optional[int],
        total_coins: Optional[int],
        confidence: Optional[float],
        is_known: bool = True,
        image_path: Optional[str] = None,
        sender_text: Optional[str] = None,
        bbox: Optional[list[float]] = None,
    ) -> int:
        created_at = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        saved_image_path = None

        if bbox is None:
            bbox_json = None
        else:
            bbox_json = json.dumps(
                bbox,
                ensure_ascii=False,
            )

        if image_path:
            source = Path(image_path)

            if source.exists():
                history_images_dir = (
                    Path(self.db).parent
                    / "gift_history_images"
                )

                history_images_dir.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                extension = source.suffix or ".png"

                filename = (
                    datetime.now().strftime(
                        "%Y%m%d_%H%M%S_"
                    )
                    + uuid.uuid4().hex[:8]
                    + extension
                )

                destination = (
                    history_images_dir
                    / filename
                )

                shutil.copy2(
                    source,
                    destination,
                )

                saved_image_path = str(
                    destination
                )

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO gift_history(
                    created_at,
                    gift_id,
                    gift_name,
                    quantity,
                    coins_each,
                    total_coins,
                    confidence,
                    is_known,
                    image_path,
                    sender_text,
                    bbox_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    gift_id,
                    gift_name,
                    int(quantity),
                    coins_each,
                    total_coins,
                    confidence,
                    1 if is_known else 0,
                    saved_image_path,
                    sender_text,
                    bbox_json,
                ),
            )

            return int(cursor.lastrowid)

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

    def get_by_id_with_image(
        self,
        history_id: int,
    ) -> Optional[tuple]:
        """
        履歴詳細画面用。
        id / created_at / score / prompt / result / image_path を返す。
        """
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT
                    id,
                    created_at,
                    score,
                    prompt,
                    result,
                    image_path
                FROM ai_history
                WHERE id = ?
                """,
                (history_id,),
            )

            return cursor.fetchone()

    def get_gift_history(
        self,
        limit: int = 100,
    ):
        limit = max(
            1,
            min(
                1000,
                int(limit),
            ),
        )

        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT
                    id,
                    created_at,
                    gift_id,
                    gift_name,
                    quantity,
                    coins_each,
                    total_coins,
                    confidence,
                    is_known,
                    image_path
                FROM gift_history
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )

            return cursor.fetchall()

    def get_gift_total_coins(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT COALESCE(
                    SUM(total_coins),
                    0
                )
                FROM gift_history
                WHERE is_known = 1
                """
            )

            value = cursor.fetchone()[0]

        return int(value or 0)

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
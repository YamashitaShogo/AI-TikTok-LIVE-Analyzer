from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from core.battle_monitor import BattleMonitor


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
WATCHLIST_PATH = DATA_DIR / "battle_watchlist.json"
DB_PATH = DATA_DIR / "battle_dataset.sqlite3"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _find_battle_path() -> Path:
    """
    battle_monitor.py が使っている latest_battle.json を探す。
    既存版/ブランド名変更後の両方を候補にする。
    """
    local_appdata = Path(
        os.environ.get("LOCALAPPDATA", str(Path.home()))
    )

    candidates = [
        local_appdata / "AI-TikTok-LIVE-Analyzer" / "capture" / "latest_battle.json",
        local_appdata / "LivemetryPulse" / "capture" / "latest_battle.json",
        local_appdata / "Livemetry Pulse" / "capture" / "latest_battle.json",
    ]

    for path in candidates:
        if path.exists():
            return path

    # battle_monitor 側がまだファイルを作っていない場合は
    # 現行の旧パスをデフォルトにする。
    return candidates[0]


class BattleDatasetStore:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=20)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS battle_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    battle_id INTEGER NOT NULL,
                    unique_id TEXT NOT NULL,
                    tier TEXT,
                    mode TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    finish_reason TEXT,
                    final_payload_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (battle_id, unique_id)
                );

                CREATE TABLE IF NOT EXISTS battle_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    battle_id INTEGER NOT NULL,
                    unique_id TEXT NOT NULL,
                    tier TEXT,
                    update_time INTEGER NOT NULL DEFAULT 0,
                    captured_at TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE (battle_id, unique_id, payload_hash)
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_unique_id
                    ON battle_sessions(unique_id);

                CREATE INDEX IF NOT EXISTS idx_sessions_finished_at
                    ON battle_sessions(finished_at);

                CREATE INDEX IF NOT EXISTS idx_snapshots_battle
                    ON battle_snapshots(battle_id, unique_id, update_time);
                """
            )

    def save_payload(self, payload: dict[str, Any], tier: str = "") -> bool:
        battle_id = int(payload.get("battle_id") or 0)
        unique_id = str(payload.get("unique_id") or "").strip().lstrip("@")

        if battle_id <= 0 or not unique_id:
            return False

        now = _now_iso()
        update_time = int(payload.get("update_time") or 0)
        mode = str(payload.get("mode") or "")
        active = bool(payload.get("active"))

        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        payload_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

        with self._connect() as con:
            con.execute(
                """
                INSERT OR IGNORE INTO battle_sessions (
                    battle_id, unique_id, tier, mode,
                    started_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    battle_id,
                    unique_id,
                    tier,
                    mode,
                    now,
                    now,
                    now,
                ),
            )

            con.execute(
                """
                UPDATE battle_sessions
                SET tier = CASE WHEN ? <> '' THEN ? ELSE tier END,
                    mode = CASE WHEN ? <> '' THEN ? ELSE mode END,
                    updated_at = ?
                WHERE battle_id = ? AND unique_id = ?
                """,
                (
                    tier,
                    tier,
                    mode,
                    mode,
                    now,
                    battle_id,
                    unique_id,
                ),
            )

            cur = con.execute(
                """
                INSERT OR IGNORE INTO battle_snapshots (
                    battle_id, unique_id, tier, update_time,
                    captured_at, payload_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    battle_id,
                    unique_id,
                    tier,
                    update_time,
                    now,
                    payload_hash,
                    raw,
                ),
            )

            if not active:
                finished_at = str(payload.get("finished_at") or now)
                finish_reason = str(payload.get("reason") or "")
                con.execute(
                    """
                    UPDATE battle_sessions
                    SET finished_at = ?,
                        finish_reason = ?,
                        final_payload_json = ?,
                        updated_at = ?
                    WHERE battle_id = ? AND unique_id = ?
                    """,
                    (
                        finished_at,
                        finish_reason,
                        raw,
                        now,
                        battle_id,
                        unique_id,
                    ),
                )

            return cur.rowcount > 0

    def stats(self) -> dict[str, int]:
        with self._connect() as con:
            total = con.execute(
                "SELECT COUNT(*) FROM battle_sessions"
            ).fetchone()[0]
            finished = con.execute(
                "SELECT COUNT(*) FROM battle_sessions WHERE finished_at IS NOT NULL"
            ).fetchone()[0]
            snapshots = con.execute(
                "SELECT COUNT(*) FROM battle_snapshots"
            ).fetchone()[0]

        return {
            "battles": int(total),
            "finished": int(finished),
            "snapshots": int(snapshots),
        }


class AutoBattleDatasetCollector:
    """
    watchlist のライバーを1人ずつ巡回して既存 BattleMonitor を起動し、
    latest_battle.json の変更を SQLite に保存する。

    TikTokへ大量の並列接続を作らず、既存 BattleMonitor と同じ経路を使う。
    """

    def __init__(
        self,
        watchlist_path: Path = WATCHLIST_PATH,
        db_path: Path = DB_PATH,
        watch_seconds: int = 120,
        poll_seconds: float = 0.5,
        switch_pause_seconds: float = 3.0,
    ) -> None:
        self.watchlist_path = watchlist_path
        self.store = BattleDatasetStore(db_path)
        self.watch_seconds = max(30, int(watch_seconds))
        self.poll_seconds = max(0.2, float(poll_seconds))
        self.switch_pause_seconds = max(1.0, float(switch_pause_seconds))

        self.battle_path = _find_battle_path()
        self.monitor = BattleMonitor()

        self._stop_event = threading.Event()
        self._last_mtime_ns = 0
        self._last_payload_hash = ""

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self.monitor.stop()
        except Exception:
            pass

    def _load_watchlist(self) -> list[dict[str, str]]:
        self.watchlist_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.watchlist_path.exists():
            self.watchlist_path.write_text(
                json.dumps(
                    {
                        "targets": [
                            {
                                "unique_id": "ここをTikTok_IDに変更",
                                "tier": "middle",
                                "enabled": True,
                            }
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return []

        data = json.loads(self.watchlist_path.read_text(encoding="utf-8"))
        raw_targets = data.get("targets", [])

        targets: list[dict[str, str]] = []
        for item in raw_targets:
            if not isinstance(item, dict):
                continue
            if not item.get("enabled", True):
                continue

            unique_id = str(item.get("unique_id") or "").strip().lstrip("@")
            if not unique_id or unique_id.startswith("ここを"):
                continue

            targets.append(
                {
                    "unique_id": unique_id,
                    "tier": str(item.get("tier") or ""),
                }
            )

        return targets

    def _read_payload_if_changed(self) -> Optional[dict[str, Any]]:
        try:
            stat = self.battle_path.stat()
        except FileNotFoundError:
            return None

        if stat.st_mtime_ns == self._last_mtime_ns:
            return None

        self._last_mtime_ns = stat.st_mtime_ns

        try:
            payload = json.loads(
                self.battle_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return None

        if not isinstance(payload, dict):
            return None

        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()

        if digest == self._last_payload_hash:
            return None

        self._last_payload_hash = digest
        return payload

    def _watch_target(self, unique_id: str, tier: str) -> None:
        print(
            f"[Dataset Collector] watching @{unique_id} "
            f"tier={tier or '-'}",
            flush=True,
        )

        try:
            self.monitor.start(unique_id)
        except Exception as exc:
            print(
                f"[Dataset Collector] start failed @{unique_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            return

        deadline = time.monotonic() + self.watch_seconds

        while (
            not self._stop_event.is_set()
            and time.monotonic() < deadline
        ):
            payload = self._read_payload_if_changed()

            if payload:
                payload_unique_id = (
                    str(payload.get("unique_id") or "")
                    .strip()
                    .lstrip("@")
                )

                # 切替直後に前ライバーのJSONが残っていても保存しない
                if payload_unique_id == unique_id:
                    inserted = self.store.save_payload(payload, tier=tier)

                    if inserted:
                        battle_id = int(payload.get("battle_id") or 0)
                        active = bool(payload.get("active"))
                        update_time = int(payload.get("update_time") or 0)

                        print(
                            "[Dataset Collector] saved "
                            f"battle={battle_id} "
                            f"update={update_time} "
                            f"active={active}",
                            flush=True,
                        )

                        if not active:
                            stats = self.store.stats()
                            print(
                                "[Dataset Collector] battle finished | "
                                f"battles={stats['battles']} "
                                f"finished={stats['finished']} "
                                f"snapshots={stats['snapshots']}",
                                flush=True,
                            )

            time.sleep(self.poll_seconds)

        try:
            self.monitor.stop()
        except Exception:
            pass

    def run_forever(self) -> None:
        print("[Dataset Collector] started", flush=True)
        print(
            f"[Dataset Collector] battle file: {self.battle_path}",
            flush=True,
        )
        print(
            f"[Dataset Collector] database: {self.store.db_path}",
            flush=True,
        )

        while not self._stop_event.is_set():
            targets = self._load_watchlist()

            if not targets:
                print(
                    "[Dataset Collector] battle_watchlist.json に "
                    "TikTok IDを追加してください。",
                    flush=True,
                )
                self._stop_event.wait(10)
                continue

            for target in targets:
                if self._stop_event.is_set():
                    break

                self._watch_target(
                    unique_id=target["unique_id"],
                    tier=target["tier"],
                )

                if not self._stop_event.is_set():
                    self._stop_event.wait(self.switch_pause_seconds)

        self.stop()
        print("[Dataset Collector] stopped", flush=True)


def main() -> None:
    collector = AutoBattleDatasetCollector()

    try:
        collector.run_forever()
    except KeyboardInterrupt:
        print("\n[Dataset Collector] Ctrl+C", flush=True)
        collector.stop()


if __name__ == "__main__":
    main()

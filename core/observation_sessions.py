"""Observation session records for unattended observation reports.

Sessions live in their own SQLite file under ``<capture>/observation_report/``
so the battle collection database is never modified by this feature.
All timestamps are epoch seconds; JST formatting happens at display time.

Design rules (from the unattended-report spec):
- A session that is still marked ``running`` when the store is reopened
  after a crash is recovered as ``interrupted``. Its ``ended_at`` stays
  NULL: a guessed end time is never stored as a confirmed value. The
  last heartbeat timestamp is kept as the evidence of when observation
  was last confirmed alive.
- Monitored / disconnected seconds are accumulated from heartbeat
  samples of the existing collector heartbeat file. Sampling gaps
  longer than ``MAX_SAMPLE_GAP`` are counted as ``gap_seconds``
  (unknown), never silently as monitored time.
- Nothing in this module touches the battle database.
"""
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
MAX_SAMPLE_GAP = 60.0
END_KINDS = ("running", "normal", "abnormal", "interrupted")
# Identifies the process that owns live sessions. A session owned by
# this process is alive by definition and must never be "recovered";
# a session owned by another process is only recovered once its
# heartbeat is stale, so a second live instance is never cut off.
PROCESS_TOKEN = uuid.uuid4().hex
DEFAULT_STALE_AFTER = 180.0


def format_jst(timestamp):
    """Epoch seconds -> 'YYYY-MM-DD HH:MM:SS' in JST, or '未記録'."""
    if timestamp is None:
        return "未記録"
    try:
        return datetime.fromtimestamp(float(timestamp), JST).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OverflowError, OSError):
        return "未記録"


def session_db_path(capture_dir):
    return Path(capture_dir) / "observation_report" / "sessions.sqlite3"


class SessionStore:
    """SQLite-backed store for observation sessions (separate database)."""

    def __init__(self, capture_dir, process_token=None):
        self.capture_dir = Path(capture_dir)
        self.db_path = session_db_path(self.capture_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.process_token = process_token or PROCESS_TOKEN
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    targets_json TEXT NOT NULL DEFAULT '[]',
                    started_at REAL NOT NULL,
                    ended_at REAL,
                    end_kind TEXT NOT NULL DEFAULT 'running',
                    last_heartbeat_at REAL,
                    monitored_seconds REAL NOT NULL DEFAULT 0,
                    disconnected_seconds REAL NOT NULL DEFAULT 0,
                    gap_seconds REAL NOT NULL DEFAULT 0,
                    last_data_at REAL,
                    report_state TEXT NOT NULL DEFAULT 'none',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    recovered_at REAL
                );
                CREATE TABLE IF NOT EXISTS session_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    at REAL NOT NULL,
                    kind TEXT NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS session_events_session
                    ON session_events(session_id, at);
            """)
            # Non-destructive migration for stores created before
            # ownership tracking existed.
            columns = {row[1] for row in db.execute("PRAGMA table_info(sessions)")}
            if "owner_token" not in columns:
                db.execute("ALTER TABLE sessions ADD COLUMN owner_token TEXT")
            if "owner_pid" not in columns:
                db.execute("ALTER TABLE sessions ADD COLUMN owner_pid INTEGER")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA busy_timeout=10000")
            with db:
                yield db
        finally:
            db.close()

    # ------------------------------------------------------------- CRUD
    def start_session(self, mode, targets=None, profile="capture", now=None):
        now = time.time() if now is None else float(now)
        session_id = uuid.uuid4().hex
        targets = [str(t).strip().lstrip("@") for t in (targets or []) if str(t).strip()]
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO sessions (session_id, mode, profile, targets_json,"
                " started_at, last_heartbeat_at, owner_token, owner_pid)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, str(mode or "unattended"), str(profile or "capture"),
                 json.dumps(targets, ensure_ascii=False), now, now,
                 self.process_token, os.getpid()))
            db.execute(
                "INSERT INTO session_events (session_id, at, kind, detail_json)"
                " VALUES (?, ?, 'start', ?)",
                (session_id, now, json.dumps({"targets": targets}, ensure_ascii=False)))
        return self.get_session(session_id)

    def heartbeat(self, session_id, connected, last_data_at=None, now=None):
        """Accumulate monitored/disconnected time from one sample."""
        now = time.time() if now is None else float(now)
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT last_heartbeat_at, last_data_at FROM sessions"
                " WHERE session_id=? AND end_kind='running'", (session_id,)).fetchone()
            if row is None:
                return False
            last = row["last_heartbeat_at"]
            delta = max(0.0, now - float(last)) if last is not None else 0.0
            column = None
            if delta > MAX_SAMPLE_GAP:
                column = "gap_seconds"
            elif connected:
                column = "monitored_seconds"
            else:
                column = "disconnected_seconds"
            new_last_data = row["last_data_at"]
            if last_data_at is not None:
                new_last_data = max(float(last_data_at),
                                    float(new_last_data) if new_last_data else 0.0)
            db.execute(
                f"UPDATE sessions SET last_heartbeat_at=?, last_data_at=?,"
                f" owner_token=?, owner_pid=?,"
                f" {column}={column}+? WHERE session_id=?",
                (now, new_last_data, self.process_token, os.getpid(),
                 delta, session_id))
        return True

    def adopt_session(self, session_id):
        """Claim a running session for this process (e.g. page reopened)."""
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE sessions SET owner_token=?, owner_pid=?"
                " WHERE session_id=? AND end_kind='running'",
                (self.process_token, os.getpid(), session_id))

    def record_event(self, session_id, kind, detail=None, now=None):
        now = time.time() if now is None else float(now)
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO session_events (session_id, at, kind, detail_json)"
                " VALUES (?, ?, ?, ?)",
                (session_id, now, str(kind),
                 json.dumps(detail or {}, ensure_ascii=False)))

    def switch_target(self, session_id, new_target, now=None):
        target = str(new_target or "").strip().lstrip("@")
        self.record_event(session_id, "target_switch", {"target": target}, now=now)
        return target

    def stop_session(self, session_id, end_kind="normal", now=None):
        if end_kind not in END_KINDS or end_kind == "running":
            end_kind = "normal"
        now = time.time() if now is None else float(now)
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE sessions SET ended_at=?, end_kind=?"
                " WHERE session_id=? AND end_kind='running'",
                (now, end_kind, session_id))
            db.execute(
                "INSERT INTO session_events (session_id, at, kind, detail_json)"
                " VALUES (?, ?, 'stop', ?)",
                (session_id, now, json.dumps({"end_kind": end_kind})))
        return self.get_session(session_id)

    def recover_interrupted(self, now=None, stale_after=DEFAULT_STALE_AFTER):
        """Mark sessions left 'running' by a crash as interrupted.

        Safety guards (a live session must never be recovered):
        - sessions owned by THIS process are skipped unconditionally;
        - sessions whose heartbeat is fresh (within ``stale_after``
          seconds) are skipped: another live instance may own them.

        ``ended_at`` is deliberately left NULL for recovered sessions:
        the true end time is unknown, and the last heartbeat is the
        only confirmed evidence.
        """
        now = time.time() if now is None else float(now)
        recovered = []
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT session_id, last_heartbeat_at, owner_token FROM sessions"
                " WHERE end_kind='running'").fetchall()
            for row in rows:
                if row["owner_token"] is not None and row["owner_token"] == self.process_token:
                    continue  # owned by this live process
                last = row["last_heartbeat_at"]
                if last is not None and now - float(last) <= stale_after:
                    continue  # heartbeat still fresh: owner may be alive
                db.execute(
                    "UPDATE sessions SET end_kind='interrupted', recovered_at=?"
                    " WHERE session_id=?", (now, row["session_id"]))
                db.execute(
                    "INSERT INTO session_events (session_id, at, kind, detail_json)"
                    " VALUES (?, ?, 'recovered', ?)",
                    (row["session_id"], now, json.dumps(
                        {"last_heartbeat_at": row["last_heartbeat_at"]})))
                recovered.append(row["session_id"])
        return recovered

    def mark_report(self, session_id, state, detail=None, now=None):
        now = time.time() if now is None else float(now)
        with self._lock, self._connect() as db:
            db.execute("UPDATE sessions SET report_state=? WHERE session_id=?",
                       (str(state), session_id))
        self.record_event(session_id, "report_generated",
                          {"state": str(state), **(detail or {})}, now=now)

    # ------------------------------------------------------------- reads
    def _row_to_session(self, db, row):
        session = dict(row)
        try:
            session["targets"] = json.loads(session.pop("targets_json") or "[]")
        except ValueError:
            session["targets"] = []
        try:
            session["evidence_refs"] = json.loads(session.pop("evidence_refs_json") or "[]")
        except ValueError:
            session["evidence_refs"] = []
        # Events are loaded on every session read (the report page
        # refreshes constantly), so a long session with a flapping
        # connection must not grow this read without bound:
        # target_switch events are always kept in full (reports list
        # them and they are user-driven, hence few), other kinds are
        # capped at the most recent 1000.
        sid = session["session_id"]
        event_rows = db.execute(
            "SELECT at, kind, detail_json FROM session_events"
            " WHERE session_id=? AND kind='target_switch'"
            " ORDER BY at, id", (sid,)).fetchall()
        event_rows += db.execute(
            "SELECT at, kind, detail_json FROM session_events"
            " WHERE session_id=? AND kind<>'target_switch'"
            " ORDER BY id DESC LIMIT 1000", (sid,)).fetchall()
        event_rows.sort(key=lambda r: r["at"])
        session["events"] = [
            {"at": r["at"], "kind": r["kind"],
             "detail": json.loads(r["detail_json"] or "{}")}
            for r in event_rows]
        session["started_jst"] = format_jst(session["started_at"])
        session["ended_jst"] = format_jst(session["ended_at"])
        session["elapsed_seconds"] = (
            (session["ended_at"] or session["last_heartbeat_at"] or session["started_at"])
            - session["started_at"])
        return session

    def get_session(self, session_id):
        with self._connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE session_id=?",
                             (session_id,)).fetchone()
            return self._row_to_session(db, row) if row else None

    def list_sessions(self, limit=50):
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?",
                (max(1, int(limit)),)).fetchall()
            return [self._row_to_session(db, row) for row in rows]

    def latest_session(self):
        sessions = self.list_sessions(limit=1)
        return sessions[0] if sessions else None


class SessionSampler:
    """Polls the existing collector heartbeat file during a session.

    Read-only with respect to collection: it only reads
    ``collector_health.json`` (via core.collection_health.read_health)
    and the battle database's last-data timestamp. Every failure is
    swallowed; sampling must never disturb collection.
    """

    def __init__(self, store, session_id, capture_dir, interval=10.0):
        self.store = store
        self.session_id = session_id
        self.capture_dir = Path(capture_dir)
        self.interval = max(2.0, float(interval))
        self._stop = threading.Event()
        self._thread = None
        self._was_connected = None
        self._last_error_kind = ''

    def start(self):
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="SessionSampler")
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=self.interval + 5)

    def _sample_once(self, now=None):
        try:
            from core.collection_health import read_health
        except ImportError:  # direct-script import style
            from collection_health import read_health
        health = read_health(self.capture_dir, now=now)
        connected = str(health.get("status") or "").startswith("接続中")
        # Record WHY collection is failing when the collector knows:
        # without this, a session whose target did not exist (or was
        # rate-limited) is indistinguishable from plain offline
        # waiting in the stored record. One event per transition;
        # the tracker re-arms when the error clears.
        error_kind = str(health.get("error_kind") or "")
        if error_kind in ("not_found", "rate_limit") \
                and error_kind != self._last_error_kind:
            self.store.record_event(
                self.session_id, "connection_error",
                {"kind": error_kind, "status": health.get("status")},
                now=now)
        self._last_error_kind = error_kind
        if self._was_connected is not None and connected != self._was_connected:
            self.store.record_event(
                self.session_id,
                "disconnect_start" if not connected else "disconnect_end",
                {"status": health.get("status")}, now=now)
        self._was_connected = connected
        self.store.heartbeat(self.session_id, connected,
                             last_data_at=health.get("last_data"), now=now)

    def _run(self):
        while not self._stop.is_set():
            try:
                self._sample_once()
            except Exception:
                pass  # Sampling must never disturb collection.
            self._stop.wait(self.interval)


class SessionRuntime:
    """Owns live samplers independently of any UI page.

    The observation session's lifetime is the app process's lifetime,
    not a page's: navigating away from the report page must not stop
    session recording. Pages delegate start/stop here and never touch
    samplers directly. One runtime exists per capture directory.
    """

    def __init__(self, capture_dir, sampler_interval=10.0):
        self.capture_dir = Path(capture_dir)
        self.store = SessionStore(self.capture_dir)
        self.sampler_interval = sampler_interval
        self._samplers = {}
        self._lock = threading.RLock()

    def start_session(self, mode, targets=None, profile="capture"):
        session = self.store.start_session(mode, targets, profile=profile)
        self.ensure_sampling(session["session_id"])
        return self.store.get_session(session["session_id"])

    def ensure_sampling(self, session_id):
        """Attach a sampler to a running session if none is alive."""
        with self._lock:
            sampler = self._samplers.get(session_id)
            if sampler is not None and sampler._thread is not None \
                    and sampler._thread.is_alive():
                return sampler
            session = self.store.get_session(session_id)
            if session is None or session["end_kind"] != "running":
                return None
            self.store.adopt_session(session_id)
            sampler = SessionSampler(self.store, session_id, self.capture_dir,
                                     interval=self.sampler_interval)
            sampler.start()
            self._samplers[session_id] = sampler
            return sampler

    def ensure_all_sampling(self):
        for session in self.store.list_sessions(limit=50):
            if session["end_kind"] == "running":
                self.ensure_sampling(session["session_id"])

    def active_sessions(self):
        self.ensure_all_sampling()
        return [s for s in self.store.list_sessions(limit=50)
                if s["end_kind"] == "running"]

    def stop_session(self, session_id, end_kind="normal", auto_report=True):
        with self._lock:
            sampler = self._samplers.pop(session_id, None)
        if sampler is not None:
            sampler.stop()
        session = self.store.stop_session(session_id, end_kind=end_kind)
        if auto_report and session is not None:
            thread = threading.Thread(target=self._auto_report,
                                      args=(session_id,), daemon=True,
                                      name="SessionAutoReport")
            thread.start()
        return session

    def _auto_report(self, session_id):
        """Best-effort automatic report (JSON) after a session stops.

        Runs in a background thread and swallows every failure: report
        generation must never affect collection or the stop action.
        What stays manual: on-screen aggregation, PDF and AI analysis.
        """
        try:
            from core.unattended_report import build_report
            from core.report_export import export_json
            session = self.store.get_session(session_id)
            if session is None:
                return
            database = self.capture_dir / "battle_dataset" / "battles.sqlite3"
            report = build_report(database, {"kind": "session"}, session=session,
                                  profile=session["profile"],
                                  generation_trigger="auto_session_stop")
            folder = self.capture_dir / "observation_report" / "reports"
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.fromtimestamp(session["ended_at"] or time.time(), JST)
            export_json(report, folder / f"report_{stamp.strftime('%Y%m%d_%H%M%S')}.json")
            self.store.mark_report(session_id, "generated",
                                   {"trigger": "auto_session_stop"})
        except Exception:
            pass  # Automatic reporting is best-effort by design.


_RUNTIMES = {}
_RUNTIMES_LOCK = threading.Lock()


def get_runtime(capture_dir):
    """The process-wide SessionRuntime for one capture directory."""
    key = str(Path(capture_dir).resolve())
    with _RUNTIMES_LOCK:
        runtime = _RUNTIMES.get(key)
        if runtime is None:
            runtime = SessionRuntime(capture_dir)
            _RUNTIMES[key] = runtime
        return runtime

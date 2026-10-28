"""Opt-in screen-evidence capture for first-challenge ground truth (Phase D).

Design: tools/first_challenge_observation_design.md

Purpose: while a battle runs, keep timestamped still frames of the battle
screen plus the receive times of the battle notifications that might later
need to be reconciled with what was on screen. This module ONLY collects
evidence. It never analyses images and never decides what an event means:

- Every session starts with verdict "unknown".
- No automatic code path in this module can set "candidate" or
  "screen_confirmed". Only set_human_verdict() (a human action, also used
  by tools/evidence_capture.py) may record those, into human_verdict.json.
- A screen showing a x3 marker never, by itself, marks any notification
  event as x3-specific: the human verdict records the screen observation
  for the session and explicitly keeps event_meaning undetermined.

Safety contract: the recorder is inert unless the user explicitly enables
`evidence_capture_enabled` in settings.json (default OFF). Every public
method swallows exceptions so battle collection can never be broken by
this module. Frames come from the existing latest.jpg flow (written by
the collector's normal 5-second poll); this module adds no screenshot
loop and never changes any existing polling cadence. It also stays inert
inside TopWatch child processes (their capture dir lives under a
top_watch/ sandbox).

Storage (local only, never committed, no SQLite involvement):
    <capture base>/evidence/<battle_id>_<observation_id>/
        frame_000001.jpg / .png ...
        metadata.json
        correspondence.csv
        human_verdict.json   (only when a human records one)

Privacy: no cookies, session ids, comment text, names or handles are
recorded. Battle context is reduced to format and participant counts.
"""

import csv
import json
import os
import queue
import secrets
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))

SCHEMA = "livemetry_evidence_session_v1"

# The notifications reconciled against frames (receive times only).
EVIDENCE_METHODS = frozenset({
    "WebcastBattleGameplayMessage",
    "WebcastLinkmicBattleTaskMessage",
    "WebcastGiftMessage",
    "WebcastLinkMicBattle",
    "WebcastLinkMicOpponentGifts",
})

HUMAN_VERDICTS = ("candidate", "screen_confirmed")

_DEFAULTS = {
    "enabled": False,
    "interval_sec": 2.0,
    "post_roll_sec": 10.0,
    "max_frames_per_battle": 400,
    "max_total_mb": 500,
    "retention_days": 14,
}


def jst_iso(epoch_seconds):
    """Epoch seconds -> JST ISO-8601 with milliseconds."""
    try:
        value = float(epoch_seconds)
    except (TypeError, ValueError):
        return ""
    dt = datetime.fromtimestamp(value, tz=JST)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}+09:00"


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


def _as_float(value, default, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return min(high, max(low, number))


def _as_int(value, default, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, number))


class EvidenceConfig:
    """Recorder configuration. Build via load_config() for app use;
    tests may construct this directly with byte-exact caps."""

    def __init__(self, enabled=False, interval_sec=2.0, post_roll_sec=10.0,
                 max_frames_per_battle=400, max_total_bytes=500 * 1024 * 1024,
                 retention_days=14):
        self.enabled = bool(enabled)
        self.interval_sec = min(5.0, max(1.0, float(interval_sec)))
        self.post_roll_sec = min(60.0, max(0.0, float(post_roll_sec)))
        self.max_frames_per_battle = min(10000, max(1, int(max_frames_per_battle)))
        self.max_total_bytes = max(1, int(max_total_bytes))
        self.retention_days = min(365, max(0, int(retention_days)))

    def __repr__(self):
        return (f"EvidenceConfig(enabled={self.enabled}, "
                f"interval_sec={self.interval_sec}, "
                f"post_roll_sec={self.post_roll_sec}, "
                f"max_frames_per_battle={self.max_frames_per_battle}, "
                f"max_total_bytes={self.max_total_bytes}, "
                f"retention_days={self.retention_days})")


def load_config(settings):
    """Build an EvidenceConfig from a settings.json dict, defensively.

    Unknown/missing/invalid values fall back to the Phase D defaults;
    the feature stays OFF unless evidence_capture_enabled is truthy.
    """
    data = settings if isinstance(settings, dict) else {}
    return EvidenceConfig(
        enabled=_as_bool(data.get("evidence_capture_enabled"),
                         _DEFAULTS["enabled"]),
        interval_sec=_as_float(data.get("evidence_interval_sec"),
                               _DEFAULTS["interval_sec"], 1.0, 5.0),
        post_roll_sec=_as_float(data.get("evidence_post_roll_sec"),
                                _DEFAULTS["post_roll_sec"], 0.0, 60.0),
        max_frames_per_battle=_as_int(
            data.get("evidence_max_frames_per_battle"),
            _DEFAULTS["max_frames_per_battle"], 1, 10000),
        max_total_bytes=_as_int(data.get("evidence_max_total_mb"),
                                _DEFAULTS["max_total_mb"], 1, 10000) * 1024 * 1024,
        retention_days=_as_int(data.get("evidence_retention_days"),
                               _DEFAULTS["retention_days"], 0, 365),
    )


def in_top_watch_sandbox(base_dir):
    """True when the capture base lives under a TopWatch child sandbox
    (<...>/top_watch/<streamer>/AI-TikTok-LIVE-Analyzer/capture_fixed)."""
    try:
        return "top_watch" in Path(base_dir).parts
    except Exception:
        return False


def sanitize_battle_context(payload):
    """Reduce a latest_battle payload to format + counts only.

    Names, handles, user ids and anchor ids are deliberately dropped:
    the evidence record never carries personal identifiers.
    """
    context = {}
    if not isinstance(payload, dict):
        return context
    mode = payload.get("mode")
    if isinstance(mode, str) and mode:
        context["mode"] = mode[:32]
    participants = payload.get("participants")
    if isinstance(participants, list):
        context["participant_count"] = len(participants)
    teams = payload.get("teams")
    if isinstance(teams, list):
        context["team_count"] = len(teams)
        sizes = []
        total = 0
        for team in teams:
            users = team.get("users") if isinstance(team, dict) else None
            size = len(users) if isinstance(users, list) else 0
            sizes.append(size)
            total += size
        context["team_sizes"] = sizes
        if "participant_count" not in context:
            context["participant_count"] = total
    duration = payload.get("duration_seconds")
    if isinstance(duration, (int, float)) and duration:
        context["duration_seconds"] = int(duration)
    start_ms = payload.get("start_time_ms")
    if isinstance(start_ms, (int, float)) and start_ms:
        context["battle_start_time_ms"] = int(start_ms)
        context["battle_start_jst"] = jst_iso(int(start_ms) / 1000.0)
    gameplay = payload.get("gameplay_option")
    if isinstance(gameplay, str) and gameplay:
        # Enum label from the battle settings, recorded as-is (context
        # only; it is not evidence about any notification's meaning).
        context["gameplay_option"] = gameplay[:64]
    return context


class _LatestJpgSource:
    """Reads new frames from the collector's existing latest.jpg flow.

    poll() returns (image_bytes, captured_at_epoch) only when the file's
    mtime advanced since the previous poll; captured_at is the mtime,
    i.e. when the collector wrote the frame. Never raises.
    """

    def __init__(self, frame_path):
        self._path = Path(frame_path)
        self._last_mtime = None

    def poll(self):
        try:
            stat = self._path.stat()
        except OSError:
            return None
        if self._last_mtime is not None and stat.st_mtime <= self._last_mtime:
            return None
        try:
            data = self._path.read_bytes()
        except OSError:
            return None
        if not data:
            return None
        self._last_mtime = stat.st_mtime
        return data, stat.st_mtime


def _frame_extension(image_bytes):
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    return ".jpg"


class EvidenceRecorder:
    """Per-process recorder. All public methods are exception-swallowing
    and no-ops while disabled, so wiring can call them unconditionally.
    """

    def __init__(self, base_dir, config=None, *, clock=None, frame_path=None):
        self._base_dir = Path(base_dir)
        self._root = self._base_dir / "evidence"
        self._config = config if config is not None else EvidenceConfig()
        self._clock = clock if clock is not None else time.time
        self._frame_path = (Path(frame_path) if frame_path is not None
                            else self._base_dir / "latest.jpg")
        self._lock = threading.RLock()
        self._session = None
        self._queue = queue.Queue(maxsize=64)
        self._writer = None
        self._feeder = None
        self._feeder_stop = threading.Event()
        self._closed = False

    # ------------------------------------------------------------------
    # construction helpers
    # ------------------------------------------------------------------
    @classmethod
    def from_app_settings(cls, base_dir, *, clock=None):
        """Build a recorder for the collector process.

        Reads settings.json next to the capture base dir (the same file
        the rest of the app uses), defensively. Stays disabled inside
        TopWatch child sandboxes. Never raises.
        """
        try:
            settings = {}
            try:
                settings_path = Path(base_dir).parent / "settings.json"
                if settings_path.exists():
                    data = json.loads(
                        settings_path.read_text(encoding="utf-8-sig"))
                    if isinstance(data, dict):
                        settings = data
            except Exception:
                settings = {}
            config = load_config(settings)
            if in_top_watch_sandbox(base_dir):
                config.enabled = False
            return cls(base_dir, config, clock=clock)
        except Exception:
            return cls(base_dir, EvidenceConfig(enabled=False), clock=clock)

    @property
    def enabled(self):
        return bool(self._config.enabled) and not self._closed

    @property
    def config(self):
        return self._config

    @property
    def root(self):
        return self._root

    def active_session_dir(self):
        with self._lock:
            if self._session is None:
                return None
            return self._session["dir"]

    # ------------------------------------------------------------------
    # session lifecycle
    # ------------------------------------------------------------------
    def start_battle(self, battle_id, context=None):
        """Begin an evidence session for a battle. Returns the session
        dir (Path) or None when disabled / already recording this battle.
        """
        try:
            if not self.enabled:
                return None
            battle_key = str(battle_id or "").strip()
            if not battle_key:
                return None
            with self._lock:
                if self._session is not None:
                    if self._session["battle_id"] == battle_key:
                        return self._session["dir"]
                    self._finalize_locked("superseded_by_new_battle")
                self.purge_old_evidence()
                now = self._clock()
                stamp = datetime.fromtimestamp(now, tz=JST).strftime(
                    "%Y%m%dT%H%M%S") + f"{int(now * 1000) % 1000:03d}"
                observation_id = f"{stamp}-{secrets.token_hex(3)}"
                session_dir = self._root / f"{battle_key}_{observation_id}"
                session_dir.mkdir(parents=True, exist_ok=True)
                self._session = {
                    "battle_id": battle_key,
                    "observation_id": observation_id,
                    "dir": session_dir,
                    "context": sanitize_battle_context(context or {}),
                    "started_at": now,
                    "end_reason": "",
                    "ending_at": None,
                    "frames": [],
                    "events": [],
                    "last_saved_at": None,
                    "frames_skipped_sampling": 0,
                    "frames_dropped_queue": 0,
                    "frames_capped": 0,
                }
                self._ensure_writer_locked()
                self._start_feeder_locked()
                return session_dir
        except Exception:
            return None

    def finish_battle(self, reason="finished"):
        """End the active session. With a post-roll configured and the
        frame feeder running, finalization is deferred until the
        post-roll elapses (the feeder thread performs it); otherwise the
        session is finalized immediately. Never raises."""
        try:
            if not self.enabled:
                return
            with self._lock:
                if self._session is None:
                    return
                self._session["end_reason"] = str(reason or "finished")
                post_roll = self._config.post_roll_sec
                feeder_alive = (self._feeder is not None
                                and self._feeder.is_alive())
                if post_roll > 0 and feeder_alive:
                    self._session["ending_at"] = self._clock() + post_roll
                    return
                self._finalize_locked(self._session["end_reason"])
        except Exception:
            pass

    def stop(self):
        """Finalize any active session immediately (no post-roll)."""
        try:
            with self._lock:
                if self._session is not None:
                    if not self._session["end_reason"]:
                        self._session["end_reason"] = "recorder_stop"
                    self._finalize_locked(self._session["end_reason"])
        except Exception:
            pass

    def close(self):
        """Finalize and shut down background threads (process teardown
        and tests). The recorder is unusable afterwards."""
        try:
            self.stop()
        except Exception:
            pass
        try:
            self._feeder_stop.set()
            self._closed = True
            if self._writer is not None:
                try:
                    self._queue.put_nowait(None)
                except Exception:
                    pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # inputs
    # ------------------------------------------------------------------
    def accept_frame(self, image_bytes, captured_at_epoch):
        """Offer one frame. Returns True when it was queued for saving.

        Sampling (configured interval), the per-battle frame cap and a
        full writer queue all drop frames quietly. Invalid data is
        recorded as a failed frame entry. Never raises."""
        try:
            if not self.enabled:
                return False
            captured_at = float(captured_at_epoch)
            with self._lock:
                session = self._session
                if session is None:
                    return False
                if (not isinstance(image_bytes, (bytes, bytearray))
                        or len(image_bytes) == 0):
                    session["frames"].append({
                        "file": None,
                        "captured_at": captured_at,
                        "captured_at_jst": jst_iso(captured_at),
                        "status": "failed",
                        "bytes": 0,
                        "error": "invalid_frame_data",
                    })
                    return False
                last = session["last_saved_at"]
                if (last is not None
                        and captured_at - last < self._config.interval_sec):
                    session["frames_skipped_sampling"] += 1
                    return False
                saved = sum(1 for f in session["frames"]
                            if f["status"] in ("queued", "ok"))
                if saved >= self._config.max_frames_per_battle:
                    session["frames_capped"] += 1
                    return False
                session["last_saved_at"] = captured_at
                index = sum(1 for f in session["frames"]
                            if f["file"] is not None) + 1
                filename = (f"frame_{index:06d}"
                            + _frame_extension(bytes(image_bytes[:8])))
                entry = {
                    "file": filename,
                    "captured_at": captured_at,
                    "captured_at_jst": jst_iso(captured_at),
                    "status": "queued",
                    "bytes": 0,
                }
                session["frames"].append(entry)
                try:
                    self._queue.put_nowait(
                        (session["dir"] / filename, bytes(image_bytes), entry))
                except queue.Full:
                    entry["status"] = "failed"
                    entry["error"] = "writer_queue_full"
                    session["frames_dropped_queue"] += 1
                    return False
                return True
        except Exception:
            return False

    def accept_event(self, method, received_at_epoch, battle_id=None):
        """Record the receive time of one of the reconciled methods.
        Never raises."""
        try:
            if not self.enabled:
                return
            if method not in EVIDENCE_METHODS:
                return
            received_at = float(received_at_epoch)
            with self._lock:
                session = self._session
                if session is None:
                    return
                session["events"].append({
                    "method": str(method),
                    "received_at": received_at,
                    "received_at_jst": jst_iso(received_at),
                    "battle_id": (str(battle_id)
                                  if battle_id is not None else None),
                })
        except Exception:
            pass

    def note_frame_failure(self, error="frame_source_error"):
        """Record a failed frame attempt (e.g. the frame source raised)
        without interrupting collection."""
        try:
            with self._lock:
                session = self._session
                if session is None:
                    return
                now = self._clock()
                session["frames"].append({
                    "file": None,
                    "captured_at": now,
                    "captured_at_jst": jst_iso(now),
                    "status": "failed",
                    "bytes": 0,
                    "error": str(error)[:120],
                })
        except Exception:
            pass

    # ------------------------------------------------------------------
    # background writer / feeder
    # ------------------------------------------------------------------
    def _ensure_writer_locked(self):
        if self._writer is None or not self._writer.is_alive():
            self._writer = threading.Thread(
                target=self._writer_loop, daemon=True,
                name="EvidenceWriter")
            self._writer.start()

    def _writer_loop(self):
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                path, data, entry = item
                try:
                    path.write_bytes(data)
                    entry["status"] = "ok"
                    entry["bytes"] = len(data)
                except OSError as exc:
                    entry["status"] = "failed"
                    entry["error"] = f"write_failed:{type(exc).__name__}"
            finally:
                self._queue.task_done()

    def flush(self, timeout=10.0):
        """Wait until queued frame writes have completed (tests and
        finalization)."""
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.01)
        return self._queue.unfinished_tasks == 0

    def _start_feeder_locked(self):
        if self._feeder is not None and self._feeder.is_alive():
            return
        self._feeder_stop.clear()
        self._feeder = threading.Thread(
            target=self._feeder_loop, daemon=True, name="EvidenceFeeder")
        self._feeder.start()

    def _feeder_loop(self):
        source = _LatestJpgSource(self._frame_path)
        # Best-effort pre-roll: the frame the collector most recently
        # wrote (at most 15 s old) becomes the session's first frame.
        try:
            stat = self._frame_path.stat()
            if self._clock() - stat.st_mtime <= 15.0:
                data = self._frame_path.read_bytes()
                if data:
                    source._last_mtime = stat.st_mtime
                    self.accept_frame(data, stat.st_mtime)
        except OSError:
            pass
        while not self._feeder_stop.is_set():
            try:
                item = source.poll()
                if item is not None:
                    data, captured_at = item
                    self.accept_frame(data, captured_at)
            except Exception:
                try:
                    self.note_frame_failure("frame_source_error")
                except Exception:
                    pass
            with self._lock:
                session = self._session
                ending_at = (session["ending_at"]
                             if session is not None else None)
            if ending_at is not None and self._clock() >= ending_at:
                with self._lock:
                    if self._session is not None:
                        self._finalize_locked(self._session["end_reason"]
                                              or "finished")
                return
            if session is None:
                return
            time.sleep(0.2)

    # ------------------------------------------------------------------
    # finalization
    # ------------------------------------------------------------------
    def _finalize_locked(self, reason):
        session = self._session
        if session is None:
            return
        self._session = None
        self._feeder_stop.set()
        try:
            self.flush(timeout=10.0)
        except Exception:
            pass
        ended_at = self._clock()
        frames = session["frames"]
        events = session["events"]
        ok_frames = [f for f in frames if f["status"] == "ok"]
        correspondence, sync = _build_correspondence(ok_frames, events)
        metadata = {
            "schema": SCHEMA,
            "observation_id": session["observation_id"],
            "battle_id": session["battle_id"],
            "context": session["context"],
            "started_at": session["started_at"],
            "started_at_jst": jst_iso(session["started_at"]),
            "started_at_source": "recorder_local_clock",
            "ended_at": ended_at,
            "ended_at_jst": jst_iso(ended_at),
            "ended_at_source": "recorder_local_clock",
            "end_reason": reason,
            "config": {
                "interval_sec": self._config.interval_sec,
                "post_roll_sec": self._config.post_roll_sec,
                "max_frames_per_battle": self._config.max_frames_per_battle,
            },
            "frames": frames,
            "events": events,
            "counts": {
                "frames_saved": len(ok_frames),
                "frames_failed": sum(1 for f in frames
                                     if f["status"] == "failed"),
                "frames_skipped_sampling": session["frames_skipped_sampling"],
                "frames_dropped_queue": session["frames_dropped_queue"],
                "frames_capped": session["frames_capped"],
                "events": len(events),
            },
            "sync": sync,
            # Verdict discipline: starts "unknown"; only a human may
            # change it, via set_human_verdict() -> human_verdict.json.
            "verdict": "unknown",
            "verdict_source": "default",
            "human_verdict": None,
        }
        try:
            _atomic_write_json(session["dir"] / "metadata.json", metadata)
        except OSError:
            pass
        try:
            _write_correspondence_csv(
                session["dir"] / "correspondence.csv", correspondence)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # retention / caps / deletion
    # ------------------------------------------------------------------
    def _session_started_at(self, session_dir):
        try:
            data = json.loads(
                (session_dir / "metadata.json").read_text(encoding="utf-8"))
            started = data.get("started_at")
            if isinstance(started, (int, float)):
                return float(started)
        except Exception:
            pass
        try:
            return session_dir.stat().st_mtime
        except OSError:
            return 0.0

    def list_sessions(self):
        """All finalized/active session dirs under the evidence root,
        oldest first."""
        try:
            if not self._root.exists():
                return []
            dirs = [p for p in self._root.iterdir() if p.is_dir()]
            dirs.sort(key=self._session_started_at)
            return dirs
        except Exception:
            return []

    def total_size_bytes(self):
        total = 0
        try:
            for path in self._root.rglob("*"):
                try:
                    if path.is_file():
                        total += path.stat().st_size
                except OSError:
                    continue
        except Exception:
            pass
        return total

    def purge_old_evidence(self):
        """Apply retention days, then the total-size cap, oldest first.
        The active session is never purged. Returns removed dirs."""
        removed = []
        try:
            if not self._root.exists():
                return removed
            with self._lock:
                active = (self._session["dir"]
                          if self._session is not None else None)
            sessions = self.list_sessions()
            now = self._clock()
            retention = self._config.retention_days
            survivors = []
            for session_dir in sessions:
                if active is not None and session_dir == active:
                    survivors.append(session_dir)
                    continue
                age_days = (now - self._session_started_at(session_dir)) / 86400.0
                if retention >= 0 and age_days > retention:
                    if delete_session(session_dir):
                        removed.append(session_dir)
                    continue
                survivors.append(session_dir)
            total = self.total_size_bytes()
            while total > self._config.max_total_bytes and survivors:
                victim = survivors.pop(0)
                if active is not None and victim == active:
                    break
                size = _dir_size(victim)
                if delete_session(victim):
                    removed.append(victim)
                    total -= size
                else:
                    break
            return removed
        except Exception:
            return removed


def _dir_size(path):
    total = 0
    try:
        for item in Path(path).rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                continue
    except Exception:
        pass
    return total


def delete_session(session_dir):
    """Remove one session directory tree. Returns True on success."""
    try:
        target = Path(session_dir)
        if target.is_dir():
            shutil.rmtree(target)
            return True
    except OSError:
        return False
    return False


def _atomic_write_json(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    os.replace(temp, path)


def _build_correspondence(ok_frames, events):
    """For each event, the nearest saved frames before/after it.

    Receive time (WebSocket) and frame capture time are kept distinct;
    the deltas are the sync-error record used later by a human.
    """
    rows = []
    max_abs_nearest = None
    within_2s = 0
    ordered = sorted(ok_frames, key=lambda f: f["captured_at"])
    for index, event in enumerate(events):
        received = event["received_at"]
        before = None
        after = None
        for frame in ordered:
            if frame["captured_at"] <= received:
                before = frame
            if frame["captured_at"] >= received and after is None:
                after = frame
        before_delta = (round((received - before["captured_at"]) * 1000)
                        if before is not None else None)
        after_delta = (round((after["captured_at"] - received) * 1000)
                       if after is not None else None)
        nearest = None
        nearest_delta = None
        candidates = []
        if before is not None:
            candidates.append((before_delta, before))
        if after is not None:
            candidates.append((after_delta, after))
        if candidates:
            _, nearest_frame = min(candidates, key=lambda c: c[0])
            nearest = nearest_frame["file"]
            nearest_delta = round(
                (nearest_frame["captured_at"] - received) * 1000)
            if max_abs_nearest is None or abs(nearest_delta) > max_abs_nearest:
                max_abs_nearest = abs(nearest_delta)
            if abs(nearest_delta) <= 2000:
                within_2s += 1
        rows.append({
            "event_index": index,
            "method": event["method"],
            "received_at": received,
            "received_at_jst": event["received_at_jst"],
            "frame_before": before["file"] if before is not None else "",
            "before_delta_ms": before_delta,
            "frame_after": after["file"] if after is not None else "",
            "after_delta_ms": after_delta,
            "nearest_frame": nearest or "",
            "nearest_delta_ms": nearest_delta,
        })
    sync = {
        "events_total": len(events),
        "events_with_frame_within_2s": within_2s,
        "max_abs_nearest_delta_ms": max_abs_nearest,
        "uncertainty_note": ("design treats screen/log sync as a +/-2 s "
                             "uncertainty interval; deltas are recorded, "
                             "never hidden"),
    }
    return rows, sync


def _write_correspondence_csv(path, rows):
    fields = ["event_index", "method", "received_at_jst", "received_at",
              "frame_before", "before_delta_ms", "frame_after",
              "after_delta_ms", "nearest_frame", "nearest_delta_ms"]
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fields})
    os.replace(temp, path)


def set_human_verdict(session_dir, verdict, note="", *, recorded_by="human",
                      clock=None):
    """Record a HUMAN verdict for a finalized session.

    This is the only way a session's verdict can leave "unknown".
    verdict must be "candidate" or "screen_confirmed". The record keeps
    the screen observation (what the human saw) separate from event
    meaning: a screen showing a x3 marker does not, by itself, prove
    that any particular notification event is x3-specific, so
    event_meaning is always recorded as undetermined here.
    """
    if verdict not in HUMAN_VERDICTS:
        raise ValueError(
            f"verdict must be one of {HUMAN_VERDICTS}, got {verdict!r}")
    target = Path(session_dir)
    if not target.is_dir():
        raise FileNotFoundError(f"session dir not found: {target}")
    now = (clock or time.time)()
    record = {
        "schema": "livemetry_evidence_human_verdict_v1",
        "verdict": verdict,
        "note": str(note or ""),
        "screen_observation": str(note or ""),
        "event_meaning": "not_determined_by_screen_alone",
        "recorded_by": str(recorded_by or "human"),
        "recorded_at": now,
        "recorded_at_jst": jst_iso(now),
    }
    _atomic_write_json(target / "human_verdict.json", record)
    metadata_path = target / "metadata.json"
    try:
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if isinstance(metadata, dict):
                metadata["verdict"] = verdict
                metadata["verdict_source"] = "human"
                metadata["human_verdict"] = record
                _atomic_write_json(metadata_path, metadata)
    except Exception:
        pass
    return record


def read_session(session_dir):
    """Load a session's metadata (+ human verdict when present)."""
    target = Path(session_dir)
    metadata = {}
    try:
        data = json.loads((target / "metadata.json").read_text(
            encoding="utf-8"))
        if isinstance(data, dict):
            metadata = data
    except Exception:
        metadata = {}
    human = None
    try:
        data = json.loads((target / "human_verdict.json").read_text(
            encoding="utf-8"))
        if isinstance(data, dict):
            human = data
    except Exception:
        human = None
    return {"dir": target, "metadata": metadata, "human_verdict": human,
            "size_bytes": _dir_size(target)}

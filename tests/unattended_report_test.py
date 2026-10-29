"""Tests for the unattended observation report (spec section 15).

Synthetic data only. Item 15 (regression of Phase A / opponent names /
Challenge Investigator) is covered by running those existing test files
in the same CI step, not from inside this file.
Run: python tests/unattended_report_test.py
"""
import json
import sqlite3
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.observation_sessions import SessionStore, get_runtime  # noqa: E402
from core.unattended_report import available_sources, build_report  # noqa: E402
from core.report_export import export_csv, export_json, export_pdf  # noqa: E402
from core import report_ai  # noqa: E402

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    (PASSED if condition else FAILED).append(name)
    print(("PASS " if condition else "FAIL ") + name + (f" :: {detail}" if detail and not condition else ""))


T0 = 1_762_000_000.0
SCHEMA = """
CREATE TABLE battles (unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
    first_seen REAL NOT NULL, last_seen REAL NOT NULL, status TEXT NOT NULL,
    payload TEXT NOT NULL, PRIMARY KEY(unique_id, battle_id));
CREATE TABLE snapshots (unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
    received_at REAL NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
    UNIQUE(unique_id, battle_id, fingerprint));
CREATE TABLE comments (unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
    received_at REAL NOT NULL, username TEXT NOT NULL, comment TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE);
CREATE TABLE excluded_battles (unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
    reason TEXT NOT NULL, excluded_at REAL NOT NULL, PRIMARY KEY(unique_id, battle_id));
CREATE TABLE viewer_samples (unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
    received_at REAL NOT NULL, elapsed_seconds REAL, viewer_count INTEGER NOT NULL,
    PRIMARY KEY(unique_id, battle_id, received_at));
"""


def payload(host=1001, score=500, known=True, start_ms=None, nickname="Host", mode="individual"):
    entry = {"anchor_id": str(host), "score": score, "score_known": known,
             "nickname": nickname, "unique_id": "hostunique"}
    data = {"mode": mode, "host_user_id": str(host), "host_nickname": nickname,
            "participants": [entry], "active": False}
    if start_ms is not None:
        data["start_time_ms"] = start_ms
    return data


def make_db(directory):
    path = Path(directory) / "battle_dataset" / "battles.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    db.commit()
    return path, db


_fp = [0]


def add_battle(db, uid, bid, first, last, status, data):
    db.execute("INSERT INTO battles VALUES (?,?,?,?,?,?)",
               (uid, bid, first, last, status, json.dumps(data)))
    db.commit()


def add_snapshot(db, uid, bid, at, data):
    _fp[0] += 1
    db.execute("INSERT INTO snapshots VALUES (?,?,?,?,?)",
               (uid, bid, at, f"fp{_fp[0]}", json.dumps(data)))
    db.commit()


def add_viewer(db, uid, bid, at, count):
    db.execute("INSERT INTO viewer_samples VALUES (?,?,?,?,?)",
               (uid, bid, at, None, count))
    db.commit()


def main():
    tmp = Path(tempfile.mkdtemp(prefix="unattended_report_test_"))
    capture = tmp / "capture"
    capture.mkdir()

    # ---- 1. session start/stop -------------------------------------
    store = SessionStore(capture)
    session = store.start_session("Battle Hunter", ["alice"], profile="capture", now=T0)
    sid = session["session_id"]
    check("1a session starts running", session["end_kind"] == "running")
    store.heartbeat(sid, True, last_data_at=T0 + 30, now=T0 + 30)
    store.heartbeat(sid, True, last_data_at=T0 + 60, now=T0 + 60)
    mid = store.get_session(sid)
    check("1b heartbeat accumulates monitored seconds",
          mid["monitored_seconds"] == 60 and mid["disconnected_seconds"] == 0)
    stopped = store.stop_session(sid, end_kind="normal", now=T0 + 3600)
    check("1c stop records end", stopped["end_kind"] == "normal" and stopped["ended_at"] == T0 + 3600)

    # ---- crash recovery ---------------------------------------------
    # A crash means the owning process is gone: simulate the next
    # process (different token) finding the session with a stale
    # heartbeat. Same-process recovery is covered by F1a and must
    # never fire.
    crashed = store.start_session("Battle Hunter", ["bob"], profile="capture", now=T0)
    store.heartbeat(crashed["session_id"], True, now=T0 + 10)
    store2 = SessionStore(capture, process_token="next-process")
    recovered = store2.recover_interrupted(now=T0 + 9999)
    after = store2.get_session(crashed["session_id"])
    check("R1 crashed session recovered as interrupted",
          crashed["session_id"] in recovered and after["end_kind"] == "interrupted")
    check("R2 guessed end time is NOT stored", after["ended_at"] is None)

    # ---- 2. 7-hour synthetic session --------------------------------
    db_path, db = make_db(capture)
    seven_h = store.start_session("Battle Hunter", ["alice"], profile="capture", now=T0)
    for i in range(24):
        start = T0 + i * 1050
        data = payload(score=100 * (i + 1), start_ms=int(start * 1000))
        add_battle(db, "alice", 5000 + i, start, start + 900, "finished", data)
        for step in range(10):
            add_snapshot(db, "alice", 5000 + i, start + step * 90,
                         payload(score=10 * (step + 1), start_ms=int(start * 1000)))
            add_viewer(db, "alice", 5000 + i, start + step * 90, 50 + step)
    store.stop_session(seven_h["session_id"], end_kind="normal", now=T0 + 7 * 3600)
    report7 = build_report(db_path, {"kind": "session"},
                           session=store.get_session(seven_h["session_id"]), profile="capture")
    check("2a 7h session aggregates", report7["summary"]["record_count"] == 24)
    check("2b observed seconds ~7h", abs(report7["summary"]["observed_seconds"] - 7 * 3600) < 1)
    check("2c finished count", report7["summary"]["finished_confirmed"] == 24)

    # ---- 3. partial battle -------------------------------------------
    pdata = payload(score=700, start_ms=int((T0 - 300) * 1000))
    add_battle(db, "alice", 6001, T0, T0 + 600, "finished", pdata)
    fdata = payload(score=800, start_ms=int((T0 - 5) * 1000))
    add_battle(db, "alice", 6002, T0, T0 + 600, "finished", fdata)
    rep = build_report(db_path, {"kind": "period", "start": T0 - 400, "end": T0 + 700,
                                 "streamers": ["alice"]}, profile="capture")
    by_id = {b["battle_id"]: b for b in rep["battles"]}
    check("3a late-observed battle is partial", by_id[6001]["partial_state"] == "partial")
    check("3b on-time battle is full", by_id[6002]["partial_state"] == "full")
    check("3c partial counted separately", rep["summary"]["partial_battles"] == 1)

    # ---- 4. disconnect / stopped session aggregation ------------------
    disc = store.start_session("Battle Hunter", ["alice"], profile="capture", now=T0)
    store.heartbeat(disc["session_id"], True, now=T0 + 10)
    store.heartbeat(disc["session_id"], False, now=T0 + 40)
    store.record_event(disc["session_id"], "disconnect_start", {}, now=T0 + 15)
    store.stop_session(disc["session_id"], end_kind="normal", now=T0 + 100)
    rep4 = build_report(db_path, {"kind": "session"},
                        session=store.get_session(disc["session_id"]), profile="capture")
    check("4a disconnect seconds measured", rep4["session"]["disconnected_seconds"] == 30)
    check("4b error/disconnect count from events", rep4["summary"]["error_count"] == 1)

    # ---- 5. duplicate battle across streamers -------------------------
    dup_data = payload(score=300, start_ms=int(T0 * 1000))
    add_battle(db, "carol", 7001, T0, T0 + 300, "finished", dup_data)
    add_battle(db, "dave", 7001, T0, T0 + 300, "finished", dup_data)
    rep5 = build_report(db_path, {"kind": "period", "start": T0 - 10, "end": T0 + 400,
                                  "streamers": ["carol", "dave"]}, profile="capture")
    check("5a records counted per observation", rep5["summary"]["record_count"] == 2)
    check("5b unique battles counted once", rep5["summary"]["unique_battle_count"] == 1)

    # ---- 6. real zero vs unknown score --------------------------------
    add_battle(db, "erin", 8001, T0, T0 + 300, "finished",
               payload(score=0, known=True, start_ms=int(T0 * 1000)))
    add_battle(db, "erin", 8002, T0, T0 + 300, "finished",
               payload(score=0, known=False, start_ms=int(T0 * 1000)))
    rep6 = build_report(db_path, {"kind": "period", "start": T0 - 10, "end": T0 + 400,
                                  "streamers": ["erin"]}, profile="capture")
    by6 = {b["battle_id"]: b for b in rep6["battles"]}
    check("6a real zero is known", by6[8001]["final_score"] == 0 and by6[8001]["score_known"])
    check("6b unknown is not zero", by6[8002]["final_score"] is None and not by6[8002]["score_known"])
    check("6c median uses known only", rep6["summary"]["final_score_median"] == 0
          and rep6["summary"]["score_known_battles"] == 1)

    # ---- 7. viewers missing -------------------------------------------
    check("7a battle without viewer samples stays None",
          by6[8001]["viewer_median"] is None and by6[8001]["viewer_peak"] is None)
    check("7b summary viewer median is None, not 0", rep6["summary"]["viewer_median"] is None)

    # ---- 8. capture vs capture_fixed separation ------------------------
    fixed_dir = tmp / "capture_fixed"
    fixed_dir.mkdir()
    fixed_path, fixed_db = make_db(fixed_dir)
    add_battle(fixed_db, "alice", 9001, T0, T0 + 300, "finished",
               payload(score=999, start_ms=int(T0 * 1000)))
    rep_fixed = build_report(fixed_path, {"kind": "all"}, profile="capture_fixed")
    rep_main = build_report(db_path, {"kind": "period", "start": T0 - 10, "end": T0 + 400,
                                      "streamers": ["alice"]}, profile="capture")
    check("8a fixed report has only fixed data",
          rep_fixed["summary"]["record_count"] == 1
          and rep_fixed["battles"][0]["battle_id"] == 9001)
    check("8b capture report excludes fixed battle",
          all(b["battle_id"] != 9001 for b in rep_main["battles"]))

    # ---- 9. multi-streamer separation ----------------------------------
    rep9 = build_report(db_path, {"kind": "period", "start": T0 - 10, "end": T0 + 400,
                                  "streamers": ["carol", "dave"]}, profile="capture")
    per = {row["unique_id"]: row for row in rep9["per_streamer"]}
    check("9a per-streamer rows stay separate",
          set(per) == {"carol", "dave"} and per["carol"]["records"] == 1
          and per["dave"]["records"] == 1)

    # ---- 10. exports ----------------------------------------------------
    out = tmp / "out"
    out.mkdir()
    export_json(rep9, out / "report.json")
    loaded = json.loads((out / "report.json").read_text(encoding="utf-8"))
    check("10a JSON has schema version", loaded["schema_version"] == "livemetry_unattended_report_v1")
    export_csv(rep6, out / "report.csv")
    csv_lines = (out / "report.csv").read_text(encoding="utf-8-sig").strip().splitlines()
    check("10b CSV rows = battles + header", len(csv_lines) == 3)
    check("10c CSV unknown score cell is blank", csv_lines[2].split(",")[7] == "")
    export_pdf(rep9, out / "report.pdf")
    check("10d PDF generated", (out / "report.pdf").read_bytes()[:4] == b"%PDF")

    # ---- 11. empty data --------------------------------------------------
    empty_report = build_report(tmp / "missing.sqlite3", {"kind": "all"}, profile="capture")
    check("11a missing DB does not crash", empty_report["summary"]["record_count"] == 0)
    export_csv(empty_report, out / "empty.csv")
    export_pdf(empty_report, out / "empty.pdf")
    check("11b empty exports still produced",
          (out / "empty.csv").exists() and (out / "empty.pdf").read_bytes()[:4] == b"%PDF")

    # ---- 12/13. AI: explicit only, aggregates only, failure-safe ---------
    calls = []

    class FakeClient:
        def analyze_image(self, image_path, prompt):
            calls.append(prompt)
            return "① 今回の観測結果：テスト応答"

    class BrokenClient:
        def analyze_image(self, image_path, prompt):
            raise RuntimeError("AI unavailable")

    build_report(db_path, {"kind": "all"}, profile="capture")
    report_ai.evidence_preview(rep9)
    export_json(rep9, out / "again.json")
    check("13a no AI call without explicit analyze", len(calls) == 0)
    payload_ai, _, _ = report_ai.analyze(rep9, client=FakeClient(), folder=out / "ai")
    check("13b explicit analyze calls once", len(calls) == 1)
    sent = calls[0]
    check("13c no streamer id/name/comment in payload",
          "carol" not in sent and "dave" not in sent and "hostunique" not in sent
          and "R0001" in sent)
    try:
        report_ai.analyze(rep9, client=BrokenClient(), folder=out / "ai")
        ai_raised = False
    except RuntimeError:
        ai_raised = True
    check("12a AI failure surfaces as error", ai_raised)
    still = build_report(db_path, {"kind": "all"}, profile="capture")
    check("12b statistics report works without AI", still["summary"]["record_count"] > 0)

    # ---- 14. large data ---------------------------------------------------
    big_dir = tmp / "big"
    big_dir.mkdir()
    big_path, big_db = make_db(big_dir)
    add_battle(big_db, "alice", 4242, T0, T0 + 20000, "finished",
               payload(score=20000, start_ms=int(T0 * 1000)))
    for i in range(20000):
        add_snapshot(big_db, "alice", 4242, T0 + i, payload(score=i, start_ms=int(T0 * 1000)))
    tracemalloc.start()
    began = time.time()
    big_report = build_report(big_path, {"kind": "all"}, profile="capture")
    elapsed = time.time() - began
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    battle = big_report["battles"][0]
    check("14a 20k snapshots aggregate", battle["score_sample_count"] == 20000)
    check("14b series downsampled to cap", battle["series_downsampled"]
          and len(battle["score_series"]) <= 501)
    check("14c aggregation stays fast", elapsed < 30, f"{elapsed:.1f}s")
    print(f"     (14: elapsed {elapsed:.2f}s, tracemalloc peak {peak / 1e6:.1f} MB)")

    # ---- F1. recovery never kills a live session (PR #8 review #1) -----
    f1_dir = tmp / "f1"
    f1_dir.mkdir()
    store_a = SessionStore(f1_dir, process_token="proc-A")
    live = store_a.start_session("Battle Hunter", ["x"], profile="capture", now=T0)
    live_id = live["session_id"]
    check("F1a own-process live session is never recovered",
          store_a.recover_interrupted(now=T0 + 5) == []
          and store_a.get_session(live_id)["end_kind"] == "running")
    store_b = SessionStore(f1_dir, process_token="proc-B")
    check("F1b foreign session with fresh heartbeat is not recovered",
          store_b.recover_interrupted(now=T0 + 30) == []
          and store_b.get_session(live_id)["end_kind"] == "running")
    check("F1c stale foreign session is recovered, end time unguessed",
          store_b.recover_interrupted(now=T0 + 10000) == [live_id]
          and store_b.get_session(live_id)["end_kind"] == "interrupted"
          and store_b.get_session(live_id)["ended_at"] is None)

    # ---- F2. session lifetime is independent of the page (review #2) ---
    f2_dir = tmp / "f2"
    f2_dir.mkdir()
    runtime = get_runtime(f2_dir)
    sess = runtime.start_session("Battle Hunter", ["y"], profile="capture")
    sampler = runtime._samplers[sess["session_id"]]
    check("F2a runtime starts the sampler", sampler._thread.is_alive())
    # A page being destroyed never touches the runtime: the sampler and
    # the session must still be alive afterwards.
    check("F2b sampler survives page teardown",
          sampler._thread.is_alive()
          and runtime.store.get_session(sess["session_id"])["end_kind"] == "running")
    runtime.stop_session(sess["session_id"], auto_report=False)
    check("F2c runtime stop ends sampler and session",
          not sampler._thread.is_alive()
          and runtime.store.get_session(sess["session_id"])["end_kind"] == "normal")
    sess2 = runtime.start_session("Battle Hunter", ["y"], profile="capture")
    lost = runtime._samplers.pop(sess2["session_id"])
    lost.stop()
    runtime.ensure_all_sampling()
    check("F2d sampling reattaches for a running session",
          runtime._samplers[sess2["session_id"]]._thread.is_alive())
    runtime.stop_session(sess2["session_id"], auto_report=False)

    # ---- F3. TopWatch real layout (review #3) ---------------------------
    f3_base = tmp / "f3base"
    tw_dir = f3_base / "top_watch" / "alice" / "AI-TikTok-LIVE-Analyzer" / "capture_fixed"
    make_db(tw_dir)
    tw_sources = [s for s in available_sources(base=f3_base)
                  if s["key"].startswith("topwatch:")]
    check("F3a nested TopWatch layout is found",
          len(tw_sources) == 1 and tw_sources[0]["streamer_hint"] == "alice")
    check("F3b TopWatch database path is the real one",
          Path(tw_sources[0]["database"]) == tw_dir / "battle_dataset" / "battles.sqlite3")

    # ---- F4. window clipping (review #4) --------------------------------
    f4_dir = tmp / "f4"
    f4_dir.mkdir()
    f4_path, f4_db = make_db(f4_dir)
    add_battle(f4_db, "frank", 9501, T0 - 600, T0 + 1200, "finished",
               payload(score=800, start_ms=int((T0 - 600) * 1000)))
    for at, value in ((T0 - 300, 100), (T0 + 100, 200), (T0 + 500, 400), (T0 + 1100, 800)):
        add_snapshot(f4_db, "frank", 9501, at, payload(score=value, start_ms=int((T0 - 600) * 1000)))
    for at, count in ((T0 - 300, 10), (T0 + 100, 20), (T0 + 1100, 99)):
        add_viewer(f4_db, "frank", 9501, at, count)
    rep_f4 = build_report(f4_path, {"kind": "period", "start": T0, "end": T0 + 600,
                                    "streamers": ["frank"]}, profile="capture")
    b_f4 = rep_f4["battles"][0]
    check("F4a only in-window score samples are aggregated",
          b_f4["score_sample_count"] == 2
          and [p["v"] for p in b_f4["score_series"]] == [200, 400])
    check("F4b only in-window viewer samples are aggregated",
          b_f4["viewer_sample_count"] == 1 and b_f4["viewer_peak"] == 20)
    check("F4c spanning battle is flagged as window-clipped",
          b_f4["starts_before_window"] and b_f4["ends_after_window"] and b_f4["window_clipped"])
    check("F4d clipped final score kept per-battle but out of the summary",
          b_f4["final_score"] == 800
          and rep_f4["summary"]["final_score_median"] is None
          and rep_f4["summary"]["clipped_final_score_battles"] == 1
          and rep_f4["summary"]["window_clipped_battles"] == 1)
    check("F4e in-window end score is available", b_f4["score_at_window_end"] == 400)

    # ---- F5. unfinished battles have no final score (review #5) ---------
    f5_dir = tmp / "f5"
    f5_dir.mkdir()
    f5_path, f5_db = make_db(f5_dir)
    add_battle(f5_db, "gina", 9601, T0, T0 + 300, "timeout_fallback",
               payload(score=1234, start_ms=int(T0 * 1000)))
    add_battle(f5_db, "gina", 9602, T0, T0 + 300, "active",
               payload(score=55, start_ms=int(T0 * 1000)))
    rep_f5 = build_report(f5_path, {"kind": "period", "start": T0 - 10, "end": T0 + 400,
                                    "streamers": ["gina"]}, profile="capture")
    by5 = {b["battle_id"]: b for b in rep_f5["battles"]}
    check("F5a unfinished battles expose no final score",
          by5[9601]["final_score"] is None and by5[9602]["final_score"] is None)
    check("F5b latest known score is kept separate",
          by5[9601]["last_known_score"] == 1234 and by5[9602]["last_known_score"] == 55)
    check("F5c summary excludes them from final-score stats",
          rep_f5["summary"]["score_known_battles"] == 0
          and rep_f5["summary"]["final_score_median"] is None
          and rep_f5["summary"]["last_known_score_battles"] == 2)
    export_csv(rep_f5, out / "f5.csv")
    f5_lines = (out / "f5.csv").read_text(encoding="utf-8-sig").strip().splitlines()
    row_9601 = next(line for line in f5_lines if ",9601," in line).split(",")
    check("F5d CSV final cell blank, reference score in its own column",
          row_9601[7] == "" and row_9601[8] == "1234")

    # ---- F6. automatic report on session stop (review #6) ---------------
    f6_dir = tmp / "f6"
    f6_dir.mkdir()
    runtime6 = get_runtime(f6_dir)
    sess6 = runtime6.start_session("Battle Hunter", ["henry"], profile="capture")
    runtime6.stop_session(sess6["session_id"])
    reports_dir = f6_dir / "observation_report" / "reports"
    generated = None
    deadline = time.time() + 10
    while time.time() < deadline:
        if reports_dir.exists():
            files = sorted(reports_dir.glob("report_*.json"))
            if files and runtime6.store.get_session(sess6["session_id"])["report_state"] == "generated":
                generated = files[-1]
                break
        time.sleep(0.2)
    check("F6a session stop auto-generates the JSON report", generated is not None)
    if generated is not None:
        auto = json.loads(generated.read_text(encoding="utf-8"))
        check("F6b auto trigger is recorded in the report",
              auto["generation"]["trigger"] == "auto_session_stop")
    f6b_dir = tmp / "f6b"
    (f6b_dir / "observation_report").mkdir(parents=True)
    (f6b_dir / "observation_report" / "reports").write_text("blocked", encoding="utf-8")
    runtime6b = get_runtime(f6b_dir)
    sess6b = runtime6b.start_session("Battle Hunter", ["henry"], profile="capture")
    stopped6b = runtime6b.stop_session(sess6b["session_id"])
    time.sleep(1.0)
    check("F6c failed auto-report never breaks the stop",
          stopped6b["end_kind"] == "normal"
          and runtime6b.store.get_session(sess6b["session_id"])["report_state"] == "none")

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("FAILED:", FAILED)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

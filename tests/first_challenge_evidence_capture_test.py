"""Phase D tests: screen-evidence capture (core/evidence_capture.py).

Run from the project root:
    python tests/first_challenge_evidence_capture_test.py

Uses fake frame bytes and a controllable clock in temp dirs only.
No network, no real stream, no image analysis anywhere.
"""

import csv
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.evidence_capture import (
    EVIDENCE_METHODS,
    EvidenceConfig,
    EvidenceRecorder,
    delete_session,
    in_top_watch_sandbox,
    jst_iso,
    load_config,
    read_session,
    sanitize_battle_context,
    set_human_verdict,
)

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  ok: {name}")
    else:
        print(f"  FAIL: {name} {detail}")
        FAILURES.append(name)


class FakeClock:
    def __init__(self, start=1_700_000_000.0):
        self.now = float(start)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


JPEG_A = b"\xff\xd8\xff\xe0" + b"A" * 200
JPEG_B = b"\xff\xd8\xff\xe0" + b"B" * 200


def make_recorder(base, clock, **config_kwargs):
    config_kwargs.setdefault("enabled", True)
    config_kwargs.setdefault("post_roll_sec", 0)
    return EvidenceRecorder(base, EvidenceConfig(**config_kwargs),
                            clock=clock)


def read_metadata(session_dir):
    return json.loads(
        (Path(session_dir) / "metadata.json").read_text(encoding="utf-8"))


print("== helpers ==")
check("jst_iso epoch 0", jst_iso(0) == "1970-01-01T09:00:00.000+09:00")
check("load_config defaults off",
      load_config({}).enabled is False)
check("load_config defensive",
      load_config({"evidence_capture_enabled": "yes",
                   "evidence_interval_sec": "junk",
                   "evidence_max_total_mb": -5}).interval_sec == 2.0)
cfg = load_config({"evidence_capture_enabled": True,
                   "evidence_interval_sec": 99,
                   "evidence_post_roll_sec": -1})
check("load_config clamps interval to 5", cfg.interval_sec == 5.0)
check("load_config clamps post_roll to 0", cfg.post_roll_sec == 0.0)
check("top_watch sandbox detected",
      in_top_watch_sandbox("/x/top_watch/uid/AI-TikTok-LIVE-Analyzer/capture_fixed"))
check("normal capture not sandbox",
      not in_top_watch_sandbox("/x/AI-TikTok-LIVE-Analyzer/capture"))

print("== 1. disabled: nothing is written ==")
with tempfile.TemporaryDirectory() as tmp:
    clock = FakeClock()
    rec = EvidenceRecorder(Path(tmp) / "capture",
                           EvidenceConfig(enabled=False), clock=clock)
    check("start_battle returns None", rec.start_battle("111", {}) is None)
    check("accept_frame False", rec.accept_frame(JPEG_A, clock()) is False)
    rec.accept_event("WebcastGiftMessage", clock(), "111")
    rec.finish_battle()
    rec.stop()
    check("no evidence root created", not (Path(tmp) / "capture" / "evidence").exists())
    rec.close()

print("== 1b. from_app_settings: settings file + TopWatch inertness ==")
with tempfile.TemporaryDirectory() as tmp:
    app_dir = Path(tmp) / "AI-TikTok-LIVE-Analyzer"
    capture = app_dir / "capture"
    capture.mkdir(parents=True)
    (app_dir / "settings.json").write_text(json.dumps({
        "evidence_capture_enabled": True, "evidence_interval_sec": 3,
    }), encoding="utf-8")
    rec = EvidenceRecorder.from_app_settings(capture, clock=FakeClock())
    check("enabled from settings", rec.enabled is True)
    check("interval from settings", rec.config.interval_sec == 3.0)
    rec.close()

    sandbox_app = Path(tmp) / "top_watch" / "someone" / "AI-TikTok-LIVE-Analyzer"
    sandbox_capture = sandbox_app / "capture_fixed"
    sandbox_capture.mkdir(parents=True)
    (sandbox_app / "settings.json").write_text(json.dumps({
        "evidence_capture_enabled": True,
    }), encoding="utf-8")
    rec2 = EvidenceRecorder.from_app_settings(sandbox_capture, clock=FakeClock())
    check("inert inside TopWatch sandbox", rec2.enabled is False)
    check("sandbox start writes nothing",
          rec2.start_battle("1", {}) is None
          and not (sandbox_capture / "evidence").exists())
    rec2.close()

print("== 2. enabled: frames, JST ms timestamps, sampling ==")
with tempfile.TemporaryDirectory() as tmp:
    clock = FakeClock()
    rec = make_recorder(Path(tmp) / "capture", clock, interval_sec=2.0)
    session = rec.start_battle("222", {"mode": "individual",
                                       "participants": [{}, {}]})
    check("session dir created", session is not None and session.is_dir())
    t0 = clock()
    check("frame 1 saved", rec.accept_frame(JPEG_A, t0) is True)
    check("frame at +0.5 skipped", rec.accept_frame(JPEG_B, t0 + 0.5) is False)
    check("frame at +1.9 skipped", rec.accept_frame(JPEG_B, t0 + 1.9) is False)
    check("frame at +2.0 saved", rec.accept_frame(JPEG_B, t0 + 2.0) is True)
    check("frame at +3.0 skipped", rec.accept_frame(JPEG_A, t0 + 3.0) is False)
    rec.finish_battle("finished")
    meta = read_metadata(session)
    check("2 frames saved", meta["counts"]["frames_saved"] == 2)
    check("3 frames skipped by sampling",
          meta["counts"]["frames_skipped_sampling"] == 3)
    first = meta["frames"][0]
    check("frame timestamp JST ms",
          first["captured_at_jst"] == jst_iso(t0)
          and first["captured_at_jst"].endswith("+09:00")
          and "." in first["captured_at_jst"])
    check("frame file on disk",
          (session / first["file"]).read_bytes() == JPEG_A)
    check("session started_at_jst JST",
          meta["started_at_jst"] == jst_iso(t0))
    check("verdict starts unknown", meta["verdict"] == "unknown")
    check("human_verdict empty", meta["human_verdict"] is None)
    rec.close()

print("== 3. frame failures never break collection ==")
with tempfile.TemporaryDirectory() as tmp:
    clock = FakeClock()
    rec = make_recorder(Path(tmp) / "capture", clock, interval_sec=1.0)
    session = rec.start_battle("333", {})
    t0 = clock()
    check("None frame rejected quietly", rec.accept_frame(None, t0) is False)
    check("empty frame rejected quietly", rec.accept_frame(b"", t0) is False)
    rec.note_frame_failure("simulated_source_error")
    check("good frame still saved", rec.accept_frame(JPEG_A, t0 + 1.0) is True)
    rec.finish_battle()
    meta = read_metadata(session)
    check("failures recorded", meta["counts"]["frames_failed"] == 3,
          str(meta["counts"]))
    check("good frame counted", meta["counts"]["frames_saved"] == 1)
    statuses = [f["status"] for f in meta["frames"]]
    check("failed entries have no file",
          all(f["file"] is None for f in meta["frames"]
              if f["status"] == "failed"))
    check("status sequence sane", statuses[-1] == "ok")
    rec.close()

print("== 4. correspondence: sync-error deltas ==")
with tempfile.TemporaryDirectory() as tmp:
    clock = FakeClock()
    rec = make_recorder(Path(tmp) / "capture", clock, interval_sec=1.0)
    session = rec.start_battle("444", {})
    t0 = clock()
    rec.accept_frame(JPEG_A, t0)               # frame_000001 @ t0
    rec.accept_frame(JPEG_B, t0 + 10.0)        # frame_000002 @ t0+10
    rec.accept_event("WebcastGiftMessage", t0 + 3.0, "444")
    rec.accept_event("WebcastBattleGameplayMessage", t0 + 10.0, "444")
    rec.accept_event("WebcastLinkMicBattle", t0 + 25.0, "444")
    rec.accept_event("WebcastChatMessage", t0 + 4.0, "444")  # not reconciled
    rec.finish_battle()
    meta = read_metadata(session)
    check("only reconciled methods recorded", meta["counts"]["events"] == 3)
    check("method set matches spec",
          EVIDENCE_METHODS == {
              "WebcastBattleGameplayMessage",
              "WebcastLinkmicBattleTaskMessage",
              "WebcastGiftMessage",
              "WebcastLinkMicBattle",
              "WebcastLinkMicOpponentGifts",
          })
    rows = list(csv.DictReader(
        (session / "correspondence.csv").open(encoding="utf-8")))
    check("3 correspondence rows", len(rows) == 3)
    gift = rows[0]
    check("gift before frame", gift["frame_before"] == "frame_000001.jpg")
    check("gift before delta", gift["before_delta_ms"] == "3000")
    check("gift after frame", gift["frame_after"] == "frame_000002.jpg")
    check("gift after delta", gift["after_delta_ms"] == "7000")
    check("gift nearest delta", gift["nearest_delta_ms"] == "-3000")
    game = rows[1]
    check("gameplay nearest is frame 2", game["nearest_frame"] == "frame_000002.jpg")
    check("gameplay nearest delta 0", game["nearest_delta_ms"] == "0")
    late = rows[2]
    check("late event has no after frame", late["frame_after"] == "")
    check("late nearest delta", late["nearest_delta_ms"] == "-15000")
    check("sync summary recorded",
          meta["sync"]["max_abs_nearest_delta_ms"] == 15000
          and meta["sync"]["events_with_frame_within_2s"] == 1)
    rec.close()

print("== 5. caps: per-battle frames, total size, retention ==")
with tempfile.TemporaryDirectory() as tmp:
    clock = FakeClock()
    rec = make_recorder(Path(tmp) / "capture", clock, interval_sec=1.0,
                        max_frames_per_battle=2)
    session = rec.start_battle("555", {})
    t0 = clock()
    results = [rec.accept_frame(JPEG_A, t0 + i * 2.0) for i in range(4)]
    check("frame cap holds", results == [True, True, False, False])
    rec.finish_battle()
    meta = read_metadata(session)
    check("capped counted", meta["counts"]["frames_capped"] == 2)
    rec.close()

with tempfile.TemporaryDirectory() as tmp:
    clock = FakeClock()
    base = Path(tmp) / "capture"
    rec = make_recorder(base, clock, interval_sec=1.0, retention_days=365)
    dirs = []
    for i, bid in enumerate(("601", "602", "603")):
        s = rec.start_battle(bid, {})
        rec.accept_frame(JPEG_A, clock())
        rec.finish_battle()
        dirs.append(s)
        clock.advance(60)
    sizes = [sum(p.stat().st_size for p in s.rglob("*") if p.is_file())
             for s in dirs]
    rec.config.max_total_bytes = sizes[2]  # room for the newest only
    removed = rec.purge_old_evidence()
    check("oldest purged first",
          dirs[0] in removed and dirs[1] in removed and dirs[2] not in removed)
    check("survivor kept", dirs[2].is_dir() and not dirs[0].exists())
    check("total within cap", rec.total_size_bytes() <= sizes[2])
    rec.close()

with tempfile.TemporaryDirectory() as tmp:
    clock = FakeClock()
    rec = make_recorder(Path(tmp) / "capture", clock, retention_days=14)
    old = rec.start_battle("701", {})
    rec.accept_frame(JPEG_A, clock())
    rec.finish_battle()
    clock.advance(30 * 86400)
    removed = rec.purge_old_evidence()
    check("retention purges old session", old in removed and not old.exists())
    rec.close()

print("== 6. battle formats: 1v1 / 3-player / 2v2 context ==")
with tempfile.TemporaryDirectory() as tmp:
    clock = FakeClock()
    rec = make_recorder(Path(tmp) / "capture", clock, interval_sec=1.0)
    cases = [
        ("801", {"mode": "individual",
                 "participants": [{"anchor_id": "a1"}, {"anchor_id": "a2"}],
                 "host_nickname": "SECRETNAME1"},
         {"mode": "individual", "participant_count": 2}),
        ("802", {"mode": "individual",
                 "participants": [{"anchor_id": "a1"}, {"anchor_id": "a2"},
                                  {"anchor_id": "a3"}]},
         {"mode": "individual", "participant_count": 3}),
        ("803", {"mode": "team",
                 "teams": [{"team_id": "t1", "users": [{"user_id": "u1"},
                                                       {"user_id": "u2"}]},
                           {"team_id": "t2", "users": [{"user_id": "u3"},
                                                       {"user_id": "u4"}]}]},
         {"mode": "team", "participant_count": 4, "team_count": 2,
          "team_sizes": [2, 2]}),
    ]
    for bid, payload, expected in cases:
        session = rec.start_battle(bid, payload)
        rec.accept_frame(JPEG_A, clock())
        rec.finish_battle()
        meta = read_metadata(session)
        ok = all(meta["context"].get(k) == v for k, v in expected.items())
        check(f"context {bid}", ok, str(meta["context"]))
        raw = (session / "metadata.json").read_text(encoding="utf-8")
        check(f"no personal data {bid}",
              "SECRETNAME1" not in raw
              and '"anchor_id"' not in raw
              and '"user_id"' not in raw
              and '"host_nickname"' not in raw)
    rec.close()

ctx = sanitize_battle_context({"mode": "individual",
                               "participants": [{"anchor_id": "999888"}],
                               "host_nickname": "someone",
                               "unique_id": "somehandle"})
check("sanitize drops ids and names",
      ctx == {"mode": "individual", "participant_count": 1})

print("== 7. no false confirmation ==")
with tempfile.TemporaryDirectory() as tmp:
    clock = FakeClock()
    rec = make_recorder(Path(tmp) / "capture", clock, interval_sec=1.0)
    session = rec.start_battle("901", {})
    rec.accept_frame(JPEG_A, clock())
    rec.accept_event("WebcastBattleGameplayMessage", clock(), "901")
    rec.finish_battle()
    meta = read_metadata(session)
    check("verdict unknown after finalize", meta["verdict"] == "unknown")
    check("no human verdict file", not (session / "human_verdict.json").exists())
    check("recorder exposes no verdict setter",
          not hasattr(rec, "set_human_verdict"))
    try:
        set_human_verdict(session, "confirmed", "x")
        check("invalid verdict rejected", False)
    except ValueError:
        check("invalid verdict rejected", True)
    record = set_human_verdict(session, "screen_confirmed",
                               "x3 marker visible 12.0s-42.0s on screen")
    check("human verdict recorded", record["verdict"] == "screen_confirmed")
    check("event meaning stays undetermined",
          record["event_meaning"] == "not_determined_by_screen_alone")
    info = read_session(session)
    check("metadata reflects human verdict",
          info["metadata"]["verdict"] == "screen_confirmed"
          and info["metadata"]["verdict_source"] == "human")
    rec.close()

source_text = (Path(__file__).resolve().parent.parent
               / "core" / "evidence_capture.py").read_text(encoding="utf-8")
for banned in ("import cv2", "import numpy", "from PIL", "import PIL",
               "pytesseract", "easyocr"):
    check(f"no image-analysis import: {banned}", banned not in source_text)

print("== 8. stop / delete / list ==")
with tempfile.TemporaryDirectory() as tmp:
    clock = FakeClock()
    rec = make_recorder(Path(tmp) / "capture", clock, interval_sec=1.0)
    session = rec.start_battle("1001", {})
    rec.accept_frame(JPEG_A, clock())
    rec.stop()  # immediate finalize, no post-roll wait
    check("stop finalizes", (session / "metadata.json").exists())
    check("listed", rec.list_sessions() == [session])
    check("delete works", delete_session(session) and not session.exists())
    check("list empty after delete", rec.list_sessions() == [])
    rec.close()

print("== 9. latest.jpg source poll (feeder building block) ==")
with tempfile.TemporaryDirectory() as tmp:
    from core.evidence_capture import _LatestJpgSource
    path = Path(tmp) / "latest.jpg"
    path.write_bytes(JPEG_A)
    source = _LatestJpgSource(path)
    item = source.poll()
    check("first poll returns frame", item is not None and item[0] == JPEG_A)
    check("second poll no change", source.poll() is None)
    time.sleep(0.02)
    path.write_bytes(JPEG_B)
    item = source.poll()
    check("updated frame returned", item is not None and item[0] == JPEG_B)

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
    sys.exit(1)
print("ALL FIRST CHALLENGE EVIDENCE CAPTURE TESTS PASSED")

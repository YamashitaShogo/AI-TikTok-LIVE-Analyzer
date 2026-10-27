"""Phase A tests: participant identity, score_known unification, display.

Run from the project root:
    LOCALAPPDATA=<tempdir> python tests/battle_phase_a_test.py

Uses synthetic TikTokLive events; no network, no real stream.
The monitor's payload sink is replaced with a capture list.
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if os.environ.get("PHASE_A_LIB"):
    sys.path.insert(0, os.environ["PHASE_A_LIB"])

os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp(prefix="lm_phase_a_"))

from core.score_known import is_known, known_score, score_state, score_text
from core.low_score_policy import exclusion_reason

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  ok: {name}")
    else:
        print(f"  FAIL: {name} {detail}")
        FAILURES.append(name)


print("== score_known helper ==")
check("True + 0 is a real zero", known_score({"score": 0, "score_known": True}) == 0)
check("True + value", known_score({"score": 1234, "score_known": True}) == 1234)
check("False is not 0", known_score({"score": 0, "score_known": False}) is None)
check("missing flag is unstated", score_state({"score": 500}) == "unstated")
check("missing flag is not known", known_score({"score": 500}) is None)
check("text False", score_text({"score": 0, "score_known": False}) == "未取得")
check("text missing", score_text({"score": 500}) == "不明")
check("text zero", score_text({"score": 0, "score_known": True}) == "0")

print("== low_score_policy uses the same rule ==")
base = {
    "active": False, "mode": "individual",
    "participants": [
        {"anchor_id": "1", "score": 50, "score_known": True},
        {"anchor_id": "2", "score": 80, "score_known": True},
    ],
}
check("all known <=100 excluded", exclusion_reason(base) == "final_all_at_most_100")
legacy = {
    "active": False, "mode": "individual",
    "participants": [
        {"anchor_id": "1", "score": 50},
        {"anchor_id": "2", "score": 80},
    ],
}
check("legacy unstated never excluded by score", exclusion_reason(legacy) is None)

# ---------------------------------------------------------------- monitor
from core import battle_monitor

CAPTURE_DIR = battle_monitor.CAPTURE_DIR
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

payloads = []
_orig_write = battle_monitor.BattleMonitor._write_payload
battle_monitor.BattleMonitor._write_payload = staticmethod(
    lambda payload: payloads.append(payload)
)


class FakeArmy:
    def __init__(self, anchor_id, hostscore):
        self.anchor_id_str = anchor_id
        self.hostscore = hostscore


class FakeUser:
    def __init__(self, user_id, score):
        self.user_id = int(user_id)
        self.user_id_str = user_id
        self.score = score


class FakeTeam:
    def __init__(self, team_id, total, users):
        self.team_id = int(team_id)
        self.team_total_score = total
        self.team_user = users


class FakeEvent:
    def __init__(self, battle_id, update_time, armies=None, teams=None,
                 raw_armies=None, raw_teams=None, start_ms=0, duration=0):
        self.battle_id = battle_id
        self.update_battle_score_time = update_time
        self.armies = armies or {}
        self.team_armies = teams
        self._raw = {
            "battleSettings": {"startTimeMs": start_ms, "duration": duration},
            "armies": raw_armies or {},
            "teamArmies": raw_teams or [],
        }

    def to_dict(self):
        return self._raw


def make_monitor():
    monitor = battle_monitor.BattleMonitor.__new__(battle_monitor.BattleMonitor)
    monitor._lock = threading.RLock()
    monitor._generation = 1
    monitor._battle_id = None
    monitor._last_update_time = 0
    monitor._battle_timing = (0, 0)
    monitor._battle_gameplay_option = ""
    monitor._finished_battle_ids = set()
    monitor._timeout_battle_ids = set()
    monitor._collab_seen = False
    monitor._collab_state_known = False
    return monitor


now_ms = int(time.time() * 1000)

print("== 1v1: order changes must not move scores ==")
monitor = make_monitor()
A, B = "900000000000000001", "100000000000000002"  # string sort puts B first
monitor._handle_battle(
    FakeEvent(111, 1000,
              armies={B: FakeArmy(B, 200), A: FakeArmy(A, 100)},
              raw_armies={B: {"hostscore": 200}, A: {"hostscore": 100}},
              start_ms=now_ms, duration=300),
    "hostroom", 1)
p1 = payloads[-1]
by_id = {p["anchor_id"]: p for p in p1["participants"]}
check("payload keeps processing order (B first)",
      [p["anchor_id"] for p in p1["participants"]] == [B, A])
check("participant_index assigned", [p["participant_index"] for p in p1["participants"]] == [0, 1])
check("seat is None (unknown)", all(p["seat"] is None for p in p1["participants"]))
check("order_source recorded", p1.get("order_source") == "armies_map")
check("scores attached by anchor_id", by_id[A]["score"] == 100 and by_id[B]["score"] == 200)

monitor._handle_battle(
    FakeEvent(111, 2000,
              armies={A: FakeArmy(A, 150), B: FakeArmy(B, 260)},
              raw_armies={A: {"hostscore": 150}, B: {"hostscore": 260}},
              start_ms=now_ms, duration=300),
    "hostroom", 1)
p2 = payloads[-1]
by_id2 = {p["anchor_id"]: p for p in p2["participants"]}
check("after reorder, A still has A's score", by_id2[A]["score"] == 150)
check("after reorder, B still has B's score", by_id2[B]["score"] == 260)

print("== score presence: missing hostscore is not zero ==")
monitor = make_monitor()
monitor._handle_battle(
    FakeEvent(222, 1000,
              armies={A: FakeArmy(A, 0), B: FakeArmy(B, 0)},
              raw_armies={A: {"hostscore": 0}, B: {}},
              start_ms=now_ms, duration=300),
    "hostroom", 1)
p3 = payloads[-1]
by_id3 = {p["anchor_id"]: p for p in p3["participants"]}
check("present 0 stays known", by_id3[A]["score_known"] is True and score_text(by_id3[A]) == "0")
check("absent hostscore is not_fetched", by_id3[B]["score_known"] is False and score_text(by_id3[B]) == "未取得")

print("== 2v2 team: totals, indices, user flags ==")
monitor = make_monitor()
teams = [
    FakeTeam("7001", 500, [FakeUser("101", 300), FakeUser("102", 200)]),
    FakeTeam("7002", 400, [FakeUser("201", 400), FakeUser("202", 0)]),
]
raw_teams = [
    {"teamId": 7001, "teamTotalScore": 500,
     "teamUser": [{"userId": 101, "score": 300}, {"userId": 102, "score": 200}]},
    {"teamId": 7002, "teamTotalScore": 400,
     "teamUser": [{"userId": 201, "score": 400}, {"userId": 202}]},
]
monitor._handle_battle(
    FakeEvent(333, 1000, teams=teams, raw_teams=raw_teams,
              start_ms=now_ms, duration=300),
    "hostroom", 1)
p4 = payloads[-1]
check("team mode", p4["mode"] == "team" and p4.get("order_source") == "team_armies_list")
check("team_index/seat", [(t["team_index"], t["seat"]) for t in p4["teams"]] == [(0, None), (1, None)])
check("team totals known", [known_score(t) for t in p4["teams"]] == [500, 400])
u = {user["user_id"]: user for t in p4["teams"] for user in t["users"]}
check("user score known", u["101"]["score_known"] is True and known_score(u["101"]) == 300)
check("user score missing in raw -> not known", u["202"]["score_known"] is False)

battle_monitor.BattleMonitor._write_payload = _orig_write

# ---------------------------------------------------------------- display
print("== viewer text: host by id, never by position ==")
try:
    from ui.pages.viewer import ViewerPage

    fmt = ViewerPage._format_battle_state
    data = {
        "active": True, "mode": "individual",
        "host_user_id": B, "host_nickname": "ホスト名",
        "participants": [
            {"anchor_id": A, "score": 100, "score_known": True},
            {"anchor_id": B, "score": 200, "score_known": True},
        ],
    }
    text = fmt(object(), data)
    check("host labelled by id match", "ホスト名: 200" in text, text)
    check("opponent labelled with id tail", f"相手（ID…{A[-4:]}）: 100" in text, text)

    unknown = dict(data, host_user_id="")
    text2 = fmt(object(), unknown)
    check("unknown host is stated", "本人不明" in text2, text2)
    check("no one is labelled host", "ホスト名" not in text2, text2)

    unknown_score = {
        "active": True, "mode": "individual", "host_user_id": A,
        "participants": [
            {"anchor_id": A, "score": 0, "score_known": False},
            {"anchor_id": B, "score": 0, "score_known": True},
        ],
    }
    text3 = fmt(object(), unknown_score)
    check("not fetched shows 未取得", "未取得" in text3, text3)
    check("real zero shows 0", ": 0" in text3, text3)

    timeout = {
        "active": False, "reason": "timeout_fallback",
        "finished_at": int(time.time()), "result_display_seconds": 120,
        "mode": "individual", "host_user_id": A,
        "participants": [
            {"anchor_id": A, "score": 10, "score_known": True},
            {"anchor_id": B, "score": 20, "score_known": True},
        ],
    }
    text4 = fmt(object(), timeout)
    check("timeout labelled as estimate", "推定スコア" in text4, text4)
except Exception as exc:
    check(f"viewer import/run in this environment ({type(exc).__name__}: {exc})", False)

print("== battle page text ==")
try:
    from ui.pages.battle import BattlePage

    page = BattlePage.__new__(BattlePage)
    page.battle_data = {
        "mode": "individual", "host_user_id": B,
        "participants": [
            {"anchor_id": A, "score": 0, "score_known": False},
            {"anchor_id": B, "score": 0, "score_known": True},
        ],
    }
    text = page._format_score_text()
    # The Battle page intentionally puts the identified host first.
    check("battle page separates unknown and zero", text == "0  VS  未取得", text)

    page.battle_data = dict(page.battle_data, reason="timeout_fallback")
    text = page._format_score_text()
    check("battle page timeout is estimate", "推定スコア" in text, text)
except Exception as exc:
    check(f"battle page import/run in this environment ({type(exc).__name__}: {exc})", False)

print("== legacy payload compatibility ==")
from core.collection_store import score_text as store_score_text

legacy_payload = {
    "mode": "individual", "host_user_id": A,
    "participants": [
        {"anchor_id": A, "score": 500},
        {"anchor_id": B, "score": 300},
    ],
}
text, identified = store_score_text(legacy_payload)
check("legacy scores render as unstated, not numbers", "不明" in text, text)
check("legacy host still identified", identified is True)

from core.random_battle_dataset import RandomBattleDatasetRecorder

recorder = RandomBattleDatasetRecorder(
    capture_dir=Path(tempfile.mkdtemp(prefix="lm_phase_a_ds_")))
legacy_battle = dict(legacy_payload, active=True, unique_id="hostroom",
                     battle_id=999, update_time=1)
check("recorder accepts legacy payload", recorder.record_battle(legacy_battle) is True)
check("recorder status counts it", recorder.status()["battles"] == 1)

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
    sys.exit(1)
print("ALL PHASE A TESTS PASSED")

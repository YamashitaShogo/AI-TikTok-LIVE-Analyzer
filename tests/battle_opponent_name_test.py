"""Opponent name tests: anchors_info names keyed by user id.

Run from the project root:
    LOCALAPPDATA=<tempdir> python tests/battle_opponent_name_test.py

Uses synthetic TikTokLive events; no network, no real stream, and all
names/handles in this file are fictional test data. The monitor's
payload sink is replaced with a capture list.
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

os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp(prefix="lm_names_"))

from TikTokLiveProto.v3.webcast.im import LinkMicBattleBattleAction

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  ok: {name}")
    else:
        print(f"  FAIL: {name} {detail}")
        FAILURES.append(name)


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
    def __init__(self, anchor_id, hostscore, user_armies=None):
        self.anchor_id_str = anchor_id
        self.hostscore = hostscore
        # Supporters of this anchor (NOT the participant). The monitor
        # must never take a participant name from here.
        self.user_armies = user_armies or []


class FakeSupporter:
    def __init__(self, user_id, nickname):
        self.user_id = int(user_id)
        self.user_id_str = user_id
        self.nickname = nickname


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


class FakeBaseUser:
    def __init__(self, user_id, nick_name, display_id):
        self.user_id = int(user_id)
        self.nick_name = nick_name
        self.display_id = display_id


class FakeAnchorsValue:
    def __init__(self, user):
        self.user = user


class FakeAnchorInfo:
    def __init__(self, key, user):
        self.key = int(key)
        self.value = FakeAnchorsValue(user)


def anchor_info(user_id, nickname, handle):
    return FakeAnchorInfo(user_id, FakeBaseUser(user_id, nickname, handle))


class FakeStateEvent:
    def __init__(self, battle_id, action, anchors_info=None):
        self.battle_id = battle_id
        self.action = action
        self.anchors_info = anchors_info or []

    def to_dict(self):
        return {"battleId": self.battle_id}


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
    monitor._anchor_names = {}
    monitor._anchor_names_scope = None
    return monitor


now_ms = int(time.time() * 1000)
HOST = "900000000000000001"
OPP = "100000000000000002"

print("== 1v1: names from anchors_info, keyed by user id ==")
monitor = make_monitor()
monitor._handle_battle_state(
    FakeStateEvent(555, LinkMicBattleBattleAction.OPEN, [
        anchor_info(HOST, "ホスト表示名", "host_handle"),
        anchor_info(OPP, "相手の表示名", "opp_handle"),
    ]), "hostroom", 1)
monitor._handle_battle(
    FakeEvent(555, 1000,
              armies={OPP: FakeArmy(OPP, 200), HOST: FakeArmy(HOST, 100)},
              raw_armies={OPP: {"hostscore": 200}, HOST: {"hostscore": 100}},
              start_ms=now_ms, duration=300),
    "hostroom", 1)
p = payloads[-1]
by_id = {x["anchor_id"]: x for x in p["participants"]}
check("opponent nickname attached", by_id[OPP].get("nickname") == "相手の表示名", str(by_id[OPP]))
check("opponent unique_id attached", by_id[OPP].get("unique_id") == "opp_handle")
check("name_source recorded", by_id[OPP].get("name_source") == "anchors_info")
check("host entry also keyed correctly", by_id[HOST].get("nickname") == "ホスト表示名")
check("scores unchanged by names", by_id[HOST]["score"] == 100 and by_id[OPP]["score"] == 200)
check("score_known unchanged", by_id[OPP]["score_known"] is True)

print("== event order: armies first, state later ==")
monitor = make_monitor()
monitor._handle_battle(
    FakeEvent(556, 1000,
              armies={HOST: FakeArmy(HOST, 10), OPP: FakeArmy(OPP, 20)},
              raw_armies={HOST: {"hostscore": 10}, OPP: {"hostscore": 20}},
              start_ms=now_ms, duration=300),
    "hostroom", 1)
early = {x["anchor_id"]: x for x in payloads[-1]["participants"]}
check("no names before state event", "nickname" not in early[OPP])
monitor._handle_battle_state(
    FakeStateEvent(556, LinkMicBattleBattleAction.OPEN, [
        anchor_info(OPP, "後から届いた名前", "late_handle"),
    ]), "hostroom", 1)
monitor._handle_battle(
    FakeEvent(556, 2000,
              armies={OPP: FakeArmy(OPP, 25), HOST: FakeArmy(HOST, 15)},
              raw_armies={OPP: {"hostscore": 25}, HOST: {"hostscore": 15}},
              start_ms=now_ms, duration=300),
    "hostroom", 1)
later = {x["anchor_id"]: x for x in payloads[-1]["participants"]}
check("names appear once known, still keyed right",
      later[OPP].get("nickname") == "後から届いた名前" and later[OPP]["score"] == 25)
check("unknown anchor stays unnamed", "nickname" not in later[HOST])

print("== 3-player: everyone mapped by id ==")
monitor = make_monitor()
P3 = "100000000000000003"
monitor._handle_battle_state(
    FakeStateEvent(557, LinkMicBattleBattleAction.OPEN, [
        anchor_info(P3, "三人目", "third_handle"),
        anchor_info(HOST, "ホスト表示名", "host_handle"),
        anchor_info(OPP, "相手の表示名", "opp_handle"),
    ]), "hostroom", 1)
monitor._handle_battle(
    FakeEvent(557, 1000,
              armies={OPP: FakeArmy(OPP, 30), P3: FakeArmy(P3, 10), HOST: FakeArmy(HOST, 20)},
              raw_armies={OPP: {"hostscore": 30}, P3: {"hostscore": 10}, HOST: {"hostscore": 20}},
              start_ms=now_ms, duration=300),
    "hostroom", 1)
trio = {x["anchor_id"]: x for x in payloads[-1]["participants"]}
check("3-player names", trio[HOST]["nickname"] == "ホスト表示名"
      and trio[OPP]["nickname"] == "相手の表示名" and trio[P3]["nickname"] == "三人目")
check("3-player scores", trio[HOST]["score"] == 20 and trio[OPP]["score"] == 30 and trio[P3]["score"] == 10)

print("== 2v2 team: names on team users ==")
monitor = make_monitor()
monitor._handle_battle_state(
    FakeStateEvent(558, LinkMicBattleBattleAction.OPEN, [
        anchor_info("101", "味方A", "a_handle"),
        anchor_info("102", "味方B", "b_handle"),
        anchor_info("201", "敵C", "c_handle"),
        anchor_info("202", "敵D", "d_handle"),
    ]), "hostroom", 1)
teams = [
    FakeTeam("7001", 500, [FakeUser("101", 300), FakeUser("102", 200)]),
    FakeTeam("7002", 400, [FakeUser("201", 400), FakeUser("202", 0)]),
]
raw_teams = [
    {"teamId": 7001, "teamTotalScore": 500,
     "teamUser": [{"userId": 101, "score": 300}, {"userId": 102, "score": 200}]},
    {"teamId": 7002, "teamTotalScore": 400,
     "teamUser": [{"userId": 201, "score": 400}, {"userId": 202, "score": 0}]},
]
monitor._handle_battle(
    FakeEvent(558, 1000, teams=teams, raw_teams=raw_teams,
              start_ms=now_ms, duration=300),
    "hostroom", 1)
users = {u["user_id"]: u for t in payloads[-1]["teams"] for u in t["users"]}
check("2v2 names", users["101"]["nickname"] == "味方A" and users["102"]["nickname"] == "味方B"
      and users["201"]["nickname"] == "敵C" and users["202"]["nickname"] == "敵D")
check("2v2 user scores unchanged", users["101"]["score"] == 300 and users["202"]["score"] == 0)

print("== special team format: uneven teams (2 vs 3, team-format 1v1) ==")
monitor = make_monitor()
monitor._handle_battle_state(
    FakeStateEvent(559, LinkMicBattleBattleAction.OPEN, [
        anchor_info("101", "味方A", "a_handle"), anchor_info("102", "味方B", "b_handle"),
        anchor_info("201", "敵C", "c_handle"), anchor_info("202", "敵D", "d_handle"),
        anchor_info("203", "敵E", "e_handle"),
    ]), "hostroom", 1)
teams = [
    FakeTeam("7001", 500, [FakeUser("101", 300), FakeUser("102", 200)]),
    FakeTeam("7002", 900, [FakeUser("201", 400), FakeUser("202", 300), FakeUser("203", 200)]),
]
raw_teams = [
    {"teamId": 7001, "teamTotalScore": 500,
     "teamUser": [{"userId": 101, "score": 300}, {"userId": 102, "score": 200}]},
    {"teamId": 7002, "teamTotalScore": 900,
     "teamUser": [{"userId": 201, "score": 400}, {"userId": 202, "score": 300}, {"userId": 203, "score": 200}]},
]
monitor._handle_battle(
    FakeEvent(559, 1000, teams=teams, raw_teams=raw_teams,
              start_ms=now_ms, duration=300),
    "hostroom", 1)
users = {u["user_id"]: u for t in payloads[-1]["teams"] for u in t["users"]}
check("uneven teams: all five named", all(
    users[uid].get("nickname") == name for uid, name in
    {"101": "味方A", "102": "味方B", "201": "敵C", "202": "敵D", "203": "敵E"}.items()))

print("== trap: supporter names in user_armies are never used ==")
monitor = make_monitor()
monitor._handle_battle(
    FakeEvent(560, 1000,
              armies={
                  HOST: FakeArmy(HOST, 100, [FakeSupporter("777", "サポーター甲")]),
                  OPP: FakeArmy(OPP, 200, [FakeSupporter("888", "サポーター乙")]),
              },
              raw_armies={HOST: {"hostscore": 100}, OPP: {"hostscore": 200}},
              start_ms=now_ms, duration=300),
    "hostroom", 1)
trapped = {x["anchor_id"]: x for x in payloads[-1]["participants"]}
check("supporter nickname not used as participant name",
      "nickname" not in trapped[HOST] and "nickname" not in trapped[OPP])

print("== cache separation: battle_id and generation ==")
monitor = make_monitor()
monitor._handle_battle_state(
    FakeStateEvent(561, LinkMicBattleBattleAction.OPEN, [
        anchor_info(OPP, "バトル1の名前", "battle1_handle"),
    ]), "hostroom", 1)
monitor._handle_battle(
    FakeEvent(562, 1000,
              armies={HOST: FakeArmy(HOST, 10), OPP: FakeArmy(OPP, 20)},
              raw_armies={HOST: {"hostscore": 10}, OPP: {"hostscore": 20}},
              start_ms=now_ms, duration=300),
    "hostroom", 1)
other = {x["anchor_id"]: x for x in payloads[-1]["participants"]}
check("names do not leak into another battle", "nickname" not in other[OPP])
monitor._handle_battle_state(
    FakeStateEvent(562, LinkMicBattleBattleAction.OPEN, [
        anchor_info(OPP, "バトル2の名前", "battle2_handle"),
    ]), "hostroom", 1)
monitor._handle_battle(
    FakeEvent(562, 2000,
              armies={HOST: FakeArmy(HOST, 15), OPP: FakeArmy(OPP, 25)},
              raw_armies={HOST: {"hostscore": 15}, OPP: {"hostscore": 25}},
              start_ms=now_ms, duration=300),
    "hostroom", 1)
second = {x["anchor_id"]: x for x in payloads[-1]["participants"]}
check("second battle uses its own names", second[OPP].get("nickname") == "バトル2の名前")

monitor._generation = 2  # new monitoring connection
monitor._handle_battle(
    FakeEvent(562, 3000,
              armies={HOST: FakeArmy(HOST, 15), OPP: FakeArmy(OPP, 25)},
              raw_armies={HOST: {"hostscore": 15}, OPP: {"hostscore": 25}},
              start_ms=now_ms, duration=300),
    "hostroom", 2)
newgen = {x["anchor_id"]: x for x in payloads[-1]["participants"]}
check("names do not leak across generations", "nickname" not in newgen[OPP])

print("== missing / malformed anchors_info never breaks monitoring ==")
monitor = make_monitor()
monitor._handle_battle_state(
    FakeStateEvent(563, LinkMicBattleBattleAction.OPEN, []), "hostroom", 1)
monitor._handle_battle_state(
    FakeStateEvent(563, LinkMicBattleBattleAction.OPEN, [
        FakeAnchorInfo(OPP, None),  # value.user is None
        anchor_info(HOST, "", ""),  # empty name and handle
    ]), "hostroom", 1)
monitor._handle_battle(
    FakeEvent(563, 1000,
              armies={HOST: FakeArmy(HOST, 10), OPP: FakeArmy(OPP, 20)},
              raw_armies={HOST: {"hostscore": 10}, OPP: {"hostscore": 20}},
              start_ms=now_ms, duration=300),
    "hostroom", 1)
plain = {x["anchor_id"]: x for x in payloads[-1]["participants"]}
check("no nickname keys when nothing usable arrived",
      "nickname" not in plain[HOST] and "nickname" not in plain[OPP])
check("scores still flow", plain[HOST]["score"] == 10 and plain[OPP]["score"] == 20)

print("== FINISH: result payload gains names from the finish event ==")
monitor = make_monitor()
monitor._handle_battle(
    FakeEvent(564, 1000,
              armies={HOST: FakeArmy(HOST, 10), OPP: FakeArmy(OPP, 20)},
              raw_armies={HOST: {"hostscore": 10}, OPP: {"hostscore": 20}},
              start_ms=now_ms, duration=300),
    "hostroom", 1)
# Simulate the previous live payload on disk, without names.
import json as _json
tmp_battle_path = Path(tempfile.mkdtemp(prefix="lm_names_bp_")) / "latest_battle.json"
tmp_battle_path.write_text(_json.dumps(payloads[-1]), encoding="utf-8")
_orig_battle_path = battle_monitor.BATTLE_PATH
battle_monitor.BATTLE_PATH = tmp_battle_path
try:
    monitor._handle_battle_state(
        FakeStateEvent(564, LinkMicBattleBattleAction.FINISH, [
            anchor_info(HOST, "ホスト表示名", "host_handle"),
            anchor_info(OPP, "相手の表示名", "opp_handle"),
        ]), "hostroom", 1)
finally:
    battle_monitor.BATTLE_PATH = _orig_battle_path
result = payloads[-1]
check("finish payload is a result", result.get("active") is False and result.get("reason") == "finished")
fin = {x["anchor_id"]: x for x in result["participants"]}
check("finish payload carries names", fin[OPP].get("nickname") == "相手の表示名"
      and fin[HOST].get("nickname") == "ホスト表示名")

battle_monitor.BattleMonitor._write_payload = _orig_write

# ---------------------------------------------------------------- display
print("== viewer text: nickname preferred, ID tail fallback ==")
try:
    from ui.pages.viewer import ViewerPage

    fmt = ViewerPage._format_battle_state
    named = {
        "active": True, "mode": "individual",
        "host_user_id": HOST, "host_nickname": "ホスト表示名",
        "participants": [
            {"anchor_id": OPP, "score": 200, "score_known": True,
             "nickname": "相手の表示名", "unique_id": "opp_handle"},
            {"anchor_id": HOST, "score": 100, "score_known": True},
        ],
    }
    text = fmt(object(), named)
    check("viewer shows nickname and handle", "相手の表示名（@opp_handle）: 200" in text, text)
    check("viewer host unchanged", "ホスト表示名: 100" in text, text)

    unnamed = {
        "active": True, "mode": "individual",
        "host_user_id": HOST, "host_nickname": "ホスト表示名",
        "participants": [
            {"anchor_id": OPP, "score": 200, "score_known": True},
            {"anchor_id": HOST, "score": 100, "score_known": True},
        ],
    }
    text2 = fmt(object(), unnamed)
    check("viewer falls back to ID tail", f"相手（ID…{OPP[-4:]}）: 200" in text2, text2)

    team_named = {
        "active": True, "mode": "team", "host_user_id": "101",
        "host_nickname": "ホスト表示名",
        "teams": [
            {"team_id": "7001", "score": 500, "score_known": True,
             "users": [{"user_id": "101", "score": 300, "nickname": "味方A"},
                        {"user_id": "102", "score": 200, "nickname": "味方B"}]},
            {"team_id": "7002", "score": 400, "score_known": True,
             "users": [{"user_id": "201", "score": 400, "nickname": "敵C"},
                        {"user_id": "202", "score": 0, "nickname": "敵D"}]},
        ],
    }
    text3 = fmt(object(), team_named)
    check("viewer team shows member names", "敵C・敵D: 400" in text3, text3)
    check("viewer host team unchanged", "ホスト表示名: 500" in text3, text3)
except Exception as exc:
    check(f"viewer import/run in this environment ({type(exc).__name__}: {exc})", False)

print("== battle page text: names only when present ==")
try:
    from ui.pages.battle import BattlePage

    page = BattlePage.__new__(BattlePage)
    page.battle_data = {
        "mode": "individual", "host_user_id": HOST,
        "participants": [
            {"anchor_id": OPP, "score": 200, "score_known": True,
             "nickname": "相手の表示名", "unique_id": "opp_handle"},
            {"anchor_id": HOST, "score": 100, "score_known": True},
        ],
    }
    text = page._format_score_text()
    # Unified format: a participant with nickname + unique_id is now
    # shown as nickname（@unique_id） on the battle page too (before
    # this change the battle page showed the nickname only).
    check("battle page shows names with scores",
          "ホスト表示名" not in text and "相手の表示名（@opp_handle）: 200" in text and "100" in text, text)

    page.battle_data = {
        "mode": "individual", "host_user_id": HOST,
        "participants": [
            {"anchor_id": OPP, "score": 0, "score_known": False},
            {"anchor_id": HOST, "score": 0, "score_known": True},
        ],
    }
    text = page._format_score_text()
    check("battle page without names matches Phase A output", text == "0  VS  未取得", text)
except Exception as exc:
    check(f"battle page import/run in this environment ({type(exc).__name__}: {exc})", False)

print("== collection history text and graph labels ==")
try:
    from core.collection_store import score_text as store_score_text

    named_payload = {
        "mode": "individual", "host_user_id": HOST,
        "participants": [
            {"anchor_id": OPP, "score": 200, "score_known": True,
             "nickname": "相手の表示名", "unique_id": "opp_handle"},
            {"anchor_id": HOST, "score": 100, "score_known": True,
             "nickname": "ホスト表示名", "unique_id": "host_handle"},
        ],
    }
    text, identified = store_score_text(named_payload)
    # Unified format: entries with nickname + unique_id now show
    # nickname（@unique_id） in history text (nickname only before).
    check("history text shows names",
          "ホスト表示名（@host_handle）: 100" in text and "相手の表示名（@opp_handle）: 200" in text, text)
    check("history host identification unchanged", identified is True)

    unnamed_payload = {
        "mode": "individual", "host_user_id": HOST,
        "participants": [
            {"anchor_id": OPP, "score": 200, "score_known": True},
            {"anchor_id": HOST, "score": 100, "score_known": True},
        ],
    }
    text2, _ = store_score_text(unnamed_payload)
    check("history text without names is unchanged", text2 == "100  VS  200", text2)

    team_payload = {
        "mode": "team", "host_user_id": "101",
        "teams": [
            {"team_id": "7001", "score": 500, "score_known": True,
             "users": [{"user_id": "101", "score": 300, "score_known": True, "nickname": "味方A"},
                        {"user_id": "102", "score": 200, "score_known": True, "nickname": "味方B"}]},
            {"team_id": "7002", "score": 400, "score_known": True,
             "users": [{"user_id": "201", "score": 400, "score_known": True, "nickname": "敵C"},
                        {"user_id": "202", "score": 0, "score_known": True, "nickname": "敵D"}]},
        ],
    }
    text3, _ = store_score_text(team_payload)
    check("history team text shows member names", "敵C・敵D: 400" in text3, text3)

    from core.score_history import resolve_labels, scores as history_scores

    named_scores = history_scores(named_payload)
    check("graph series keys are stable ids",
          named_scores == {"自枠": 100, f"相手 {OPP}": 200}, str(named_scores))
    # Unified format: the graph label now includes the handle when the
    # payload recorded one (nickname only before this change).
    check("graph labels resolve nicknames",
          resolve_labels([named_payload]).get(f"相手 {OPP}") == "相手の表示名（@opp_handle）")
    unnamed_scores = history_scores(unnamed_payload)
    check("graph keys without names are unchanged",
          unnamed_scores == {"自枠": 100, f"相手 {OPP}": 200}, str(unnamed_scores))
    check("no labels without names", resolve_labels([unnamed_payload]) == {})

    team_scores = history_scores(team_payload)
    check("2v2 series keys stay team based",
          team_scores == {"チーム 7001": 500, "自枠（個人）": 300, "チーム 7002": 400},
          str(team_scores))
    team_labels = resolve_labels([team_payload])
    check("2v2 labels use member names",
          team_labels.get("チーム 7001") == "味方A・味方B"
          and team_labels.get("チーム 7002") == "敵C・敵D", str(team_labels))
    unnamed_team = {"mode": "team", "host_user_id": "101",
                    "teams": [{"team_id": "7001", "score": 500, "score_known": True,
                               "users": [{"user_id": "101", "score": 500, "score_known": True}]}]}
    check("solo host team is the host series, no label",
          history_scores(unnamed_team) == {"自枠": 500}
          and resolve_labels([unnamed_team]) == {})
    unnamed_multi = {"mode": "team", "host_user_id": "101",
                     "teams": [{"team_id": "7001", "score": 500, "score_known": True,
                                "users": [{"user_id": "101", "score": 300, "score_known": True},
                                           {"user_id": "102", "score": 200, "score_known": True}]}]}
    check("unnamed multi team keeps team id key and no label",
          history_scores(unnamed_multi) == {"チーム 7001": 500, "自枠（個人）": 300}
          and resolve_labels([unnamed_multi]) == {})

    # The reported problem: a 3-player battle recorded in team format
    # (one person per team). If series were keyed by display label, the
    # mid-battle arrival of names would split every participant into
    # two series (team id first, nickname later) -- 7 series for 3
    # people. Keys must stay the 3 stable identities throughout.
    def solo_team_payload(named):
        def team(tid, uid, score, nickname=None):
            user = {"user_id": uid, "score": score, "score_known": True}
            if named and nickname:
                user["nickname"] = nickname
            return {"team_id": tid, "score": score, "score_known": True,
                    "users": [user]}
        return {"mode": "team", "host_user_id": "101", "teams": [
            team("7001", "101", 100), team("7002", "201", 200, "相手1"),
            team("7003", "301", 300, "相手2")]}

    early, late = solo_team_payload(False), solo_team_payload(True)
    union = set()
    for payload in (early, early, late):
        union |= set(history_scores(payload))
    check("3-player solo-team battle stays 3 series",
          union == {"自枠", "相手 201", "相手 301"}, str(union))
    labels = resolve_labels([early, late])
    check("late-arriving names label the whole battle",
          labels.get("相手 201") == "相手1" and labels.get("相手 301") == "相手2",
          str(labels))
    check("names are kept even if a later payload lacks them",
          resolve_labels([late, early]).get("相手 201") == "相手1")

    mixed = {"mode": "individual", "host_user_id": "101", "participants": [
        {"anchor_id": "101", "score": 100, "score_known": True},
        {"anchor_id": "201", "score": 200, "score_known": True},
        {"anchor_id": "301", "score": 300, "score_known": True}]}
    union2 = set(history_scores(mixed)) | union
    check("mixed recording modes stay 3 series",
          union2 == {"自枠", "相手 201", "相手 301"}, str(union2))
except Exception as exc:
    check(f"history/graph in this environment ({type(exc).__name__}: {exc})", False)

try:
    from core.fixed_score_graph import resolve_labels as fixed_resolve
    from core.fixed_score_graph import scores as fixed_scores

    check("fixed graph series keys are stable ids",
          fixed_scores(named_payload) == {"自枠": 100, f"相手 {OPP}": 200})
    check("fixed graph labels resolve nicknames",
          fixed_resolve([team_payload]).get("チーム 7002") == "敵C・敵D")
    fixed_union = set()
    for payload in (early, late):
        fixed_union |= set(fixed_scores(payload))
    check("fixed graph solo-team battle stays 3 series",
          fixed_union == {"自枠", "相手 201", "相手 301"}, str(fixed_union))
except Exception as exc:
    print(f"  skip: fixed_score_graph import in this environment ({type(exc).__name__}: {exc})")

print("== unified label format: nickname（@unique_id） everywhere ==")
try:
    from core.participant_label import member_labels, participant_label

    check("label: nickname + unique_id",
          participant_label({"nickname": "名前", "unique_id": "handle"}) == "名前（@handle）")
    check("label: nickname only",
          participant_label({"nickname": "名前"}) == "名前")
    check("label: unique_id only",
          participant_label({"unique_id": "handle"}) == "@handle")
    check("label: neither field",
          participant_label({}) == "" and participant_label({}, "FB") == "FB")
    check("label: '@'-prefixed handle never doubles",
          participant_label({"nickname": "名前", "unique_id": "@handle"}) == "名前（@handle）"
          and participant_label({"unique_id": "@handle"}) == "@handle")
    check("label: empty strings count as absent",
          participant_label({"nickname": "", "unique_id": ""}) == "")
    check("label: None counts as absent",
          participant_label({"nickname": None, "unique_id": None}) == "")
    check("label: whitespace counts as absent",
          participant_label({"nickname": "   ", "unique_id": "  "}) == "")
    check("label: malformed entries never raise",
          participant_label(None, "FB") == "FB"
          and participant_label("not-a-dict", "FB") == "FB")
    check("member_labels: per-member tiers, unnamed omitted",
          member_labels([{"nickname": "A", "unique_id": "a"}, {},
                         {"unique_id": "b"}, {"nickname": "C"}])
          == ["A（@a）", "@b", "C"])

    from core.score_history import resolve_labels as hist_resolve
    from core.score_history import scores as hist_scores
    from core.fixed_score_graph import resolve_labels as fixed_resolve2
    from core.collection_store import score_text as store_text2

    handle_only = {
        "mode": "individual", "host_user_id": HOST,
        "participants": [
            {"anchor_id": OPP, "score": 200, "score_known": True,
             "unique_id": "opp_handle"},
            {"anchor_id": HOST, "score": 100, "score_known": True},
        ],
    }
    check("graph label: unique_id only becomes @handle",
          hist_resolve([handle_only]).get(f"相手 {OPP}") == "@opp_handle"
          and fixed_resolve2([handle_only]).get(f"相手 {OPP}") == "@opp_handle")
    check("graph keys unchanged for handle-only payload",
          hist_scores(handle_only) == {"自枠": 100, f"相手 {OPP}": 200})

    text, _ = store_text2(handle_only)
    check("history text: unique_id only becomes @handle",
          "@opp_handle: 200" in text, text)

    team_handles = {
        "mode": "team", "host_user_id": "101",
        "teams": [
            {"team_id": "7001", "score": 500, "score_known": True,
             "users": [{"user_id": "101", "score": 300, "score_known": True, "nickname": "味方A", "unique_id": "a_handle"},
                        {"user_id": "102", "score": 200, "score_known": True, "nickname": "味方B", "unique_id": "b_handle"}]},
            {"team_id": "7002", "score": 400, "score_known": True,
             "users": [{"user_id": "201", "score": 400, "score_known": True, "nickname": "敵C", "unique_id": "c_handle"},
                        {"user_id": "202", "score": 0, "score_known": True, "nickname": "敵D", "unique_id": "d_handle"}]},
        ],
    }
    text, _ = store_text2(team_handles)
    check("history team text: members formatted with handles",
          "敵C（@c_handle）・敵D（@d_handle）: 400" in text, text)
    check("graph team labels: members formatted with handles",
          hist_resolve([team_handles]).get("チーム 7002") == "敵C（@c_handle）・敵D（@d_handle）")

    legacy = {
        "mode": "individual", "host_user_id": HOST,
        "participants": [
            {"anchor_id": OPP, "score": 200, "score_known": True,
             "nickname": "相手の表示名"},
            {"anchor_id": HOST, "score": 100, "score_known": True},
        ],
    }
    check("legacy payload without unique_id keeps nickname-only label",
          hist_resolve([legacy]).get(f"相手 {OPP}") == "相手の表示名")
    text, _ = store_text2(legacy)
    check("legacy history text keeps nickname-only prefix",
          "相手の表示名: 200" in text and "（@" not in text, text)

    twins = {
        "mode": "individual", "host_user_id": HOST,
        "participants": [
            {"anchor_id": OPP, "score": 200, "score_known": True,
             "nickname": "同名", "unique_id": "twin_a"},
            {"anchor_id": P3, "score": 300, "score_known": True,
             "nickname": "同名", "unique_id": "twin_b"},
            {"anchor_id": HOST, "score": 100, "score_known": True},
        ],
    }
    twin_scores = hist_scores(twins)
    twin_labels = hist_resolve([twins])
    check("same nickname: two distinct opponent series",
          twin_scores == {"自枠": 100, f"相手 {OPP}": 200, f"相手 {P3}": 300},
          str(twin_scores))
    check("same nickname: labels stay distinct via handles",
          twin_labels.get(f"相手 {OPP}") == "同名（@twin_a）"
          and twin_labels.get(f"相手 {P3}") == "同名（@twin_b）", str(twin_labels))
    twins_bare = {
        "mode": "individual", "host_user_id": HOST,
        "participants": [
            {"anchor_id": OPP, "score": 200, "score_known": True, "nickname": "同名"},
            {"anchor_id": P3, "score": 300, "score_known": True, "nickname": "同名"},
            {"anchor_id": HOST, "score": 100, "score_known": True},
        ],
    }
    check("same nickname without handles: still two series",
          hist_scores(twins_bare) == {"自枠": 100, f"相手 {OPP}": 200, f"相手 {P3}": 300})
except Exception as exc:
    check(f"unified labels in this environment ({type(exc).__name__}: {exc})", False)

print("== viewer / battle page: handle-only and '@'-prefixed cases ==")
try:
    from ui.pages.viewer import ViewerPage

    fmt = ViewerPage._format_battle_state
    handle_only_view = {
        "active": True, "mode": "individual",
        "host_user_id": HOST, "host_nickname": "ホスト表示名",
        "participants": [
            {"anchor_id": OPP, "score": 200, "score_known": True,
             "unique_id": "opp_handle"},
            {"anchor_id": HOST, "score": 100, "score_known": True},
        ],
    }
    text = fmt(object(), handle_only_view)
    check("viewer shows @handle when nickname is missing",
          "@opp_handle: 200" in text, text)

    prefixed = {
        "active": True, "mode": "individual",
        "host_user_id": HOST, "host_nickname": "ホスト表示名",
        "participants": [
            {"anchor_id": OPP, "score": 200, "score_known": True,
             "nickname": "相手の表示名", "unique_id": "@opp_handle"},
            {"anchor_id": HOST, "score": 100, "score_known": True},
        ],
    }
    text = fmt(object(), prefixed)
    check("viewer never renders @@ for stored '@' handles",
          "相手の表示名（@opp_handle）: 200" in text and "@@" not in text, text)

    team_handles_view = {
        "active": True, "mode": "team", "host_user_id": "101",
        "host_nickname": "ホスト表示名",
        "teams": [
            {"team_id": "7001", "score": 500, "score_known": True,
             "users": [{"user_id": "101", "score": 300, "nickname": "味方A", "unique_id": "a_handle"},
                        {"user_id": "102", "score": 200, "nickname": "味方B", "unique_id": "b_handle"}]},
            {"team_id": "7002", "score": 400, "score_known": True,
             "users": [{"user_id": "201", "score": 400, "nickname": "敵C", "unique_id": "c_handle"},
                        {"user_id": "202", "score": 0, "nickname": "敵D", "unique_id": "d_handle"}]},
        ],
    }
    text = fmt(object(), team_handles_view)
    check("viewer team members formatted with handles",
          "敵C（@c_handle）・敵D（@d_handle）: 400" in text, text)
except Exception as exc:
    check(f"viewer unified labels in this environment ({type(exc).__name__}: {exc})", False)

try:
    from ui.pages.battle import BattlePage

    page = BattlePage.__new__(BattlePage)
    page.battle_data = {
        "mode": "individual", "host_user_id": HOST,
        "participants": [
            {"anchor_id": OPP, "score": 200, "score_known": True,
             "unique_id": "opp_handle"},
            {"anchor_id": HOST, "score": 100, "score_known": True},
        ],
    }
    text = page._format_score_text()
    check("battle page shows @handle when nickname is missing",
          "@opp_handle: 200" in text, text)

    page.battle_data = {
        "mode": "team", "host_user_id": "101",
        "teams": [
            {"team_id": "7001", "score": 500, "score_known": True,
             "users": [{"user_id": "101", "score": 300, "score_known": True, "nickname": "味方A", "unique_id": "a_handle"},
                        {"user_id": "102", "score": 200, "score_known": True, "nickname": "味方B", "unique_id": "b_handle"}]},
            {"team_id": "7002", "score": 400, "score_known": True,
             "users": [{"user_id": "201", "score": 400, "score_known": True, "nickname": "敵C", "unique_id": "c_handle"},
                        {"user_id": "202", "score": 0, "score_known": True, "nickname": "敵D", "unique_id": "d_handle"}]},
        ],
    }
    text = page._format_score_text()
    check("battle page team members formatted with handles",
          "敵C（@c_handle）・敵D（@d_handle）: 400" in text, text)
except Exception as exc:
    check(f"battle page unified labels in this environment ({type(exc).__name__}: {exc})", False)

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
    sys.exit(1)
print("ALL OPPONENT NAME TESTS PASSED")

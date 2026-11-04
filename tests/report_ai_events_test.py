"""AI v3 event evidence (PR #12): speed-challenge / item events in
the AI payload — summarised and anonymised in Python, correlated
with observed score samples under strict rules, and kept apart
across battles and sessions.

Synthetic events only; no external API is called (a fake client
captures the prompt). Event judgement reuses the existing
core.battle_timeline normaliser — this test feeds it payloads in
the recorded shapes and checks what report_ai makes of them.
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import types
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='pulse_ai_events_')
os.environ['LOCALAPPDATA'] = _TMP  # must precede core imports (BASE)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pyaudiowpatch  # noqa: F401
except ImportError:
    sys.modules['pyaudiowpatch'] = types.ModuleType('pyaudiowpatch')

from core import battle_timeline, report_ai
from core.observation_sessions import format_jst

passed = failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f'PASS {name}')
    else:
        failed += 1
        print(f'FAIL {name}')


T0 = 1_762_000_000.0
DB = Path(_TMP) / 'battles.sqlite3'
_db = sqlite3.connect(DB)
_db.executescript("""
CREATE TABLE snapshots (unique_id TEXT NOT NULL, battle_id INTEGER NOT NULL,
    received_at REAL NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
    UNIQUE(unique_id, battle_id, fingerprint));
""")
_db.commit()
_db.close()


def snap(uid, bid, at, score):
    payload = {"mode": "individual", "host_user_id": "111",
               "host_nickname": "Alice",
               "participants": [
                   {"anchor_id": "111", "score": score, "score_known": True,
                    "nickname": "Alice", "unique_id": "alice"},
                   {"anchor_id": "222", "score": 0, "score_known": False,
                    "nickname": "Bob", "unique_id": "bob"}]}
    db = sqlite3.connect(DB)
    db.execute("INSERT INTO snapshots VALUES (?,?,?,?,?)",
               (uid, bid, at, f'{uid}-{bid}-{at}', json.dumps(payload)))
    db.commit()
    db.close()


def challenge_payloads(reward_start, reward_multiple=2, reward_duration=60,
                       mission_start=None, mission_duration=30):
    config = {
        'targetConfig': {
            'targetStartTimestamp': int((mission_start or T0 + 100) * 1000),
            'duration': mission_duration,
            'promptKey': 'pm_mt_match_sp_team_gifter_target_host',
            'defaultPattern': 'テストミッション',
        },
        'rewardConfig': {'rewardMultiple': reward_multiple,
                         'rewardStartTimestamp': int(reward_start * 1000),
                         'duration': reward_duration},
    }
    start = {'start': {'config': config}, 'common': {'msgId': 'm-start'}}
    settle = {'taskSettle': {'result': 'SUCCEED',
                             'rewardStartTimestamp': int(reward_start * 1000)},
              'common': {'msgId': 'm-settle'}}
    return start, settle


# --- Battle A (alice/101): dense samples, mission+reward+items -------------
for i in range(31):
    at = T0 + i * 10
    score = 1000 if at <= T0 + 200 else 1000 + int((at - (T0 + 200)) // 10) * 30
    if at > T0 + 260:
        score = 1180
    snap('alice', 101, at, score)
start, settle = challenge_payloads(T0 + 200)
battle_timeline.record(DB, 'alice', 101, 'challenge', start, T0 + 95)
battle_timeline.record(DB, 'alice', 101, 'challenge', settle, T0 + 150)
battle_timeline.record(DB, 'alice', 101, 'item', {
    'useGlove': {'cardInfo': {'effectTimeSec': T0 + 280, 'effectLastDuration': 30,
                              'sendTimeSec': T0 + 279, 'toAnchorIdStr': '222'},
                 'displayContent': {'defaultPattern': 'Alice sent 1 Boosting Glove'}},
    'common': {'msgId': 'i-use'}}, T0 + 280)
battle_timeline.record(DB, 'alice', 101, 'item', {
    'obtainGlove': {'cardInfo': {'effectTimeSec': T0 + 100}},
    'common': {'msgId': 'i-obtain'}}, T0 + 100)
battle_timeline.record(DB, 'alice', 101, 'item', {
    'useTimer': {'cardInfo': {'sendTimeSec': T0 + 50, 'toAnchorIdStr': '111'},
                 'displayContent': {'defaultPattern': 'Alice sent 1 Timer'}},
    'common': {'msgId': 'i-timer'}}, T0 + 50)

# --- Battle B (alice/102): reward window inside a sample hole --------------
snap('alice', 102, T0, 500)
snap('alice', 102, T0 + 10, 500)
snap('alice', 102, T0 + 120, 900)
start_b, settle_b = challenge_payloads(T0 + 200, reward_duration=60,
                                       mission_start=T0 + 20, mission_duration=30)
# Move B's reward into the hole: rebuild with reward at T0+40..T0+100.
start_b, settle_b = challenge_payloads(T0 + 40, reward_duration=60,
                                       mission_start=T0 + 20, mission_duration=30)
battle_timeline.record(DB, 'alice', 102, 'challenge', start_b, T0 + 15)
battle_timeline.record(DB, 'alice', 102, 'challenge', settle_b, T0 + 35)

# --- Battle C (bob/999): another streamer entirely, never in the report ----
snap('bob', 999, T0, 10)
start_c, _ = challenge_payloads(T0 + 200)
battle_timeline.record(DB, 'bob', 999, 'challenge', start_c, T0 + 95)


def battle_row(bid, finished, first, last, samples=31):
    return {'unique_id': 'alice', 'battle_id': bid, 'nickname': 'Alice',
            'finished_confirmed': finished, 'first_seen': first,
            'last_seen': last, 'score_sample_count': samples,
            'largest_increase': None}


REPORT = {
    'profile': 'capture_fixed',
    'summary': {'window_start': T0, 'window_end': T0 + 3600,
                'window_start_jst': format_jst(T0),
                'window_end_jst': format_jst(T0 + 3600),
                'observed_seconds': 3600, 'monitored_seconds': 3600,
                'disconnected_seconds': 0, 'record_count': 2,
                'unique_battle_count': 2, 'finished_confirmed': 1,
                'unfinished': 1, 'score_known_battles': 1,
                'score_unknown_battles': 0, 'final_score_median': 1180,
                'final_score_max': 1180, 'viewer_median': 40,
                'viewer_peak_max': 120, 'score_sample_total': 34,
                'viewer_sample_total': 34, 'partial_battles': 0,
                'gap_count': 0, 'error_count': 0},
    'per_streamer': [{'unique_id': 'alice', 'nickname': 'Alice',
                      'records': 2, 'finished': 1, 'score_known': 1,
                      'score_median': 1180, 'score_max': 1180,
                      'viewer_median': 40, 'viewer_peak': 120,
                      'partial_records': 0}],
    'battles': [battle_row(101, True, T0, T0 + 300),
                battle_row(102, False, T0, T0 + 120, samples=3)],
    'comparison': None,
    'data_notes': [],
}

evidence, _ = report_ai.build_evidence(REPORT, DB)
events = evidence['events']
check('V1 events are available from the recorded store',
      events['status'] == 'available')
by_type = {}
for b in events['battles']:
    for e in b['events']:
        by_type.setdefault(e['type'], []).append(e)
check('V2 challenge mission is summarised',
      len(by_type.get('challenge_mission', [])) >= 1
      and by_type['challenge_mission'][0]['challenge'] == 'スピードチャレンジ')
reward = by_type.get('challenge_reward', [])
check('V3 reward event present with the confirmed multiple',
      len(reward) >= 1 and reward[0]['multiple_confirmed'] == 2)
during = reward[0]['score_increase_during'] if reward else {}
check('V4 score increase during the reward interval is Python-computed',
      during.get('computable') is True and during.get('increase') == 180)
check('V5 the increase interval matches the reward window samples',
      during.get('from_jst') == format_jst(T0 + 200)
      and during.get('to_jst') == format_jst(T0 + 260))
items = by_type.get('item_use', [])
glove = next((e for e in items if e['item'] == 'グローブ'), None)
check('V6 item use is summarised with its notified name mapped safely',
      glove is not None)
check('V7 item target is a role, opponent here',
      glove is not None and glove['target_role'] == 'opponent')
check('V8 item before-window change is computed from samples',
      glove is not None
      and glove['score_change_before'].get('increase') == 120)
check('V9 the obtain notification never became a use event',
      len(items) == 2)  # glove + timer only
timer = next((e for e in items if e['item'] == 'Timer'), None)
check('V10 an item without an effect end keeps end null (never guessed)',
      timer is not None and timer['end_jst'] is None
      and timer['target_role'] == 'self')
b102 = next((b for b in events['battles'] if not b['battle_finished']), None)
reward_b = next((e for e in (b102 or {}).get('events', [])
                 if e['type'] == 'challenge_reward'), None)
check('V11 a reward window inside a sample hole is NOT computable',
      reward_b is not None
      and reward_b['score_increase_during']['computable'] is False)
check('V12 battles stay separate (A has 5 events, B has 3)',
      sorted(b['event_count'] for b in events['battles']) == [3, 5])
blob = json.dumps(evidence, ensure_ascii=False)
check('V13 no identifiers or raw payload keys are sent',
      all(x not in blob for x in ('alice', 'Alice', 'bob', '101', '102', '999',
                                  'rewardConfig', 'cardInfo', 'toAnchorIdStr',
                                  '222', '111', 'battle_id')))
check('V14 streamer appears only as a code',
      all(b['streamer'] == 'R0001' for b in events['battles']))

# --- availability distinction ------------------------------------------------
missing = report_ai.build_evidence(REPORT, Path(_TMP) / 'nope.sqlite3')[0]
check('V15 a missing DB is unavailable (not "no events")',
      missing['events']['status'] == 'unavailable')
none_db = report_ai.build_evidence(REPORT)[0]
check('V16 no database argument is unavailable too',
      none_db['events']['status'] == 'unavailable')
empty_db_path = Path(_TMP) / 'empty.sqlite3'
sqlite3.connect(empty_db_path).close()
empty = report_ai.build_evidence(REPORT, empty_db_path)[0]
check('V17 a readable DB without events is available with total 0',
      empty['events']['status'] == 'available'
      and empty['events']['total_events'] == 0)

# --- preview == what analyze sends --------------------------------------------
class FakeClient:
    def __init__(self):
        self.prompt = None

    def analyze_image(self, path, prompt):
        self.prompt = prompt
        return '① 要約です。② 良かった点。③ 改善点。④ 次回試すこと。'


client = FakeClient()
payload, _, _ = report_ai.analyze(REPORT, client=client, folder=Path(_TMP) / 'ai',
                                  database=DB)
sent = json.loads(client.prompt.split('観測データJSON:\n', 1)[1])
preview = json.loads(report_ai.evidence_preview(REPORT, DB))
check('V18 the preview events block equals the sent events block',
      sent['events'] == preview['events'] == payload['evidence']['events'])
check('V19 analyze still works when events are unavailable',
      report_ai.analyze(REPORT, client=FakeClient(),
                        folder=Path(_TMP) / 'ai2',
                        database=Path(_TMP) / 'nope.sqlite3')[0]['answer'])


# --- W: window intersection, multi-session, identifier-tainted text --------
def e_score(at):
    if at < T0 + 180:
        return 500
    if at <= T0 + 240:
        return 500 + int((at - (T0 + 180)) // 10) * 10
    return 560


for i in range(61):
    at = T0 - 100 + i * 10
    snap('alice', 105, at, e_score(at))
start_e, settle_e = challenge_payloads(T0 + 180, reward_duration=60,
                                       mission_start=T0 - 50, mission_duration=30)
battle_timeline.record(DB, 'alice', 105, 'challenge', start_e, T0 - 60)
battle_timeline.record(DB, 'alice', 105, 'challenge', settle_e, T0 + 150)
battle_timeline.record(DB, 'alice', 105, 'item', {
    'useGlove': {'cardInfo': {'effectTimeSec': T0 + 450, 'effectLastDuration': 30,
                              'sendTimeSec': T0 + 449, 'toAnchorIdStr': '222'},
                 'displayContent': {'defaultPattern': 'Alice sent 1 Boosting Glove'}},
    'common': {'msgId': 'e-glove'}}, T0 + 450)

for i in range(13):
    snap('alice', 106, T0 + i * 10, 100)
battle_timeline.record(DB, 'alice', 106, 'challenge', {
    'start': {'config': {
        'targetConfig': {'targetStartTimestamp': int((T0 + 10) * 1000),
                         'duration': 30,
                         'promptKey': 'pm_mt_match_sp_team_gifter_target_host',
                         'defaultPattern': 'aliceさんのチャレンジ'},
        'rewardConfig': {}}},
    'common': {'msgId': 'f-start'}}, T0 + 5)
battle_timeline.record(DB, 'alice', 106, 'item', {
    'useSpecial': {'cardInfo': {'sendTimeSec': T0 + 60, 'toAnchorIdStr': '222'},
                   'displayContent': {'defaultPattern': 'Bob sent 1 aliceトークン'}},
    'common': {'msgId': 'f-item'}}, T0 + 60)


def report_for(bid, first, last, win_first, win_last):
    rep = dict(REPORT)
    rep['summary'] = dict(REPORT['summary'],
                          window_start=win_first, window_end=win_last,
                          window_start_jst=format_jst(win_first),
                          window_end_jst=format_jst(win_last))
    rep['battles'] = [battle_row(bid, True, first, last, samples=61)]
    return rep


ev_w1, _ = report_ai.build_evidence(report_for(105, T0 - 100, T0 + 500, T0, T0 + 200), DB)
w1_events = ev_w1['events']['battles'][0]['events'] if ev_w1['events']['battles'] else []
w1_reward = next((e for e in w1_events if e['type'] == 'challenge_reward'), None)
check('W1 window intersection keeps only in-window events',
      ev_w1['events']['total_events'] == 2 and w1_reward is not None)
check('W2 a reward crossing the window end cannot use out-of-window samples',
      w1_reward is not None
      and w1_reward['score_increase_during']['computable'] is False)

ev_w2, _ = report_ai.build_evidence(
    report_for(105, T0 - 100, T0 + 500, T0 + 200, T0 + 600), DB)
w2_events = ev_w2['events']['battles'][0]['events'] if ev_w2['events']['battles'] else []
w2_reward = next((e for e in w2_events if e['type'] == 'challenge_reward'), None)
check('W3 the next session sees its own slice (reward + item, no mission/settle)',
      sorted(e['type'] for e in w2_events) == ['challenge_reward', 'item_use'])
check('W4 the same reward computes from in-window samples only (increase 40)',
      w2_reward is not None
      and w2_reward['score_increase_during'].get('increase') == 40)

ev_f, _ = report_ai.build_evidence(report_for(106, T0, T0 + 120, T0, T0 + 3600), DB)
f_events = ev_f['events']['battles'][0]['events'] if ev_f['events']['battles'] else []
f_mission = next((e for e in f_events if e['type'] == 'challenge_mission'), None)
f_item = next((e for e in f_events if e['type'] == 'item_use'), None)
f_blob = json.dumps(ev_f, ensure_ascii=False)
check('W5 a mission text containing a streamer name is withheld as 未判定',
      f_mission is not None and f_mission['mission'] == '未判定'
      and 'aliceさん' not in f_blob)
check('W6 an item name containing an identifier is withheld as unjudged',
      f_item is not None and f_item['item_name_known'] is False
      and f_item['item'] == 'アイテム（名称未判定）'
      and 'aliceトークン' not in f_blob)

# --- prompt v3 ------------------------------------------------------------------
P = report_ai.PROMPT
check('V20 prompt version is v3', report_ai.PROMPT_VERSION == 'unattended-report-v3.1')
check('V21 v2 coverage rules are retained',
      '記録自体が存在しない時間' in P and 'gap_count=0' in P
      and 'increase_from_jst' in P and '観測方法やデータ取得の改善は④に書かない' in P)
check('V22 event rules: overlap may be described, causation never claimed',
      '時間的重なりを説明できます' in P and '原因だとは断定しないでください' in P)
check('V23 unavailable vs no-record distinction is instructed',
      'unavailable のときはイベントに一切触れないでください' in P
      and '発生しなかったとは言えません' in P)
check('V24 no multiple guessing, no sales conversion for events',
      'multiple_confirmed' in P and '倍率を推測しないでください' in P
      and '売上・ギフト金額に換算しないでください' in P)

# --- manual-only pin --------------------------------------------------------------
page_source = (Path(__file__).resolve().parent.parent
               / 'ui' / 'pages' / 'unattended_report.py').read_text(encoding='utf-8')
check('V25 AI runs only from the button handler',
      page_source.count('ai_analyze(report') == 1
      and 'command=self.run_ai' in page_source)

print(f'\n{passed} passed, {failed} failed')
raise SystemExit(1 if failed else 0)

"""Battle detail events: speed challenge + battle items (PR #12).

Events are written through the real recording path
(core.battle_timeline.record — the same one battle_monitor uses
for every profile, fixed included) and must surface in the
report page's battle detail: on the score chart and in the
event list, with their time bases stated.

E1  mission / settle / reward / item-use events are loaded once
    (duplicate records are deduplicated)
E2  the speed-challenge mission carries its interpreted content
E3  a confirmed reward multiple is shown as ×N
E4  item USE is an event; item OBTAIN is not
E5  the item target resolves to the opponent's display label
E6  the chart draws item (amber) and reward (teal) markers
E7  a battle without events says so explicitly, and another
    battle's events never leak into it
E8  the mission time is the payload's planned start, not a guess

Run: python tests/battle_detail_events_test.py  (GUI: needs a display)
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import types
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='pulse_battle_events_')
os.environ['LOCALAPPDATA'] = _TMP  # must precede core imports (BASE)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pyaudiowpatch  # noqa: F401
except ImportError:
    sys.modules['pyaudiowpatch'] = types.ModuleType('pyaudiowpatch')

import customtkinter as ctk

FAILURES = []


def check(name, condition, detail=''):
    print(('PASS ' if condition else 'FAIL ') + name
          + (f'  [{detail}]' if detail and not condition else ''))
    if not condition:
        FAILURES.append(name)


from core.observation_profile import BASE
from core.observation_sessions import get_runtime
from core.battle_timeline import record as record_timeline

CAP = BASE / 'capture_fixed'
DB_PATH = CAP / 'battle_dataset' / 'battles.sqlite3'
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_db = sqlite3.connect(DB_PATH)
_db.executescript("""
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
""")
NOW = time.time()
START = NOW - 5000
T0 = START + 100  # battle 8001 start


def individual(host_score, opp_score, finished=False):
    parts = [
        {"anchor_id": "1", "score": host_score, "score_known": True,
         "nickname": "mio", "unique_id": "mio__x6"},
        {"anchor_id": "2", "score": opp_score, "score_known": True,
         "nickname": "rival", "unique_id": "rival_x"},
    ]
    return json.dumps({"mode": "individual", "host_user_id": "1",
                       "host_nickname": "mio", "participants": parts,
                       "active": not finished,
                       "start_time_ms": int(T0 * 1000),
                       "duration_seconds": 300})


def add_battle(bid, first, last, status, snaps):
    _db.execute("INSERT INTO battles VALUES (?,?,?,?,?,?)",
                ('mio__x6', bid, first, last, status,
                 individual(500, 250, finished=True)))
    for j, (offset, snap) in enumerate(snaps):
        _db.execute("INSERT INTO snapshots VALUES (?,?,?,?,?)",
                    ('mio__x6', bid, first + offset, f'{bid}fp{j}', snap))


add_battle(8001, T0, T0 + 200, 'finished',
           [(off, individual(100 + off, 50 + off))
            for off in (0, 20, 40, 60, 80, 100)])
add_battle(8002, START + 1000, START + 1200, 'finished',
           [(off, individual(10 + off, 5 + off))
            for off in (0, 20, 40)])
_db.commit()

MISSION = {
    "common": {"msgId": "c1"},
    "start": {"config": {
        "targetConfig": {
            "promptKey": "pm_mt_match_sp_team_gifter_target_host",
            "targetStartTimestamp": int(T0 * 1000), "duration": 60,
            "progressTarget": 3},
        "rewardConfig": {
            "rewardStartTimestamp": int((T0 + 70) * 1000), "duration": 60,
            "rewardMultiple": 2}}}}
SETTLE = {"common": {"msgId": "c2"},
          "taskSettle": {"result": "SUCCEED",
                         "rewardStartTimestamp": int((T0 + 70) * 1000)}}
ITEM_USE = {
    "common": {"msgId": "i1"},
    "useCard": {
        "cardInfo": {"cardNameKey": "boosting_glove",
                     "effectTimeSec": int(T0 + 30),
                     "sendTimeSec": int(T0 + 29),
                     "effectLastDuration": 30, "toAnchorId": "2"},
        "displayContent": {"defaultPattern": "rival sent 1 Boosting Glove"}}}
ITEM_OBTAIN = {
    "common": {"msgId": "i2"},
    "obtainCard": {"cardInfo": {"cardNameKey": "boosting_glove"}}}

db_str = str(DB_PATH)
record_timeline(db_str, 'mio__x6', 8001, 'challenge', MISSION, T0 + 2)
record_timeline(db_str, 'mio__x6', 8001, 'challenge', MISSION, T0 + 2)  # dup
record_timeline(db_str, 'mio__x6', 8001, 'challenge', SETTLE, T0 + 65)
record_timeline(db_str, 'mio__x6', 8001, 'item', ITEM_USE, T0 + 31)
record_timeline(db_str, 'mio__x6', 8001, 'item', ITEM_OBTAIN, T0 + 10)

store = get_runtime(str(CAP)).store
s1 = store.start_session('固定観測', targets=['mio__x6'],
                         profile='capture_fixed', now=START - 100)
store.heartbeat(s1['session_id'], connected=3, now=START - 95)
store.stop_session(s1['session_id'], 'normal', now=START + 3000)

import tkinter.messagebox as messagebox
messagebox.showinfo = lambda *a, **k: None
messagebox.showerror = lambda *a, **k: None
messagebox.askyesno = lambda *a, **k: True

import ui.pages.unattended_report as page_module

root = ctk.CTk()
root.geometry('1500x950')
page = page_module.UnattendedReportPage(root)
page.pack(fill='both', expand=True)


def pump(seconds=0.25):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def wait_until(predicate, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        root.update()
        if predicate():
            return True
        time.sleep(0.03)
    return predicate()


def line_count(canvas, color):
    return sum(1 for i in canvas.find_all()
               if canvas.type(i) == 'line'
               and canvas.itemcget(i, 'fill') == color)


def battle_by_id(bid):
    return next(b for b in page._report['battles'] if b['battle_id'] == bid)


def open_detail(bid):
    page._open_battle(battle_by_id(bid))
    ok = wait_until(lambda: page._detail_data is not None
                    and page._detail_data.get('payloads'))
    pump(0.4)
    return ok


page.show_history_session(s1['session_id'])
check('setup: report lists both battles',
      wait_until(lambda: page._report is not None
                 and len(page._report['battles']) == 2))
page.tabs.set('バトル履歴')
pump(0.3)

check('load: detail data arrives for 8001', open_detail(8001))
events = page._detail_data.get('events') or []
kinds = [(e.get('kind'), e.get('phase')) for e in events]
check('E1 mission/settle/reward/item load exactly once (deduped)',
      len(events) == 4
      and ('challenge', 'mission') in kinds
      and ('challenge', 'settle') in kinds
      and ('challenge', 'reward') in kinds
      and ('item', None) in kinds, str(kinds))
mission = next(e for e in events if e.get('phase') == 'mission')
check('E2 the mission is the speed challenge with its content',
      mission['label'].startswith('スピードチャレンジ')
      and 'ギフト送信者3人' in (mission.get('mission') or ''))
check('E8 the mission time is the payload planned start',
      abs(mission['at'] - T0) < 1 and abs(mission['end'] - (T0 + 60)) < 1)
reward = next(e for e in events if e.get('phase') == 'reward')
check('E3 the reward carries the confirmed multiple',
      reward.get('multiple_raw') == 2 and abs(reward['at'] - (T0 + 70)) < 1)
item = next(e for e in events if e.get('kind') == 'item')
check('E4 the item use is a glove event on its effect time; '
      'the obtain notice produced nothing',
      item['label'] == 'グローブ' and abs(item['at'] - (T0 + 30)) < 1
      and abs((item.get('end') or 0) - (T0 + 60)) < 1
      and item.get('basis') == '効果開始時刻'
      and all(e.get('message_id') != 'i2' for e in events))
list_text = page.bd_events.cget('text')
check('E5 the event list explains times, multiple and target',
      'スピードチャレンジ・ミッション' in list_text
      and '倍率 ×2（通知で確認）' in list_text
      and 'グローブ' in list_text
      and '対象： rival（@rival_x）' in list_text
      and '根拠：' in list_text, list_text[:200])
check('E6 the chart marks items (amber) and rewards (teal)',
      line_count(page.bd_score_chart, '#F59E0B') >= 1
      and line_count(page.bd_score_chart, '#14B8A6') >= 1)
page._close_battle_detail()
pump(0.2)

check('load: detail data arrives for 8002', open_detail(8002))
check('E7 a battle without events says so; nothing leaks across',
      (page._detail_data.get('events') == [])
      and page.bd_events.cget('text') == 'スピチャ・アイテムのイベント記録なし'
      and line_count(page.bd_score_chart, '#F59E0B') == 0)

page.destroy()
pump(0.2)
root.destroy()

print()
if FAILURES:
    print(f'{len(FAILURES)} FAILURES: {FAILURES}')
    sys.exit(1)
print('battle detail events tests passed')

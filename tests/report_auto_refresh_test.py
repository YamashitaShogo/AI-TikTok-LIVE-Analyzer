"""Auto-refresh tests for the streaming report page (PR #12).

The report page re-aggregates what is on screen from the latest DB
and session rows every few seconds, strictly read-only:

A1  Opening the page shows the latest session's aggregation without
    any button press; the display path writes NO report file and
    does NOT mark the session's report as generated.
A2  A battle whose end notification lands in the DB after the page
    opened flips from 終了未確認 (reference score only) to a
    confirmed final score on the next refresh — the @mio__x6 case
    (43,022 reference -> 87,519 confirmed). The user's selected
    battle survives the re-render.
A3  A session with zero battles aggregates cleanly: counts are 0
    records, scores stay 未取得 (None), never 0.
A4  Races: a stale-generation display result is dropped, and no
    second aggregation starts while one is in flight or while a
    manual generate() runs.
A5  Session switching: an auto request follows the running session,
    an explicit (manual) request is sticky, and changing the data
    source resets the display state.
A6  Destroying the page stops all display updating: the generation
    is invalidated, auto refresh is a no-op and the pump exits.

Run: python tests/report_auto_refresh_test.py  (GUI: needs a display)
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import types
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='pulse_report_refresh_')
os.environ['LOCALAPPDATA'] = _TMP  # must precede core imports (BASE)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pyaudiowpatch  # noqa: F401
except ImportError:
    sys.modules['pyaudiowpatch'] = types.ModuleType('pyaudiowpatch')

import customtkinter as ctk

from core.observation_sessions import get_runtime
from core.observation_profile import BASE

CAP_FIXED = BASE / 'capture_fixed'
DB_PATH = CAP_FIXED / 'battle_dataset' / 'battles.sqlite3'
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

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
_db = sqlite3.connect(DB_PATH)
_db.executescript(SCHEMA)
_db.commit()
_db.close()

passed = failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f'PASS {name}')
    else:
        failed += 1
        print(f'FAIL {name}')


def payload(uid, score, first_seen):
    entry = {"anchor_id": "1", "score": score, "score_known": True,
             "nickname": uid, "unique_id": uid}
    return json.dumps({"mode": "individual", "host_user_id": "1",
                       "host_nickname": uid, "participants": [entry],
                       "active": False,
                       "start_time_ms": int(first_seen * 1000)})


def insert_battle(uid, bid, status, score, first, last):
    db = sqlite3.connect(DB_PATH)
    db.execute("INSERT OR REPLACE INTO battles VALUES (?,?,?,?,?,?)",
               (uid, bid, first, last, status, payload(uid, score, first)))
    db.commit()
    db.close()


root = ctk.CTk()


def pump(seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def wait_until(predicate, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        root.update()
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


import ui.pages.unattended_report as page_module

page_module.messagebox.showerror = lambda *a, **k: None
page_module.messagebox.showwarning = lambda *a, **k: None
page_module.messagebox.showinfo = lambda *a, **k: None

store = get_runtime(str(CAP_FIXED)).store
NOW = time.time()

# ---------------------------------------------------------------- A1
insert_battle('mio', 7001, 'finished', 87519, NOW - 600, NOW - 300)
s1 = store.start_session('固定観測', targets=['mio'], profile='capture_fixed',
                         now=NOW - 900)
store.stop_session(s1['session_id'], 'normal', now=NOW - 60)

page = page_module.UnattendedReportPage(root)
page.pack(fill='both', expand=True)
check('A1a opening the page auto-displays the latest session',
      wait_until(lambda: page._report is not None
                 and page._report['session'] is not None
                 and page._report['session']['session_id'] == s1['session_id']))
check('A1b the auto display aggregated the finished battle',
      page._report['summary']['record_count'] == 1
      and page._report['battles'][0]['final_score'] == 87519)
check('A1c the display aggregation is labelled as display, not manual',
      page._report['generation']['trigger'] == 'display')
reports_dir = CAP_FIXED / 'observation_report' / 'reports'
written = list(reports_dir.glob('report_*.json')) if reports_dir.exists() else []
check('A1d the display path wrote NO report file', written == [])
check('A1e the session was NOT marked as report-generated',
      store.get_session(s1['session_id'])['report_state'] == 'none')
page.destroy()
pump(0.2)

# ---------------------------------------------------------------- A2
s2 = store.start_session('固定観測', targets=['mio'], profile='capture_fixed',
                         now=NOW - 120)
insert_battle('mio', 7002, 'active', 43022, NOW - 100, NOW - 10)
# The sampler's heartbeat is what advances a running session's
# window end in the real app; simulate a connected collector.
store.heartbeat(s2['session_id'], True, last_data_at=NOW - 10, now=NOW - 5)

page2 = page_module.UnattendedReportPage(root)
page2.pack(fill='both', expand=True)


def battle_of(page_obj, bid):
    if not page_obj._report:
        return None
    return next((b for b in page_obj._report['battles']
                 if b['battle_id'] == bid), None)


check('A2a live session auto-displays with the battle unconfirmed',
      wait_until(lambda: battle_of(page2, 7002) is not None))
b = battle_of(page2, 7002)
check('A2b unconfirmed battle has NO final score (reference only)',
      b['finished_confirmed'] is False and b['final_score'] is None
      and b['last_known_score'] == 43022)
check('A2c confirmed-final count excludes the unconfirmed battle',
      page2._report['summary']['score_known_battles'] == 0)

# The end notification lands in the DB (score updated to the final).
insert_battle('mio', 7002, 'finished', 87519, NOW - 100, NOW - 5)
store.heartbeat(s2['session_id'], True, last_data_at=NOW - 5, now=time.time())
page2._auto_refresh()
check('A2d next refresh reflects the confirmed end and final score',
      wait_until(lambda: (battle_of(page2, 7002) or {}).get('final_score') == 87519)
      and page2._report['summary']['score_known_battles'] == 1)

# Selection preservation across an auto re-render.
page2._selected_battle = battle_of(page2, 7002)
page2.battle_menu.set(f"{b['nickname']} / {b['first_seen_jst']}")
insert_battle('mio', 7003, 'finished', 100, NOW - 90, NOW - 20)
page2._auto_refresh()
check('A2e a later refresh keeps the user-selected battle',
      wait_until(lambda: page2._report is not None
                 and len(page2._report['battles']) == 2)
      and page2._selected_battle is not None
      and page2._selected_battle['battle_id'] == 7002)
page2.destroy()
pump(0.2)
store.stop_session(s2['session_id'], 'normal', now=time.time())

# ---------------------------------------------------------------- A3
s3 = store.start_session('固定観測', targets=['ghost'], profile='capture_fixed',
                         now=time.time() - 30)
page3 = page_module.UnattendedReportPage(root)
page3.pack(fill='both', expand=True)
check('A3a zero-data session still auto-displays an aggregation',
      wait_until(lambda: page3._report is not None
                 and page3._report['session'] is not None
                 and page3._report['session']['session_id'] == s3['session_id']))
check('A3b zero battles: record count 0 and no battle selected',
      page3._report['summary']['record_count'] == 0
      and page3._selected_battle is None)
kpi = {item['title']: item['value']
       for item in page_module.kpi_items(page3._report)}
check('A3c unknown scores render as 未取得, never 0',
      kpi['最大確認スコア'] == '未取得' and kpi['スコア中央値'] == '未取得')
page3.destroy()
pump(0.2)
store.stop_session(s3['session_id'], 'normal', now=time.time())

# ---------------------------------------------------------------- A4 + A5
page4 = page_module.UnattendedReportPage(root)
page4.pack(fill='both', expand=True)
wait_until(lambda: page4._report is not None)
before = page4._report
page4._display_gen += 1  # any real in-flight result is stale now, too
page4._queue.put(('display_report', page4._display_gen + 999,
                  {'marker': 'stale'}))
page4._pump()
check('A4a a stale-generation display result is dropped',
      page4._report is before)
page4._display_request = {'scope': {'kind': 'all'}, 'session_id': None,
                          'auto': False}
page4._display_inflight = 4242
page4._start_display_refresh()
check('A4b no duplicate aggregation while one is in flight',
      page4._display_inflight == 4242)
page4._display_inflight = None
page4._generating = True
page4._start_display_refresh()
check('A4c no display aggregation while a manual generate runs',
      page4._display_inflight is None)
page4._generating = False

page4._sessions = store.list_sessions(limit=50)
page4._display_request = {'scope': {'kind': 'session'},
                          'session_id': s1['session_id'], 'auto': False}
page4._retarget_display()
check('A5a an explicit display request is sticky (never retargeted)',
      page4._display_request['session_id'] == s1['session_id'])
page4._display_request = {'scope': {'kind': 'session'},
                          'session_id': s1['session_id'], 'auto': True}
s4 = store.start_session('固定観測', targets=['mio'], profile='capture_fixed',
                         now=time.time())
page4._sessions = store.list_sessions(limit=50)
page4._retarget_display()
check('A5b an auto request follows the running session',
      page4._display_request['session_id'] == s4['session_id'])
store.stop_session(s4['session_id'], 'normal', now=time.time())
gen_before = page4._display_gen
page4.source_menu.set('通常観測')
page4.change_source()
check('A5c changing source resets display state and invalidates results',
      page4._display_request is None and page4._report is None
      and page4._display_gen > gen_before)
page4.destroy()
pump(0.2)

# ---------------------------------------------------------------- A6
page5 = page_module.UnattendedReportPage(root)
page5.pack(fill='both', expand=True)
wait_until(lambda: page5._report is not None)
gen_before = page5._display_gen
page5.destroy()
check('A6a destroy invalidates in-flight display results',
      page5._alive is False and page5._display_gen == gen_before + 1)
while not page5._queue.empty():
    page5._queue.get_nowait()
page5._auto_refresh()
check('A6b auto refresh after destroy is a no-op',
      page5._display_inflight is None and page5._queue.empty())
page5._pump()  # must return immediately without touching widgets
check('A6c the pump exits quietly after destroy', True)

print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)

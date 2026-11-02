"""Battle detail graphs (PR #12): per-participant series, the
remaining-time axis, gap handling and multi-participant safety.

G1  a 1v1 battle draws TWO coloured series with name legends
G2  unknown points and >30s holes are never connected
G3  consistent payload timing gives the remaining-time axis
G4  a confirmed finish draws the 終了通知 marker
G5  an unfinished battle is annotated 参考スコア and its
    all-unknown opponent produces the 'could not be obtained' note
G6  a 2v2 team battle draws its team series without crashing
G7  without payload timing the axis falls back to recorded times
    (stated on the chart, never guessed)

Run: python tests/battle_detail_chart_test.py  (GUI: needs a display)
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import types
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='pulse_battle_chart_')
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


def individual(host_score, opp_score, opp_known=True, timing=True,
               finished=False):
    parts = [
        {"anchor_id": "1", "score": host_score, "score_known": True,
         "nickname": "mio", "unique_id": "mio__x6"},
        {"anchor_id": "2", "score": opp_score, "score_known": opp_known,
         "nickname": "rival", "unique_id": "rival_x"},
    ]
    data = {"mode": "individual", "host_user_id": "1",
            "host_nickname": "mio", "participants": parts,
            "active": not finished}
    if timing:
        data["start_time_ms"] = int(START * 1000)
        data["duration_seconds"] = 300
    return json.dumps(data)


def team(s1, s2):
    def users(pairs):
        return [{"user_id": uid, "nickname": nick, "unique_id": handle,
                 "score": sc, "score_known": True}
                for uid, nick, handle, sc in pairs]
    return json.dumps({
        "mode": "team", "host_user_id": "1", "host_nickname": "mio",
        "teams": [
            {"team_id": "t1", "score": s1, "score_known": True,
             "users": users([("1", "mio", "mio__x6", s1 // 2),
                             ("3", "mate", "mate_x", s1 - s1 // 2)])},
            {"team_id": "t2", "score": s2, "score_known": True,
             "users": users([("4", "opp1", "opp1_x", s2 // 2),
                             ("5", "opp2", "opp2_x", s2 - s2 // 2)])}],
        "active": True})


def add_battle(bid, first, last, status, row_payload, snaps):
    _db.execute("INSERT INTO battles VALUES (?,?,?,?,?,?)",
                ('mio__x6', bid, first, last, status, row_payload))
    for j, (offset, snap) in enumerate(snaps):
        _db.execute("INSERT INTO snapshots VALUES (?,?,?,?,?)",
                    ('mio__x6', bid, first + offset, f'{bid}fp{j}', snap))


# 7001: 1v1 finished, timed payloads, an unknown opponent point and
# a 110-second hole in the middle.
offsets = [0, 10, 20, 130, 140]
host_vals = [100, 200, 300, 400, 500]
opp_vals = [50, None, 150, 200, 250]
add_battle(7001, START, START + 140, 'finished',
           individual(500, 250, finished=True),
           [(off, individual(h, o, opp_known=o is not None))
            for off, h, o in zip(offsets, host_vals, opp_vals)])
for dt, viewers in ((0, 10), (20, 25), (40, 15)):
    _db.execute("INSERT INTO viewer_samples VALUES (?,?,?,?,?)",
                ('mio__x6', 7001, START + dt, dt, viewers))
# 7002: 1v1 active, opponent never known, no timing in payloads.
add_battle(7002, START + 1000, START + 1060, 'active',
           individual(90, None, opp_known=False, timing=False),
           [(off, individual(30 + off, None, opp_known=False,
                             timing=False))
            for off in (0, 30, 60)])
# 7003: 2v2 team battle, finished.
add_battle(7003, START + 2000, START + 2060, 'finished', team(800, 600),
           [(off, team(200 + off * 5, 150 + off * 4))
            for off in (0, 20, 40, 60)])
_db.commit()

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


def texts(canvas):
    return [canvas.itemcget(i, 'text') for i in canvas.find_all()
            if canvas.type(i) == 'text']


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
check('setup: report lists the three battles',
      wait_until(lambda: page._report is not None
                 and len(page._report['battles']) == 3))
page.tabs.set('バトル履歴')
pump(0.3)

# ------------------------------------------------------------- G1-G4
check('load: snapshot series arrives for 7001', open_detail(7001))
chart_texts = texts(page.bd_score_chart)
check('G1a two series are drawn (host + opponent lines)',
      line_count(page.bd_score_chart, '#3B82F6') >= 1
      and line_count(page.bd_score_chart, '#EF4444') >= 1)
check('G1b legends carry the participant names',
      any('自枠' in t and 'mio' in t for t in chart_texts)
      and any('rival（@rival_x）' in t for t in chart_texts),
      str(chart_texts))
check('G2a the host series connects only within 30s (3 segments)',
      line_count(page.bd_score_chart, '#3B82F6') == 3,
      str(line_count(page.bd_score_chart, '#3B82F6')))
check('G2b the opponent series breaks on unknown and on the hole (1)',
      line_count(page.bd_score_chart, '#EF4444') == 1,
      str(line_count(page.bd_score_chart, '#EF4444')))
check('G3 the axis is the remaining-time axis with a stated basis',
      any('バトル残り時間' in t for t in chart_texts)
      and ('5:00' in chart_texts or '0:00' in chart_texts),
      str(chart_texts))
check('G4 a confirmed finish draws the 終了通知 marker',
      '終了通知' in chart_texts)
check('G1c the viewer chart drew its series too',
      line_count(page.bd_viewer_chart, '#3B82F6') >= 1)
page._close_battle_detail()
pump(0.2)

# ------------------------------------------------------------- G5/G7
check('load: snapshot series arrives for 7002', open_detail(7002))
chart_texts = texts(page.bd_score_chart)
check('G5a an unfinished battle is annotated as reference-only',
      '参考スコア（終了未確認）' in chart_texts
      and '終了通知' not in chart_texts)
check('G5b the all-unknown opponent is explained, not silently dropped',
      '相手側スコアは取得できませんでした' in page.bd_score_note.cget('text'))
check('G7 no timing in payloads -> recorded-time axis, stated as such',
      any('記録時刻で表示' in t for t in chart_texts), str(chart_texts))
page._close_battle_detail()
pump(0.2)

# ------------------------------------------------------------- G6
check('load: snapshot series arrives for 7003', open_detail(7003))
chart_texts = texts(page.bd_score_chart)
team_colors = sum(1 for c in ('#3B82F6', '#EF4444', '#22C55E')
                  if line_count(page.bd_score_chart, c) >= 1)
check('G6 the 2v2 team battle draws multiple series without crashing',
      team_colors >= 2
      and any('opp1（@opp1_x）' in t for t in chart_texts)
      and any('自枠（個人）' in t for t in chart_texts),
      str(chart_texts))

page.destroy()
pump(0.2)
root.destroy()

print()
if FAILURES:
    print(f'{len(FAILURES)} FAILURES: {FAILURES}')
    sys.exit(1)
print('battle detail chart tests passed')

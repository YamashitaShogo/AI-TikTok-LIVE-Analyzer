"""AI tab readability (PR #12): KPI cards from the Python
aggregates, card-style AI results without fixed-height inner
scrollboxes, the send-payload preview collapsed by default, and
AI results never mixing across sessions.

The KPI values must come from the displayed report's summary only
(the AI never recomputes them); unknown stays 未取得. The preview
 text stays the exact evidence JSON — only its placement changed.
"""
import json
import os
import sqlite3
import sys
import tempfile
import time
import types
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix='pulse_ai_ui_')
os.environ['LOCALAPPDATA'] = _TMP  # must precede core imports (BASE)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pyaudiowpatch  # noqa: F401
except ImportError:
    sys.modules['pyaudiowpatch'] = types.ModuleType('pyaudiowpatch')

import customtkinter as ctk

from core.observation_profile import BASE
from core.observation_sessions import get_runtime
from ui.pages import unattended_report as page_module
from ui.pages.unattended_report import format_ai_section

page_module.messagebox.showerror = lambda *a, **k: None
page_module.messagebox.showwarning = lambda *a, **k: None
page_module.messagebox.showinfo = lambda *a, **k: None

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


def insert_battle(uid, bid, status, score, first, last, viewers=None):
    db = sqlite3.connect(DB_PATH)
    db.execute("INSERT OR REPLACE INTO battles VALUES (?,?,?,?,?,?)",
               (uid, bid, first, last, status, payload(uid, score, first)))
    for at, count in (viewers or []):
        db.execute("INSERT OR REPLACE INTO viewer_samples VALUES (?,?,?,?,?)",
                   (uid, bid, at, None, count))
    db.commit()
    db.close()


def wait_until(predicate, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        root.update()
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


# --- format_ai_section (pure) ----------------------------------------------
check('F1 repeated heading line is dropped, content kept',
      format_ai_section('良かった点：\n後半にスコアが伸びました。')
      == '後半にスコアが伸びました。')
check('F2 excess blank lines collapse, wording untouched',
      format_ai_section('一行目。\n\n\n\n二行目。') == '一行目。\n\n二行目。')
check('F3 empty stays empty', format_ai_section('') == ''
      and format_ai_section(None) == '')

# --- page ------------------------------------------------------------------
NOW = time.time()
runtime = get_runtime(CAP_FIXED)
store = runtime.store
s_old = store.start_session('固定観測', targets=['alice'], profile='capture_fixed',
                            now=NOW - 7200)
store.stop_session(s_old['session_id'], 'normal', now=NOW - 7000)
s_new = store.start_session('固定観測', targets=['alice'], profile='capture_fixed',
                            now=NOW - 600)
insert_battle('alice', 9101, 'finished', 123456, NOW - 500, NOW - 200,
              viewers=[(NOW - 400, 321), (NOW - 300, 876)])
store.heartbeat(s_new['session_id'], True, last_data_at=NOW - 200, now=NOW - 100)
store.stop_session(s_new['session_id'], 'normal', now=NOW - 90)

root = ctk.CTk()
root.geometry('1500x950')
page = page_module.UnattendedReportPage(root)
page.pack(fill='both', expand=True)
check('U1 latest session report auto-displays',
      wait_until(lambda: page._report is not None
                 and (page._report.get('session') or {}).get('session_id')
                 == s_new['session_id']))
page.tabs.set('AI改善提案')
root.update()

summary = page._report['summary']
check('U2 KPI battles = Python aggregate (unique battles)',
      page.ai_kpi_cards['battles']._value.cget('text')
      == f"{summary['unique_battle_count']:,}")
check('U3 KPI max confirmed score = Python aggregate',
      page.ai_kpi_cards['score_max']._value.cget('text') == '123,456')
check('U4 KPI peak viewers = Python aggregate',
      page.ai_kpi_cards['viewer_peak']._value.cget('text') == '876')

page._update_ai_kpis({'summary': {'unique_battle_count': 0,
                                  'final_score_max': None,
                                  'viewer_peak_max': None}})
check('U5 unknown KPI shows 未取得 (never a fabricated number)',
      page.ai_kpi_cards['score_max']._value.cget('text') == '未取得'
      and page.ai_kpi_cards['viewer_peak']._value.cget('text') == '未取得')
check('U6 a real zero battle count shows 0',
      page.ai_kpi_cards['battles']._value.cget('text') == '0')
page._update_ai_kpis(page._report)

# Result cards are labels, and the preview is the tab's only textbox.
check('U7 result cards are wrapping labels (no inner scrollboxes)',
      all(isinstance(label, ctk.CTkLabel) for label in page.ai_labels.values()))
textboxes = []


def collect(widget):
    if isinstance(widget, ctk.CTkTextbox):
        textboxes.append(widget)
    for child in widget.winfo_children():
        collect(child)


collect(page.tabs.tab('AI改善提案'))
check('U8 the send preview is the only textbox in the AI tab',
      textboxes == [page.ai_preview])

# Preview: collapsed by default, exact payload inside, toggle works.
root.update()
check('U9 preview detail is collapsed by default',
      not page.ai_detail_frame.winfo_ismapped())
preview_text = page.ai_preview.get('1.0', 'end')
check('U10 preview holds the exact evidence JSON (payload unchanged)',
      '"schema": "livemetry_unattended_ai_evidence_v1"' in preview_text
      and '"final_score_max": 123456' in preview_text)
page._toggle_ai_detail()
root.update()
check('U11 toggle opens the detail area',
      page.ai_detail_frame.winfo_ismapped()
      and '閉じる' in page.ai_detail_button.cget('text'))
page._toggle_ai_detail()
root.update()
check('U12 toggle closes it again', not page.ai_detail_frame.winfo_ismapped())

# AI result rendering through the real pump path.
ANSWER = ('① 今回の観測結果：R0001 の記録バトルは1件でした。\n'
          '② 良かった傾向：\n後半の記録区間でスコア増加が大きい傾向が見られました。\n'
          '③ 改善を検討したい点：\n序盤の記録が少なく、比較が難しい点です。\n'
          '④ 次回の配信で試すこと：\n開始直後から観測を安定させることを試します。')
page._ai_pending_token = page._report_token(page._report)
page._queue.put(('ai', page._load_gen, {'answer': ANSWER}, None, ''))
page._pump()
root.update()
check('U13 sections land in their cards',
      '記録バトルは1件' in page.ai_labels['summary'].cget('text')
      and 'スコア増加が大きい' in page.ai_labels['good'].cget('text')
      and '比較が難しい' in page.ai_labels['improve'].cget('text')
      and '観測を安定' in page.ai_labels['next'].cget('text'))
check('U14 the section heading is not duplicated inside the card',
      '良かった傾向' not in page.ai_labels['good'].cget('text'))

# Switching to another session clears the previous AI result.
page.show_history_session(s_old['session_id'])
check('U15 switching sessions clears the old AI result',
      wait_until(lambda: (page._report.get('session') or {}).get('session_id')
                 == s_old['session_id'])
      and page.ai_labels['good'].cget('text')
      == 'AI改善分析を実行すると、ここに表示されます。'
      and page.ai_status.cget('text') == '未実行')

# KPI reflow: narrow stacks, wide rows.
root.geometry('1500x950')
root.update()
page._layout_ai_kpis()
check('U16 wide window lays KPIs in a row', page._ai_kpi_mode == 'row')
# The page has a minimum layout width, so a narrow AI viewport is
# simulated with the same Configure event a real resize delivers.
page._ai_scroll._parent_canvas.event_generate('<Configure>', width=420)
root.update()
check('U17 narrow viewport stacks the KPI cards', page._ai_kpi_mode == 'stack')
page._ai_scroll._parent_canvas.event_generate('<Configure>', width=1400)
root.update()
check('U18 widening the viewport restores the row', page._ai_kpi_mode == 'row')
root.geometry('1500x950')
root.update()

page.destroy()
print(f'\n{passed} passed, {failed} failed')
raise SystemExit(1 if failed else 0)

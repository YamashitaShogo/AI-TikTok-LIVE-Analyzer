"""Run with python top_viewer.py alongside normal Pulse."""
import json
import os
import sqlite3
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from core.observation_profile import BASE, live_url
from core.fixed_import import import_finished
from core.fixed_score_graph import FixedScoreGraph

ROOT = Path(__file__).resolve().parent
CAPTURE = BASE / 'capture_fixed'
DB = CAPTURE / 'battle_dataset' / 'battles.sqlite3'

def main():
    # GUI singleton lock (this window only). The fixed PROFILE itself
    # is excluded by the collector process via core/fixed_lock.py
    # (BASE/fixed_viewer.lock): the writer holds the lock, not a
    # launcher, so this window no longer holds the profile lock.
    BASE.mkdir(parents=True, exist_ok=True)
    lock = (BASE / 'fixed_viewer_ui.lock').open('a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        messagebox.showerror('固定観測', '固定観測の操作画面は既に起動しています')
        lock.close(); return
    root = tk.Tk(); root.title('Livemetry Pulse｜Top固定観測'); root.geometry('860x720'); root.minsize(720,600)
    process = None; log = None
    value = tk.StringVar()
    saved = BASE / 'fixed_target.json'
    try: value.set(json.loads(saved.read_text(encoding='utf-8'))['url'])
    except (OSError, ValueError, KeyError): pass
    status = tk.StringVar(value='停止中')
    ttk.Label(root,text='配信者ID または https://www.tiktok.com/@ID/live').pack(pady=(18,5))
    ttk.Entry(root,textvariable=value,width=70).pack(padx=15)
    ttk.Label(root,text='固定観測：自動スクロールなし／巡回とは別ログイン・別保存先').pack(pady=10)
    def stop():
        nonlocal process, log
        if process and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        process = None
        if log: log.close(); log = None
        status.set('停止中（進行中バトルは未完了のまま残る場合があります）')
    def start():
        nonlocal process, log
        if process and process.poll() is None:
            messagebox.showinfo('固定観測','切替時は先に停止してください'); return
        try:
            from core.fixed_lock import probe_locked, read_status
            if probe_locked():
                held = read_status() or {}
                tid = str(held.get('target_id') or '')
                messagebox.showerror('固定観測',
                    '別の固定観測が既に動作しています'
                    + (f'（対象 @{tid}）' if tid else '')
                    + '。Pulse Proの固定観測や別の固定観測を停止してから開始してください')
                return
        except Exception:
            pass  # the collector itself enforces the lock at startup
        try:
            url = live_url(value.get())
            env = os.environ.copy()
            env.update(LIVEMETRY_OBSERVATION_MODE='fixed', LIVEMETRY_FIXED_URL=url, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
            if not env.get('LIVEMETRY_EULER_API_KEY') and os.name == 'nt':
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as key:
                    try: env['LIVEMETRY_EULER_API_KEY'] = winreg.QueryValueEx(key,'LIVEMETRY_EULER_API_KEY')[0]
                    except FileNotFoundError: pass
            CAPTURE.mkdir(parents=True,exist_ok=True)
            if log: log.close()
            log = (CAPTURE/'viewer_fixed.log').open('a',encoding='utf-8',buffering=1)
            process = subprocess.Popen([sys.executable,'-u',str(ROOT/'core'/'viewer_collector.py')],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            saved.write_text(json.dumps({'url':url}),encoding='utf-8')
            status.set('固定観測を起動しました。初回はViewerでログインしてください')
        except Exception as exc:
            messagebox.showerror('起動失敗',str(exc))
    def stats():
        if not DB.exists(): status.set('まだ記録がありません'); return
        try:
            with sqlite3.connect(f'{DB.as_uri()}?mode=ro',uri=True,timeout=2) as db:
                counts=[db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('battles','snapshots','viewer_samples')]
            status.set(f'固定記録：バトル {counts[0]} ／スナップショット {counts[1]} ／人数 {counts[2]}')
        except sqlite3.Error as exc: messagebox.showerror('確認失敗',str(exc))
    def merge():
        try:
            result=import_finished(DB,BASE/'capture'/'battle_dataset'/'battles.sqlite3')
            status.set(f'取込 {result["imported"]}件／重複・除外対象 {result["skipped"]}件。Pulseの収集分析を更新してください')
        except Exception as exc: messagebox.showerror('取込失敗',str(exc))
    buttons=ttk.Frame(root);buttons.pack(pady=8)
    for text,cmd in [('固定観測を開始',start),('停止',stop),('記録数を確認',stats),('Pulse分析へ取り込む',merge)]:
        ttk.Button(buttons,text=text,command=cmd).pack(side='left',padx=3)
    ttk.Label(root,textvariable=status,wraplength=550).pack(pady=12)
    ttk.Label(root,text='終了済み・除外フラグなしのバトルだけ分析へ取込。既存の同一枠・同一試合は保持。',wraplength=550).pack()
    graph = FixedScoreGraph(root, DB)
    graph.pack(fill='both',expand=True,padx=10,pady=10)
    def close(): stop(); graph.destroy(); root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    root.mainloop(); lock.close()

if __name__ == '__main__': main()

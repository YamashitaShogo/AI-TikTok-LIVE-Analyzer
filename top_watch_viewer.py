"""Top watchlist controller. Run beside the normal patrol Viewer."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox
from core.observation_profile import BASE, live_url
from core.top_watch import read_json, write_json


def main():
    BASE.mkdir(parents=True, exist_ok=True)
    lock = (BASE / 'fixed_viewer.lock').open('a+b')
    if os.name == 'nt':
        import msvcrt
        try:
            lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            messagebox.showerror('Top監視', '既存のTop固定観測を閉じてから起動してください')
            lock.close(); return
    root = tk.Tk(); root.title('Livemetry Pulse｜Top監視リスト'); root.geometry('670x570')
    config_path = BASE / 'top_watchlist.json'
    old = read_json(config_path)
    ttk.Label(root, text='Top監視リスト（1行に1人のID／上から優先）').pack(pady=(18, 6))
    editor = tk.Text(root, height=10, width=65); editor.pack(fill='x', padx=20)
    editor.insert('1.0', '\n'.join(old.get('ids', [])))
    slots = tk.IntVar(value=old.get('slots', 2))
    row = ttk.Frame(root); row.pack(pady=8)
    ttk.Label(row, text='同時探索枠数（Viewer接続は別）').pack(side='left')
    ttk.Spinbox(row, from_=1, to=3, textvariable=slots, width=4).pack(side='left', padx=8)
    ttk.Label(root, text='配信なしは次へ（接続間隔30秒／再確認5分）。待機枠は3分で交代。\nバトル中は移動せず、終了後に検知した枠へ移動します。', justify='left').pack(pady=8)
    status = tk.StringVar(value='停止中')
    proc = None; log = None
    def save(enabled):
        ids = []
        for line in editor.get('1.0', 'end').splitlines():
            if line.strip(): ids.append(live_url(line).split('/@')[1].split('/')[0])
        ids = list(dict.fromkeys(ids))
        if not ids: raise ValueError('監視する配信者IDを入力してください')
        if len(ids) > 100: raise ValueError('登録は100人以内にしてください')
        n = slots.get()
        if n not in (1, 2, 3): raise ValueError('同時探索は1〜3枠です')
        write_json(config_path, {'ids': ids, 'slots': n, 'enabled': enabled})
        return ids
    def stop():
        nonlocal proc, log
        config = read_json(config_path); config['enabled'] = False; write_json(config_path, config)
        if proc and proc.poll() is None:
            # On Windows, also terminate discovery children to avoid orphan connections.
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
            else: proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
        proc = None
        if log: log.close(); log = None
        status.set('停止中')
    def start():
        nonlocal proc, log
        try:
            ids = save(True)
            if proc and proc.poll() is None: return
            env = os.environ.copy()
            if not env.get('LIVEMETRY_EULER_API_KEY') and os.name == 'nt':
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
                    try: env['LIVEMETRY_EULER_API_KEY'] = winreg.QueryValueEx(key, 'LIVEMETRY_EULER_API_KEY')[0]
                    except FileNotFoundError: pass
            env.update(LIVEMETRY_OBSERVATION_MODE='fixed', LIVEMETRY_TOP_WATCH='1',
                       LIVEMETRY_FIXED_URL=live_url(ids[0]), PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
            folder = BASE / 'capture_fixed'; folder.mkdir(parents=True, exist_ok=True)
            log = (folder / 'viewer_top_watch.log').open('a', encoding='utf-8')
            project = Path(__file__).resolve().parent
            proc = subprocess.Popen([sys.executable, '-u', str(project / 'core/viewer_collector.py')],
                cwd=project, env=env, stdout=log, stderr=subprocess.STDOUT)
            status.set('起動中。初回は固定ViewerでTikTokにログインしてください')
        except Exception as exc: messagebox.showerror('起動失敗', str(exc))
    def merge():
        from core.fixed_import import import_finished
        try:
            result = import_finished(BASE / 'capture_fixed/battle_dataset/battles.sqlite3',
                                     BASE / 'capture/battle_dataset/battles.sqlite3')
            messagebox.showinfo('取込完了', f'取込 {result["imported"]}件。Pulseの収集履歴を更新してください')
        except Exception as exc:
            messagebox.showerror('取込失敗', str(exc))
    row = ttk.Frame(root); row.pack(pady=8)
    ttk.Button(row, text='監視開始／リスト反映', command=start).pack(side='left', padx=6)
    ttk.Button(row, text='停止', command=stop).pack(side='left', padx=6)
    ttk.Button(row, text='Pulseへ取り込む', command=merge).pack(side='left', padx=6)
    ttk.Label(root, textvariable=status, wraplength=620, justify='left').pack(padx=20, pady=12)
    def poll():
        if proc and proc.poll() is None:
            state = read_json(BASE / 'top_watch_status.json')
            status.set(state.get('message', '起動中') + '\n観測：' + state.get('viewer', '') +
                       '\n探索中：' + ', '.join(state.get('watching', [])) +
                       '\n順番待ち：' + ', '.join(state.get('waiting', [])) +
                       '\n配信なし：' + ', '.join(state.get('offline', [])))
        elif proc: status.set('Viewerが終了しました。ログを確認してください')
        root.after(2000, poll)
    def close(): stop(); root.destroy()
    root.protocol('WM_DELETE_WINDOW', close); poll(); root.mainloop(); lock.close()


if __name__ == '__main__': main()

"""Read-only score history for the fixed observation window."""
import json
import math
import sqlite3
import tkinter as tk
from tkinter import ttk
from datetime import datetime
from pathlib import Path

try:
    from core.score_known import known_score
except ModuleNotFoundError:
    from score_known import known_score

def number(value):
    if isinstance(value, bool): return None
    try: value = float(value)
    except (TypeError, ValueError): return None
    return value if math.isfinite(value) and value >= 0 else None

def scores(payload):
    """Series values keyed by STABLE identity, never by display name.

    Keys stay identical for a whole battle even when nicknames only
    become known partway through (e.g. at FINISH): individual mode
    uses '自枠' / '相手 <anchor_id>'; a one-person team is that person
    ('自枠' for the host, '相手 <user_id>' otherwise); a multi-person
    team uses 'チーム <team_id>' plus '自枠（個人）' for the host's own
    score inside it. Display names live in series_labels() instead.
    """
    result = {}
    host = str(payload.get('host_user_id') or '')
    if payload.get('mode') == 'team':
        for team in payload.get('teams') or []:
            key = str(team.get('team_id') or '')
            if not key: continue
            users = team.get('users') or []
            if len(users) == 1:
                uid = str(users[0].get('user_id') or '')
                if uid:
                    result['自枠' if uid == host else '相手 '+uid] = known_score(team)
                    continue
            result['チーム '+key] = known_score(team)
            for user in users:
                if host and str(user.get('user_id')) == host:
                    result['自枠（個人）'] = known_score(user)
    else:
        for user in payload.get('participants') or []:
            key = str(user.get('anchor_id') or user.get('key') or '')
            if key:
                result['自枠' if key == host else '相手 '+key] = known_score(user)
    return result

def series_labels(payload):
    """Display labels for the stable series keys, from one payload.

    Only labels backed by a recorded nickname are returned; series
    without a name keep their stable key as the legend text.
    """
    labels = {}
    host = str(payload.get('host_user_id') or '')
    if payload.get('mode') == 'team':
        for team in payload.get('teams') or []:
            key = str(team.get('team_id') or '')
            if not key: continue
            users = team.get('users') or []
            if len(users) == 1:
                uid = str(users[0].get('user_id') or '')
                nickname = str(users[0].get('nickname') or '').strip()
                if uid and uid != host and nickname:
                    labels['相手 '+uid] = nickname
                continue
            names = [str(u.get('nickname') or '').strip() for u in users]
            names = [name for name in names if name]
            if names:
                labels['チーム '+key] = '・'.join(names)
    else:
        for user in payload.get('participants') or []:
            key = str(user.get('anchor_id') or user.get('key') or '')
            nickname = str(user.get('nickname') or '').strip()
            if key and key != host and nickname:
                labels['相手 '+key] = nickname
    return labels

def resolve_labels(payloads):
    """Merge series_labels over a battle's payloads; a name, once
    known in any snapshot, labels the series for the whole battle."""
    labels = {}
    for payload in payloads or []:
        for key, label in series_labels(payload).items():
            if key not in labels:
                labels[key] = label
    return labels

def load_history(path, selected=None):
    path = Path(path)
    if not path.exists(): return [], None
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=.2) as db:
        choices = db.execute('SELECT unique_id,battle_id,last_seen,status FROM battles ORDER BY last_seen DESC LIMIT 50').fetchall()
        if not choices: return [], None
        key = selected or choices[0][:2]
        row = db.execute('SELECT payload FROM battles WHERE unique_id=? AND battle_id=?', key).fetchone()
        if not row: return choices, None
        points = []; payloads = []
        for received, raw in db.execute('SELECT received_at,payload FROM snapshots WHERE unique_id=? AND battle_id=? ORDER BY received_at',key):
            try: p = json.loads(raw)
            except ValueError: continue
            payloads.append(p)
            points.append((received, scores(p), p.get('start_time_ms')))
        starts = [number(p[2]) for p in points if number(p[2]) is not None and number(p[2]) > 0]
        origin = min(starts)/1000 if starts else (points[0][0] if points else 0)
        return choices, {'key':key,'points':[(max(0,t-origin),v) for t,v,_ in points], 'start_known':bool(starts), 'labels':resolve_labels(payloads)}

class FixedScoreGraph(ttk.Frame):
    def __init__(self, parent, database):
        super().__init__(parent)
        self.database = database; self.keys = {}; self.data = None; self.timer = None
        self.choice = tk.StringVar(value='最新のバトル（自動追従）')
        self.combo = ttk.Combobox(self,textvariable=self.choice,state='readonly',width=85)
        self.combo.pack(fill='x',padx=8,pady=5)
        self.combo.bind('<<ComboboxSelected>>',lambda _: self.refresh())
        self.info = ttk.Label(self,text='スコア記録を待っています'); self.info.pack()
        self.canvas = tk.Canvas(self,bg='#ffffff',height=300,highlightthickness=0)
        self.canvas.pack(fill='both',expand=True,padx=8,pady=8)
        self.canvas.bind('<Configure>',lambda _:self.draw())
        self.refresh()
    def destroy(self):
        if self.timer: self.after_cancel(self.timer)
        super().destroy()
    def refresh(self):
        if self.timer: self.after_cancel(self.timer)
        try:
            choices,self.data=load_history(self.database,self.keys.get(self.choice.get()))
            self.keys={f'{datetime.fromtimestamp(t):%m/%d %H:%M}  @{uid}  {bid}  [{state}]':(uid,bid) for uid,bid,t,state in choices}
            self.combo['values']=['最新のバトル（自動追従）',*self.keys]
            # Keep a historical selection stable as its status/last_seen changes.
            if self.choice.get() != '最新のバトル（自動追従）' and self.data:
                for label,key in self.keys.items():
                    if key == tuple(self.data['key']): self.choice.set(label); break
            self.draw()
        except (sqlite3.Error, ValueError, TypeError) as exc:
            self.info.config(text=f'読込待機：{type(exc).__name__}（3秒後に再確認）')
        self.timer=self.after(3000,self.refresh)
    def draw(self):
        c=self.canvas;c.delete('all')
        if not self.data or not self.data['points']:
            c.create_text(250,100,text='バトルのスコア記録を待っています'); return
        pts=self.data['points']; keys=list(dict.fromkeys(k for _,v in pts for k in v))
        vals=[v for _,d in pts for v in d.values() if v is not None]
        if not vals:
            self.info.config(text='スコア未取得（不明を0点として描画しません）');return
        w=max(c.winfo_width(),400);h=max(c.winfo_height(),240)
        left,right,top,bottom=75,w-20,20,h-85
        xmax=max(1,max(t for t,_ in pts));ymax=max(1,max(vals))*1.1
        xy=lambda t,v:(left+(right-left)*t/xmax,bottom-(bottom-top)*v/ymax)
        for i in range(5):
            y=bottom-(bottom-top)*i/4
            c.create_line(left,y,right,y,fill='#e5e7eb')
            c.create_text(left-8,y,text=f'{ymax*i/4:,.0f}',anchor='e')
            x=left+(right-left)*i/4;t=xmax*i/4
            c.create_text(x,bottom+15,text=f'{int(t)//60}:{int(t)%60:02d}')
        colors=['#2563eb','#dc2626','#16a34a','#9333ea','#d97706']
        for idx,key in enumerate(keys):
            color=colors[idx%len(colors)]; prev=None
            for t,values in pts:
                v=values.get(key)
                if v is None: prev=None;continue
                x,y=xy(t,v)
                if prev and t-prev[0]<=30: c.create_line(prev[1],prev[2],x,y,fill=color,width=2)
                c.create_oval(x-2,y-2,x+2,y+2,fill=color,outline='')
                prev=(t,x,y)
            c.create_text(left+(idx%2)*(right-left)/2,bottom+38+(idx//2)*17,text=(self.data.get('labels') or {}).get(key,key),fill=color,anchor='w')
        label='バトル開始からの経過' if self.data['start_known'] else '観測開始からの経過（開始時刻不明）'
        uid,bid=self.data['key']
        self.info.config(text=f'@{uid} ｜バトル {bid} ｜横軸：{label}（分:秒）／縦軸：スコア\n3秒ごとに更新・30秒を超える記録間隔は線を接続しません')

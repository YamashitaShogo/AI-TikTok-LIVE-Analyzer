"""Independent, read-only score inspection window."""
from ui.deferred_render import DeferredRender
from core.battle_clock import BattleClock
from bisect import bisect_left
from copy import deepcopy
import tkinter as tk
import customtkinter as ctk
from core.score_history import scores
from core.collection_store import format_time
from core.battle_timeline import hatch_segments
from core.timeline_display import describe_event


class ScoreZoom(ctk.CTkToplevel):
    def __init__(self, parent, detail):
        super().__init__(parent)
        self._render = DeferredRender(self)
        self._caption_text = None
        self.detail = deepcopy(detail)
        self.title('スコア推移を拡大 — ' + str(detail.get('battle_id', '')))
        self.geometry('1200x780')
        self.minsize(720, 520)
        self.points = sorted((float(p['received_at']), scores(p['result']))
                             for p in detail.get('score_snapshots', []) if p.get('received_at') is not None)
        self.events = detail.get('timeline') or []
        times = [p[0] for p in self.points] + [e['at'] for e in self.events]
        times += [e['end'] for e in self.events if e.get('end')]
        self.clock = BattleClock(detail)
        self.full = self.clock.bounds(times)
        if self.full[0] == self.full[1]: self.full = (self.full[0], self.full[1]+1)
        self.range = self.full
        self.drag = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        bar = ctk.CTkFrame(self, fg_color='transparent')
        bar.grid(row=0, column=0, sticky='ew', padx=16, pady=10)
        ctk.CTkButton(bar, text='全体に戻す', width=120, command=self.reset).pack(side='left')
        ctk.CTkLabel(bar, text='  横にドラッグして範囲拡大 ／ マウスで数値確認').pack(side='left')
        self.caption = ctk.CTkLabel(self, text='', anchor='w')
        self.caption.grid(row=1, column=0, sticky='ew', padx=16)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.canvas.grid(row=2, column=0, sticky='nsew', padx=16, pady=8)
        self.info = ctk.CTkLabel(self, text='点差は1対1で両者の値がある場合に表示します。', anchor='w', justify='left', wraplength=1100)
        self.info.grid(row=3, column=0, sticky='ew', padx=16, pady=4)
        listing = ctk.CTkTextbox(self, height=110, wrap='word')
        listing.grid(row=4, column=0, sticky='ew', padx=16, pady=(0, 12))
        listing.insert('1.0', '\n'.join(f"{i+1}. {describe_event(e, detail.get('result') or {}, format_time)}" for i,e in enumerate(self.events)) or 'イベント記録なし')
        listing.configure(state='disabled')
        self.canvas.bind('<Configure>', lambda e: self._render.resize(
            'zoom', (e.width, e.height), self._draw_now))
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.move)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.canvas.bind('<Motion>', self.hover)
        self.canvas.bind('<Leave>', lambda _: self.canvas.delete('cursor'))
        self.bind('<Escape>', lambda _: self.reset())

    def reset(self):
        self.range = self.full
        self.drag = None
        self.draw()

    def time_at(self, x):
        l,t,r,b = self.box
        return self.range[0] + (min(r,max(l,x))-l)/(r-l)*(self.range[1]-self.range[0])

    def press(self, e):
        if hasattr(self, 'box') and self.box[0] <= e.x <= self.box[2] and self.box[1] <= e.y <= self.box[3]:
            self.drag = e.x

    def move(self, e):
        if self.drag is None: return
        self.canvas.delete('selection')
        l,t,r,b = self.box
        self.canvas.create_rectangle(self.drag,t,min(r,max(l,e.x)),b,outline='#2563EB',dash=(4,3),tags='selection')

    def release(self, e):
        if self.drag is None: return
        a,b = sorted((self.time_at(self.drag), self.time_at(e.x)))
        self.drag = None
        self.canvas.delete('selection')
        if b-a >= 1:
            self.range = (a,b)
            self.draw()

    def destroy(self):
        self._render.close()
        super().destroy()

    def draw(self):
        self._render.request('zoom', self._draw_now)

    def _draw_now(self):
        c = self.canvas
        c.delete('all')
        dark = ctk.get_appearance_mode() == 'Dark'
        bg,fg,grid = ('#111C30','#CBD5E1','#334155') if dark else ('#FFFFFF','#475569','#E2E8F0')
        c.configure(bg=bg)
        w,h = max(c.winfo_width(),400), max(c.winfo_height(),220)
        keys = list(dict.fromkeys(k for _,s in self.points for k in s))
        l,t,r,b = 90,42,w-22,max(110,h-45-22*((len(keys)+1)//2))
        self.box = l,t,r,b
        a,z = self.range
        visible = [(ts,s) for ts,s in self.points if a <= ts <= z]
        self.visible = visible
        self.visible_times = [ts for ts,_ in visible]
        vals = [v for _,s in visible for v in s.values() if v is not None]
        low,high = (min(vals),max(vals)) if vals else (0,1)
        pad = max((high-low)*.08,1)
        low,high = max(0,low-pad),high+pad
        x = lambda ts:l+(ts-a)/(z-a)*(r-l)
        y = lambda v:b-(v-low)/(high-low)*(b-t)
        caption = self.clock.caption + '  ' + self.clock.label(a, format_time) + ' → ' + self.clock.label(z, format_time) + ' ／ 縦軸は表示区間に合わせて自動調整'
        if caption != self._caption_text:
            self._caption_text = caption
            self.caption.configure(text=caption)
        for i,e in enumerate(self.events):
            start,end = e['at'],e.get('end')
            color = '#F59E0B' if e.get('kind')=='item' else '#94A3B8' if e.get('phase')=='mission' else '#10B981' if e.get('phase')=='settle' else '#8B5CF6'
            if end and end >= a and start <= z:
                x1,x2 = x(max(a,start)),x(min(z,end))
                if e.get('phase')!='mission':
                    for seg in hatch_segments(x1,t,x2,b,spacing=14): c.create_line(*seg,fill=color,width=1)
            for ts,suffix in ((start,'始'),(end,'終')):
                if ts is not None and a <= ts <= z:
                    xx=x(ts);c.create_line(xx,t,xx,b,fill=color,dash=(3,3))
                    label = '達' if e.get('phase')=='settle' and e.get('succeeded') else '判' if e.get('phase')=='settle' else suffix
                    c.create_text(xx,t-10-(i%2)*14,text=f'{i+1}{label}',fill=color)
        for i in range(5):
            v=low+(high-low)*i/4;yy=y(v)
            c.create_line(l,yy,r,yy,fill=grid)
            c.create_text(l-8,yy,text=f'{v:,.0f}',anchor='e',fill=fg)
        for ts in self.clock.ticks(a,z):
            c.create_text(x(ts),b+16,text=self.clock.label(ts, lambda v: format_time(v).split(' ')[-1]),fill=fg)
        palette=['#2563EB','#EF4444','#10B981','#D97706','#A855F7','#06B6D4']
        for j,k in enumerate(keys):
            prev=None;color=palette[j%len(palette)]
            for ts,s in visible:
                v=s.get(k)
                if v is None: prev=None;continue
                xx,yy=x(ts),y(v)
                if prev and ts-prev[0]<=30:c.create_line(prev[1],prev[2],xx,yy,fill=color,width=2)
                c.create_oval(xx-2,yy-2,xx+2,yy+2,fill=color,outline='')
                prev=ts,xx,yy
            c.create_text(l+(j%2)*(r-l)/2,b+40+(j//2)*22,text=k,anchor='w',fill=color)
        if not vals:c.create_text((l+r)/2,(t+b)/2,text='この範囲にスコア記録はありません',fill=fg)

    def hover(self,e):
        if not hasattr(self,'box') or self.drag is not None:return
        c=self.canvas;c.delete('cursor')
        l,t,r,b=self.box
        if not(l<=e.x<=r and t<=e.y<=b):return
        ts=self.time_at(e.x)
        c.create_line(e.x,t,e.x,b,fill='#64748B',dash=(2,2),tags='cursor')
        if not self.visible:return
        i=bisect_left(self.visible_times,ts)
        candidates=self.visible[max(0,i-1):i+1]
        observed,s=min(candidates,key=lambda p:abs(p[0]-ts))
        if abs(observed-ts)>15:
            self.info.configure(text='この位置の近くにスコア記録がありません（補間しません）');return
        text=f'{self.clock.caption}: {self.clock.label(observed, format_time)} ／ 記録時刻 {format_time(observed)}  ｜ '+ ' ／ '.join(f'{k}: {v:,.0f}' if v is not None else f'{k}: 未取得' for k,v in s.items())
        opponents=[v for k,v in s.items() if k.startswith('相手 ')]
        if s.get('自枠') is not None and len(opponents)==1 and opponents[0] is not None:
            text+=f" ／ 点差（自枠−相手）: {s['自枠']-opponents[0]:+,.0f}"
        self.info.configure(text=text)

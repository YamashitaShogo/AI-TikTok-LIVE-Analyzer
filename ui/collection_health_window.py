import os
import time
import threading
import queue
from pathlib import Path
from datetime import datetime
import customtkinter as ctk
from core.collection_health import read_health


class CollectionHealthWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title('収集状況 — Livemetry Pulse')
        self.geometry('820x650')
        self.minsize(650, 540)
        self._queue = queue.Queue()
        self._busy = False
        self._closed = False
        self._after = None
        ctk.CTkLabel(self, text='収集状況', font=ctk.CTkFont(size=25, weight='bold')).pack(anchor='w',padx=24,pady=(20,4))
        ctk.CTkLabel(self, text='5秒ごとに更新 ／ 今日の件数はPCの現地日付・初回保存日で集計').pack(anchor='w',padx=24)
        body=ctk.CTkScrollableFrame(self, fg_color='transparent');body.pack(fill='both',expand=True,padx=16,pady=12)
        self.cards=[]
        for title in ('通常巡回', 'Top観測'):
            card=ctk.CTkFrame(body,corner_radius=12);card.pack(fill='x',padx=4,pady=8)
            ctk.CTkLabel(card,text=title,font=ctk.CTkFont(size=19,weight='bold')).pack(anchor='w',padx=18,pady=(14,6))
            label=ctk.CTkLabel(card,text='読み込み中…',justify='left',anchor='w',wraplength=700)
            label.pack(fill='x',padx=18,pady=(0,16));self.cards.append(label)
        ctk.CTkLabel(self,text='「接続中」はバトル収集の保証ではありません。最終データ保存も確認してください。',wraplength=760).pack(padx=20,pady=(0,14))
        self.protocol('WM_DELETE_WINDOW',self.destroy)
        self._tick()

    def _load(self):
        base=Path(os.environ.get('LOCALAPPDATA',os.path.expanduser('~'))) / 'AI-TikTok-LIVE-Analyzer'
        try: self._queue.put([read_health(base / p) for p in ('capture','capture_fixed')])
        except Exception: self._queue.put(None)

    def _tick(self):
        if self._closed:return
        try:
            values=self._queue.get_nowait();self._busy=False
            if values:
                for label,r in zip(self.cards,values):
                    def stamp(t):
                        return datetime.fromtimestamp(t).strftime('%m/%d %H:%M:%S') if t else '未確認'
                    text=(f"{r['status']}　｜　観測先：{('@'+r['unique_id']) if r['unique_id'] else '未選択'}\n"
                          f"稼働確認：{stamp(r['heartbeat'])}\n"
                          f"最終データ保存：{stamp(r['last_data'])}\n"
                          f"今日の保存：{r['today'] if r['today'] is not None else '未確認'} 件\n"
                          f"直近の移動・停止ログ（過去の記録を含む）：\n{r['reason']}")
                    if r['db_error']:text+='\n'+r['db_error']
                    label.configure(text=text)
        except queue.Empty:pass
        if not self._busy:
            self._busy=True
            threading.Thread(target=self._load,daemon=True).start()
        self._after=self.after(5000,self._tick)

    def destroy(self):
        self._closed=True
        if self._after:
            try:self.after_cancel(self._after)
            except Exception:pass
        super().destroy()


def open_collection_health(master):
    old=getattr(master,'_collection_health_window',None)
    if old is not None and old.winfo_exists():old.lift();return
    master._collection_health_window=CollectionHealthWindow(master)

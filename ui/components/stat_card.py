"""Reusable KPI stat card (Pulse Pro / future Pulse Agency).

Shows one headline number with a small label above and an optional
sub-line below. Unknown values must be passed as text such as '未取得'
by the caller; this component never invents or zero-fills a value.
"""
import customtkinter as ctk

try:
    from ui import theme
except ImportError:  # direct import style used by some pages
    from .. import theme

CARD = ('#FFFFFF', '#111C30')
TEXT = ('#0F172A', '#F8FAFC')
MUTED = ('#64748B', '#94A3B8')


class StatCard(ctk.CTkFrame):
    def __init__(self, parent, title, value='—', sub='', accent=None,
                 value_size=22, **kwargs):
        super().__init__(parent, fg_color=CARD, corner_radius=theme.RADIUS_MEDIUM,
                         border_width=1, border_color=theme.BORDER, **kwargs)
        if accent:
            ctk.CTkFrame(self, height=4, corner_radius=2, fg_color=accent).pack(
                fill='x', padx=12, pady=(10, 0))
        ctk.CTkLabel(self, text=title, text_color=MUTED, anchor='w',
                     font=(theme.FONT_FAMILY, theme.FONT_SMALL, 'bold')).pack(
                         fill='x', padx=12, pady=(8, 0))
        self._value = ctk.CTkLabel(self, text=str(value), text_color=TEXT, anchor='w',
                                   font=(theme.FONT_FAMILY, value_size, 'bold'))
        self._value.pack(fill='x', padx=12, pady=(2, 0))
        self._sub = ctk.CTkLabel(self, text=sub, text_color=MUTED, anchor='w',
                                 justify='left', wraplength=220,
                                 font=(theme.FONT_FAMILY, theme.FONT_SMALL))
        self._sub.pack(fill='x', padx=12, pady=(0, 10))

    def set_value(self, value, sub=None):
        self._value.configure(text=str(value))
        if sub is not None:
            self._sub.configure(text=sub)

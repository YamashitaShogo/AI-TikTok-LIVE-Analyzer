"""Reusable titled section card.

A white/dark card with a section title; callers add their widgets to
``.body``. Used by the streaming report page and reusable by future
Agency screens.
"""
import customtkinter as ctk

try:
    from ui import theme
except ImportError:
    from .. import theme

CARD = ('#FFFFFF', '#111C30')
TEXT = ('#0F172A', '#F8FAFC')
MUTED = ('#64748B', '#94A3B8')


class SectionCard(ctk.CTkFrame):
    def __init__(self, parent, title, note='', **kwargs):
        super().__init__(parent, fg_color=CARD, corner_radius=theme.RADIUS_MEDIUM,
                         border_width=1, border_color=theme.BORDER, **kwargs)
        head = ctk.CTkFrame(self, fg_color='transparent')
        head.pack(fill='x', padx=14, pady=(12, 0))
        ctk.CTkLabel(head, text=title, text_color=TEXT, anchor='w',
                     font=(theme.FONT_FAMILY, theme.FONT_SECTION_TITLE, 'bold')).pack(side='left')
        if note:
            ctk.CTkLabel(head, text=note, text_color=MUTED, anchor='e',
                         font=(theme.FONT_FAMILY, theme.FONT_SMALL)).pack(side='right')
        self.body = ctk.CTkFrame(self, fg_color='transparent')
        self.body.pack(fill='both', expand=True, padx=14, pady=(6, 12))

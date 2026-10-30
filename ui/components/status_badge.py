"""Reusable status badge label (session / report states)."""
import customtkinter as ctk

try:
    from ui import theme
except ImportError:
    from .. import theme

# kind -> (text, fg_color). Colours come from the shared theme so the
# badge looks the same in Pro and (future) Agency screens.
_KINDS = {
    'running': ('● 観測中', theme.SUCCESS),
    'collector_stopped': ('⚠ コレクタ停止', theme.DANGER),
    'normal': ('終了', theme.PRIMARY),
    'abnormal': ('異常終了', theme.DANGER),
    'interrupted': ('中断', theme.WARNING),
    'none': ('未開始', theme.TEXT_MUTED),
}


class StatusBadge(ctk.CTkLabel):
    def __init__(self, parent, kind='none', **kwargs):
        text, color = _KINDS.get(kind, _KINDS['none'])
        super().__init__(parent, text=text, text_color='#FFFFFF', fg_color=color,
                         corner_radius=10, font=(theme.FONT_FAMILY, 12, 'bold'),
                         padx=10, pady=3, **kwargs)

    def set_status(self, kind):
        text, color = _KINDS.get(kind, _KINDS['none'])
        self.configure(text=text, fg_color=color)

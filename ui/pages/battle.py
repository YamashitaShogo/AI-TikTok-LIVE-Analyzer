import json
import os
from pathlib import Path

import customtkinter as ctk

from ui import theme
import time

try:
    from core.score_known import score_text
except ModuleNotFoundError:
    from score_known import score_text


APP_NAME = "AI-TikTok-LIVE-Analyzer"
CAPTURE_DIR = (
    Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")))
    / APP_NAME
    / "capture"
)
BATTLE_PATH = CAPTURE_DIR / "latest_battle.json"
BATTLE_ITEMS_PATH = CAPTURE_DIR / "battle_items.json"


class BattlePage(ctk.CTkFrame):
    REFRESH_MS = 1000

    def __init__(self, parent):
        super().__init__(parent)

        self.battle_data = None
        self.battle_items = []
        self._refresh_job = None

        self.configure(
            fg_color=("#F5F7FB", "#0B1120"),
        )

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_ui()
        self._refresh()

    def _build_ui(self):
        header = ctk.CTkFrame(
            self,
            corner_radius=18,
            fg_color=("#FFFFFF", "#111827"),
            border_width=1,
            border_color=("#E7ECF4", "#243047"),
        )
        header.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=28,
            pady=(24, 14),
        )

        ctk.CTkLabel(
            header,
            text="Battle",
            font=(
                theme.FONT_FAMILY,
                theme.FONT_PAGE_TITLE,
                "bold",
            ),
            text_color=("#132347", "#F8FAFC"),
        ).pack(
            anchor="w",
            padx=24,
            pady=(20, 4),
        )

        ctk.CTkLabel(
            header,
            text="TikTok LIVE\u306e\u30d0\u30c8\u30eb\u30b9\u30b3\u30a2\u3068\u30d0\u30c8\u30eb\u30a2\u30a4\u30c6\u30e0\u3092\u78ba\u8a8d\u3067\u304d\u307e\u3059",
            font=(theme.FONT_FAMILY, theme.FONT_BODY),
            text_color=("#71809C", "#94A3B8"),
        ).pack(
            anchor="w",
            padx=24,
            pady=(0, 20),
        )

        body = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
        )
        body.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=28,
            pady=(0, 24),
        )

        self.score_card = ctk.CTkFrame(
            body,
            corner_radius=18,
            fg_color=("#FFFFFF", "#111827"),
            border_width=1,
            border_color=("#E7ECF4", "#243047"),
        )
        self.score_card.pack(
            fill="x",
            pady=(0, 14),
        )

        self.score_label = ctk.CTkLabel(
            self.score_card,
            text="",
            font=(theme.FONT_FAMILY, 24, "bold"),
            text_color=("#132347", "#F8FAFC"),
        )
        self.score_label.pack(
            padx=24,
            pady=(20, 4),
        )

        self.timer_label = ctk.CTkLabel(
            self.score_card,
            text="",
            font=(theme.FONT_FAMILY, 15, "bold"),
            text_color=("#64748B", "#94A3B8"),
        )
        self.timer_label.pack(
            padx=24,
            pady=(0, 20),
        )

        self.items_card = ctk.CTkFrame(
            body,
            corner_radius=18,
            fg_color=("#FFFFFF", "#111827"),
            border_width=1,
            border_color=("#E7ECF4", "#243047"),
        )
        self.items_card.pack(
            fill="x",
            pady=(0, 14),
        )

        ctk.CTkLabel(
            self.items_card,
            text="\u30d0\u30c8\u30eb\u30a2\u30a4\u30c6\u30e0\u5c65\u6b74",
            font=(theme.FONT_FAMILY, 18, "bold"),
            text_color=("#132347", "#F8FAFC"),
        ).pack(
            anchor="w",
            padx=24,
            pady=(20, 8),
        )

        self.items_frame = ctk.CTkFrame(
            self.items_card,
            fg_color="transparent",
        )
        self.items_frame.pack(
            fill="x",
            padx=0,
            pady=(0, 12),
        )

    def _load_json(self, path, default):
        if not path.exists():
            return default

        try:
            return json.loads(
                path.read_text(
                    encoding="utf-8",
                )
            )
        except Exception:
            return default

    def _load_data(self):
        battle = self._load_json(
            BATTLE_PATH,
            None,
        )
        items = self._load_json(
            BATTLE_ITEMS_PATH,
            [],
        )

        if not isinstance(battle, dict):
            battle = None

        if not isinstance(items, list):
            items = []

        self.battle_data = battle
        self.battle_items = items

    def _host_first_entries(self, entries, mode):
        """Move the identified host to the left; preserve opponent order."""
        host_id = str((self.battle_data or {}).get("host_user_id") or "").strip()
        ordered = list(entries)
        if not host_id:
            return ordered
        matches = []
        for index, entry in enumerate(ordered):
            if mode == "team":
                ids = {str(user.get("user_id") or "").strip()
                       for user in entry.get("users") or []}
            else:
                ids = {str(entry.get("anchor_id") or entry.get("key") or "").strip()}
            if host_id in ids:
                matches.append(index)
        if len(matches) == 1:
            ordered.insert(0, ordered.pop(matches[0]))
        return ordered

    def _named_score_text(self, entry):
        nickname = str(entry.get("nickname") or "").strip()
        text = score_text(entry)
        return f"{nickname}: {text}" if nickname else text

    def _format_score_text(self):
        data = self.battle_data or {}

        mode = data.get("mode")

        if mode == "individual":
            participants = self._host_first_entries(data.get("participants") or [], "individual")

            if len(participants) >= 2:
                text = "  VS  ".join(
                    self._named_score_text(item)
                    for item in participants
                )

                if data.get("reason") == "timeout_fallback":
                    text += "（推定スコア）"

                return text

        if mode == "team":
            teams = self._host_first_entries(data.get("teams") or [], "team")

            if len(teams) >= 2:
                host_id = str(data.get("host_user_id") or "").strip()
                grouped_battle = len(teams) == 2 and any(
                    len(team.get("users") or []) > 1 for team in teams
                )
                score_texts = []
                for team in teams:
                    text = score_text(team)
                    member_names = [
                        str(user.get("nickname") or "").strip()
                        for user in team.get("users") or []
                    ]
                    member_names = [name for name in member_names if name]
                    if member_names:
                        text = f"{'・'.join(member_names)}: {text}"
                    host_users = [
                        user for user in team.get("users") or []
                        if host_id and str(user.get("user_id") or "").strip() == host_id
                    ]
                    if grouped_battle and len(host_users) == 1:
                        text += f"（{score_text(host_users[0])}）"
                    score_texts.append(text)
                result = "  VS  ".join(score_texts)
                if data.get("reason") == "timeout_fallback":
                    result += "（推定スコア）"
                return result

        return "\u30d0\u30c8\u30eb\u30c7\u30fc\u30bf\u3092\u5f85\u6a5f\u4e2d..."

    def _format_timer_text(self):
        data = self.battle_data or {}

        if not data:
            return ""

        if not bool(data.get("active")):
            return "バトル終了"

        try:
            start_time_ms = int(
                data.get("start_time_ms") or 0
            )
            duration_seconds = int(
                data.get("duration_seconds") or 0
            )
        except Exception:
            return ""

        if start_time_ms <= 0 or duration_seconds <= 0:
            return ""

        end_time = (
            start_time_ms / 1000.0
            + duration_seconds
        )

        remaining = max(
            0,
            int(end_time - time.time() + 0.999),
        )

        minutes, seconds = divmod(
            remaining,
            60,
        )

        return f"残り {minutes}:{seconds:02d}"


    def _get_card_info(self, item):
        event = item.get("event") or {}

        for value in event.values():
            if not isinstance(value, dict):
                continue

            card_info = value.get("cardInfo")

            if isinstance(card_info, dict):
                return card_info

        return {}

    def _get_item_target_id(self, item):
        card_info = self._get_card_info(item)

        target_id = (
            card_info.get("toAnchorIdStr")
            or card_info.get("toAnchorId")
        )

        return str(target_id or "")

    def _get_item_sender(self, item):
        card_info = self._get_card_info(item)

        send_user = card_info.get("sendUser") or {}

        if not isinstance(send_user, dict):
            return ""

        user = send_user.get("user") or {}

        if not isinstance(user, dict):
            return ""

        return str(
            user.get("nickName")
            or user.get("displayId")
            or ""
        )

    def _format_item_name(self, item):
        event = item.get("event") or {}

        for value in event.values():
            if not isinstance(value, dict):
                continue

            display_content = value.get("displayContent") or {}

            if isinstance(display_content, dict):
                pattern = display_content.get("defaultPattern")

                if isinstance(pattern, str) and pattern.strip():
                    marker = " sent 1 "

                    if marker in pattern:
                        return pattern.split(
                            marker,
                            1,
                        )[1].strip()

            card_info = value.get("cardInfo") or {}

            if isinstance(card_info, dict):
                name = card_info.get("cardNameKey")

                if name:
                    return str(name)

        return "\u30d0\u30c8\u30eb\u30a2\u30a4\u30c6\u30e0"

    def _host_team_id(self):
        data = self.battle_data or {}
        host_id = str(
            data.get("host_user_id") or ""
        )

        if not host_id:
            return ""

        for team in data.get("teams") or []:
            for user in team.get("users") or []:
                if str(user.get("user_id") or "") == host_id:
                    return str(
                        team.get("team_id") or ""
                    )

        return ""

    def _is_item_for_host(self, item):
        data = self.battle_data or {}

        host_id = str(
            data.get("host_user_id") or ""
        )
        target_id = self._get_item_target_id(item)

        if not host_id or not target_id:
            return False

        if data.get("mode") == "individual":
            return target_id == host_id

        if data.get("mode") == "team":
            host_team_id = self._host_team_id()

            if not host_team_id:
                return False

            for team in data.get("teams") or []:
                team_id = str(
                    team.get("team_id") or ""
                )

                for user in team.get("users") or []:
                    if (
                        str(user.get("user_id") or "")
                        == target_id
                    ):
                        return team_id == host_team_id

        return False

    def _visible_items(self):
        data = self.battle_data or {}

        battle_id = int(
            data.get("battle_id") or 0
        )

        if not battle_id:
            return []

        result = []

        for item in self.battle_items:
            if int(item.get("battle_id") or 0) != battle_id:
                continue

            if not self._get_item_sender(item):
                continue

            if not self._is_item_for_host(item):
                continue

            result.append(item)

        return result[-20:]

    def _render_items(self):
        for child in self.items_frame.winfo_children():
            child.destroy()

        items = self._visible_items()

        if not items:
            ctk.CTkLabel(
                self.items_frame,
                text="\u3053\u306e\u30d0\u30c8\u30eb\u3067\u81ea\u5206\u5074\u306b\u4f7f\u308f\u308c\u305f\u30a2\u30a4\u30c6\u30e0\u306f\u307e\u3060\u3042\u308a\u307e\u305b\u3093",
                font=(theme.FONT_FAMILY, 13),
                text_color=("#71809C", "#94A3B8"),
            ).pack(
                anchor="w",
                padx=24,
                pady=(4, 12),
            )
            return

        for item in reversed(items):
            row = ctk.CTkFrame(
                self.items_frame,
                corner_radius=12,
                fg_color=("#F8FAFD", "#182235"),
            )
            row.pack(
                fill="x",
                padx=24,
                pady=(4, 8),
            )

            ctk.CTkLabel(
                row,
                text=self._format_item_name(item),
                font=(theme.FONT_FAMILY, 14, "bold"),
                text_color=("#132347", "#F8FAFC"),
            ).pack(
                anchor="w",
                padx=16,
                pady=(12, 2),
            )

            sender = self._get_item_sender(item)

            ctk.CTkLabel(
                row,
                text=f"\u9001\u4fe1\u8005: {sender}",
                font=(theme.FONT_FAMILY, 12),
                text_color=("#71809C", "#94A3B8"),
            ).pack(
                anchor="w",
                padx=16,
                pady=(0, 12),
            )

    def _refresh(self):
        self._load_data()

        self.score_label.configure(
            text=self._format_score_text(),
        )

        self.timer_label.configure(
            text=self._format_timer_text(),
        )

        self._render_items()

        self._refresh_job = self.after(
            self.REFRESH_MS,
            self._refresh,
        )

    def destroy(self):
        if self._refresh_job is not None:
            try:
                self.after_cancel(
                    self._refresh_job,
                )
            except Exception:
                pass

        super().destroy()
import json
import os
import re
import threading
import traceback
from typing import Optional

import customtkinter as ctk

from core.ai_client import AIClient
from core.history import HistoryDB

import time

from core.video_analyzer import extract_frames

class AIPage(ctk.CTkFrame):
    """手動AI分析ページ完成版。"""

    IMAGE_PATH = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "AI-TikTok-LIVE-Analyzer",
        "images",
        "current.png",
    )

    DEFAULT_PROMPT = """
あなたはTikTok LIVE配信の改善アドバイザーです。
添付画像から、配信画面の見やすさ・構図・明るさ・情報量・視聴者への伝わりやすさを分析してください。

必ず次の形式で日本語で回答してください。

総合スコア: 0〜100点

良い点:
・

改善点:
・

すぐできる改善:
・

人物が写っていない場合でも、画面構成や配信環境を中心に評価してください。
画像から分からないことは断定しないでください。
""".strip()

    def __init__(self, parent, obs):
        super().__init__(parent)

        self.obs = obs
        self.ai = AIClient()
        self.history = HistoryDB()

        self._destroying = False
        self._analysis_running = False
        self._worker: Optional[threading.Thread] = None

        self._build_ui()
        self._load_prompt()

    def _build_ui(self):
        ctk.CTkLabel(
            self,
            text="🤖 AI分析",
            font=("Yu Gothic UI", 24, "bold"),
        ).pack(pady=(20, 10))

        self.status_label = ctk.CTkLabel(
            self,
            text="待機中",
            font=("Yu Gothic UI", 14, "bold"),
        )
        self.status_label.pack(pady=(0, 8))

        self.result = ctk.CTkTextbox(self, width=760, height=280)
        self.result.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        self.result.insert(
            "1.0",
            "「AI分析開始」を押すと、OBSの現在シーンを分析します。",
        )
        self.result.configure(state="disabled")

        self.analysis_button = ctk.CTkButton(
            self,
            text="▶ AI分析開始",
            width=220,
            command=self.start_analysis_thread,
        )
        self.analysis_button.pack(pady=(0, 14))

        ctk.CTkLabel(
            self,
            text="分析プロンプト",
            font=("Yu Gothic UI", 15, "bold"),
        ).pack(anchor="w", padx=20)

        self.prompt = ctk.CTkTextbox(self, width=760, height=150)
        self.prompt.pack(fill="x", padx=20, pady=(6, 10))

        self.save_button = ctk.CTkButton(
            self,
            text="💾 プロンプト保存",
            width=220,
            command=self.save_prompt,
        )
        self.save_button.pack(pady=(0, 20))

    def _load_prompt(self):
        prompt_text = self.DEFAULT_PROMPT

        try:
            settings = Settings.load()

            saved_prompt = settings.get("ai_prompt")

            if (
                isinstance(saved_prompt, str)
                and saved_prompt.strip()
            ):
                prompt_text = saved_prompt.strip()

        except Exception as exc:
            print(
                "プロンプト読込エラー:",
                repr(exc),
            )

        self.prompt.delete("1.0", "end")
        self.prompt.insert("1.0", prompt_text)

    def save_prompt(self):
        prompt_text = self.prompt.get(
            "1.0",
            "end",
        ).strip()

        if not prompt_text:
            self.status_label.configure(
                text="❌ プロンプトが空です"
            )
            return

        try:
            settings = Settings.load()

            settings["ai_prompt"] = prompt_text

            Settings.save(settings)

            self.status_label.configure(
                text="✅ プロンプトを保存しました"
            )

        except Exception as exc:
            self.status_label.configure(
                text=(
                    f"❌ 保存エラー: "
                    f"{type(exc).__name__}: {exc}"
                )
            )

    def start_analysis_thread(self):
        if self._analysis_running:
            self.status_label.configure(text="⚠️ 現在分析中です")
            return

        prompt_text = self.prompt.get("1.0", "end").strip()

        if not prompt_text:
            self.status_label.configure(text="❌ プロンプトが空です")
            return

        try:
            if not self.obs.is_connected():
                self.status_label.configure(text="❌ OBSに接続されていません")
                self._set_result(
                    "OBSを起動し、WebSocket接続を確認してください。"
                )
                return
        except Exception:
            self.status_label.configure(text="❌ OBS接続状態を確認できません")
            return

        self._analysis_running = True
        self.analysis_button.configure(state="disabled", text="分析中...")
        self.save_button.configure(state="disabled")
        self.status_label.configure(text="📸 スクリーンショット取得中...")
        self._set_result("OBSの現在シーンを取得しています...")

        self._worker = threading.Thread(
            target=self._analysis_worker,
            args=(prompt_text,),
            name="ManualAIAnalysisThread",
            daemon=True,
        )
        self._worker.start()

    def _analysis_worker(self, prompt_text: str):
        try:
            # 保存前の最新リプレイを記録
            previous_replay_path = self.obs.get_last_replay_path()

            # Replay Buffer確認
            if not self.obs.is_replay_buffer_active():
                raise RuntimeError(
                    "OBSのReplay Bufferが開始されていません。"
                )

            self._safe_after(
                lambda: self.status_label.configure(
                    text="🎬 Replay Buffer保存中..."
                )
            )

            # Replay Buffer保存
            if not self.obs.save_replay_buffer():
                raise RuntimeError(
                    "Replay Bufferの保存に失敗しました。"
                )

            # OBS側で保存完了するまで少し待つ
            replay_path = None

            for _ in range(20):
                time.sleep(0.25)

                candidate = self.obs.get_last_replay_path()

                if (
                    candidate
                    and candidate != previous_replay_path
                    and os.path.exists(candidate)
                ):
                    replay_path = candidate
                    break

            if not replay_path:
                raise RuntimeError(
                    "保存したReplay動画のパスを取得できませんでした。"
                )

            print(f"[AIPage] replay_path={replay_path}")

            self._safe_after(
                lambda: self.status_label.configure(
                    text="🎞️ 動画からフレーム抽出中..."
                )
            )

            frames = extract_frames(
                replay_path,
                interval_seconds=5,
                max_frames=12,
            )

            if not frames:
                raise RuntimeError(
                    "Replay動画からフレームを抽出できませんでした。"
                )

            print(f"[AIPage] extracted_frames={len(frames)}")

            for frame_path in frames:
                print(f"[AIPage] frame={frame_path}")
                # 今回は抽出した最後のフレームをAI分析に使用

            self._safe_after(self._show_analyzing)

            answer = self.ai.analyze_images(
                frames,
                prompt_text,
            )

            if not answer or not str(answer).strip():
                raise RuntimeError(
                    "AIから分析結果が返されませんでした。"
                )

            answer = str(answer).strip()
            score = self._extract_score(answer)

            self._save_history(
                score=score,
                prompt=prompt_text,
                answer=answer,
                image_path=frames[-1],
            )

            self._safe_after(
                lambda: self._show_success(
                    answer,
                    score,
                )
            )
        
        except Exception as exc:
            traceback.print_exc()
            error_text = f"{type(exc).__name__}: {exc}"
            self._safe_after(lambda text=error_text: self._show_error(text))

    def _show_analyzing(self):
        if not self._page_is_alive():
            return
        self.status_label.configure(text="🤖 AI分析中...")
        self._set_result(
            "AIが配信画面を分析しています。\n完了までしばらくお待ちください。"
        )

    def _show_success(self, answer: str, score: Optional[int]):
        if not self._page_is_alive():
            return

        if score is None:
            self.status_label.configure(text="✅ AI分析完了")
        else:
            self.status_label.configure(text=f"✅ AI分析完了（{score}点）")

        self._set_result(answer)
        self._finish_analysis()

    def _show_error(self, error_text: str):
        if not self._page_is_alive():
            return

        self.status_label.configure(text="❌ AI分析エラー")
        self._set_result(
            "分析中にエラーが発生しました。\n\n" + error_text
        )
        self._finish_analysis()

    def _finish_analysis(self):
        self._analysis_running = False
        if not self._page_is_alive():
            return

        self.analysis_button.configure(state="normal", text="▶ AI分析開始")
        self.save_button.configure(state="normal")

    def _save_history(
        self,
        score: Optional[int],
        prompt: str,
        answer: str,
        image_path: Optional[str] = None,
    ):
        self.history.save(
            score=score,
            prompt=prompt,
            result=answer,
            image_path=image_path,
        )
        save = getattr(self.history, "save", None)
        if not callable(save):
            raise AttributeError("HistoryDBにsaveメソッドがありません。")

        attempts = [
            lambda: save(
                score=score,
                prompt=prompt,
                result=answer,
                image_path=image_path,
            ),
            lambda: save(
                score=score,
                prompt=prompt,
                answer=answer,
                image_path=image_path,
            ),
            lambda: save(score=score, prompt=prompt, result=answer),
            lambda: save(score, prompt, answer),
        ]

        last_error = None
        for attempt in attempts:
            try:
                attempt()
                return
            except TypeError as exc:
                last_error = exc

        if last_error is not None:
            raise last_error

    @staticmethod
    def _extract_score(answer: str) -> Optional[int]:
        patterns = [
            r"総合スコア\s*[:：]?\s*(\d{1,3})\s*点",
            r"スコア\s*[:：]?\s*(\d{1,3})\s*点",
            r"(\d{1,3})\s*/\s*100",
            r"(\d{1,3})\s*点",
        ]

        for pattern in patterns:
            match = re.search(pattern, answer)
            if not match:
                continue

            score = int(match.group(1))
            return max(0, min(100, score))

        return None

    def _set_result(self, text: str):
        if not self._page_is_alive():
            return

        self.result.configure(state="normal")
        self.result.delete("1.0", "end")
        self.result.insert("1.0", text)
        self.result.configure(state="disabled")

    def _safe_after(self, callback):
        if self._destroying:
            return

        try:
            self.after(
                0,
                lambda: callback() if self._page_is_alive() else None,
            )
        except Exception:
            pass

    def _page_is_alive(self) -> bool:
        if self._destroying:
            return False

        try:
            return bool(self.winfo_exists())
        except Exception:
            return False

    def destroy(self):
        if self._destroying:
            return

        self._destroying = True
        super().destroy()
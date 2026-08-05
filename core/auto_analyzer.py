import json
import os
import re
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Callable, Optional
from PIL import Image
from core.ai_client import AIClient
from core.history import HistoryDB


class AutoAnalyzer:
    """
    OBSの現在シーンを一定間隔で画像保存し、AI分析して履歴に保存する。

    callback(event, data) のevent:
        "status" : 状態メッセージ
        "result" : {"score": int | None, "answer": str, "image_path": str}
        "error"  : エラーメッセージ
    """

    DEFAULT_INTERVAL = 30
    DEFAULT_IMAGE_PATH = os.path.join(
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

    def __init__(
        self,
        obs,
        callback: Optional[Callable[[str, Any], None]] = None,
        interval: int = DEFAULT_INTERVAL,
        image_path: str = DEFAULT_IMAGE_PATH,
    ):
        self.obs = obs
        self.callback = callback
        self.interval = max(5, int(interval))
        self.image_path = image_path

        self.ai = AIClient()
        self.history = HistoryDB()

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    # ==================================================
    # Public API
    # ==================================================

    def start(self) -> bool:
        """自動分析を開始する。既に動作中ならFalse。"""
        with self._lock:
            if self._running:
                return False

            self._running = True
            self._stop_event.clear()

            self._thread = threading.Thread(
                target=self._loop,
                name="AutoAnalyzerThread",
                daemon=True,
            )
            self._thread.start()

        print("AI分析開始")
        return True

    def stop(self) -> bool:
        """自動分析を停止する。"""
        with self._lock:
            was_running = self._running
            self._running = False
            self._stop_event.set()

        # Tkinter終了時に固まらないよう短時間だけ待つ
        thread = self._thread
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=1.0)

        self._thread = None
        return was_running

    def is_running(self) -> bool:
        return self._running and not self._stop_event.is_set()

    def analyze_once(self) -> Optional[dict]:
        """
        1回だけ分析する。
        自動分析スレッド以外から呼び出しても使用可能。
        """
        return self._analyze_once()

    # ==================================================
    # Main loop
    # ==================================================

    def _loop(self):
        try:
            # 開始直後に1回分析
            while self.is_running():
                started_at = time.monotonic()

                try:
                    self._analyze_once()
                except Exception as exc:
                    traceback.print_exc()
                    self._emit(
                        "error",
                        f"{type(exc).__name__}: {exc}",
                    )

                if not self.is_running():
                    break

                elapsed = time.monotonic() - started_at
                wait_seconds = max(0.0, self.interval - elapsed)

                # stop()されたら即座に待機を終了
                if self._stop_event.wait(wait_seconds):
                    break

        finally:
            with self._lock:
                self._running = False

    # ==================================================
    # Analysis
    # ==================================================

    def _analyze_once(self) -> Optional[dict]:
        if not self._obs_connected():
            raise ConnectionError(
                "OBSに接続されていません。OBSとWebSocket設定を確認してください。"
            )

        scene_name = self.obs.get_current_scene()
        if not scene_name:
            raise RuntimeError("OBSの現在シーンを取得できませんでした。")

        os.makedirs(
            os.path.dirname(self.image_path) or ".",
            exist_ok=True,
        )

        self._emit("status", "OBS画面を取得しています...")

        screenshot_result = self.obs.save_screenshot(
            scene_name,
            self.image_path,
        )

        # 実装によってはFalseを返す
        if screenshot_result is False:
            raise RuntimeError("OBS画面の保存に失敗しました。")

        if not os.path.exists(self.image_path):
            raise FileNotFoundError(
                f"スクリーンショットが見つかりません: {self.image_path}"
            )

        if os.path.getsize(self.image_path) <= 0:
            raise RuntimeError("保存されたスクリーンショットが空です。")

        # スクリーンショットの書き込み完了を待つ
        for _ in range(10):
            try:
                with Image.open(self.image_path) as img:
                    img.verify()
                break
            except (OSError, IOError):
                time.sleep(0.2)
        else:
            raise RuntimeError(
                "スクリーンショットの読み込みに失敗しました。"
            )

        prompt = self._load_prompt()

        self._emit("status", "AI分析中...")

        answer = self.ai.analyze_image(
            self.image_path,
            prompt,
        )

        if not answer or not str(answer).strip():
            raise RuntimeError("AIから分析結果が返されませんでした。")

        answer = str(answer).strip()
        print("AI応答取得成功")

        score = self._extract_score(answer)

        self._save_history(
            score=score,
            prompt=prompt,
            answer=answer,
            image_path=self.image_path,
        )
        print("履歴保存成功")

        result = {
            "score": score,
            "answer": answer,
            "image_path": self.image_path,
            "scene": scene_name,
            "analyzed_at": datetime.now().isoformat(
                timespec="seconds"
            ),
        }

        self._emit("result", result)
        return result

    # ==================================================
    # Helpers
    # ==================================================

    def _obs_connected(self) -> bool:
        try:
            return bool(self.obs.is_connected())
        except Exception:
            return False

    def _load_prompt(self) -> str:
        """
        settings.json内のpromptを優先。
        読み込めない場合は標準プロンプトを使用。
        """
        candidates = [
            "settings.json",
            os.path.join("config", "settings.json"),
        ]

        for path in candidates:
            if not os.path.exists(path):
                continue

            try:
                with open(path, "r", encoding="utf-8") as file:
                    settings = json.load(file)

                for key in (
                    "analysis_prompt",
                    "prompt",
                    "ai_prompt",
                ):
                    value = settings.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()

                ai_settings = settings.get("ai")
                if isinstance(ai_settings, dict):
                    value = ai_settings.get("prompt")
                    if isinstance(value, str) and value.strip():
                        return value.strip()

            except Exception as exc:
                print(
                    f"設定ファイル読込エラー ({path}):",
                    repr(exc),
                )

        return self.DEFAULT_PROMPT

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

    def _save_history(
        self,
        score: Optional[int],
        prompt: str,
        answer: str,
        image_path: str,
    ):
        """
        既存HistoryDBのsave形式に対応。
        一般的な複数の引数形式を順番に試す。
        """
        save = getattr(self.history, "save", None)
        if not callable(save):
            raise AttributeError(
                "HistoryDBにsaveメソッドがありません。"
            )

        attempts = [
            lambda: save(score, prompt, answer),
            lambda: save(prompt, answer, score),
            lambda: save(
                score=score,
                prompt=prompt,
                answer=answer,
            ),
            lambda: save(
                score=score,
                prompt=prompt,
                result=answer,
            ),
            lambda: save(
                score=score,
                prompt=prompt,
                answer=answer,
                image_path=image_path,
            ),
        ]

        last_type_error = None

        for attempt in attempts:
            try:
                attempt()
                return
            except TypeError as exc:
                last_type_error = exc

        if last_type_error is not None:
            raise last_type_error

    def _emit(self, event: str, data: Any):
        if self.callback is None:
            return

        try:
            self.callback(event, data)
        except Exception:
            # コールバック側の不具合で分析スレッドを停止させない
            traceback.print_exc()
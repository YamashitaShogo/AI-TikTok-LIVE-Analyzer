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
from core.brightness_analyzer import BrightnessAnalyzer
from core.information_analyzer import InformationAnalyzer
from core.hybrid_score_calculator import HybridScoreCalculator
from core.hybrid_analysis_formatter import HybridAnalysisFormatter
from core.simplified_hybrid_prompt import SIMPLIFIED_HYBRID_PROMPT
from core.history import HistoryDB
from core.settings import Settings


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
あなたはTikTok LIVE配信画面を評価する分析AIです。
主観だけで採点せず、以下の固定基準に従って評価してください。

【採点基準：合計100点】

1. 構図：25点
- 23〜25点：主要要素の位置・余白・バランスが非常に良い
- 18〜22点：軽微な位置ずれや余白の問題がある
- 12〜17点：主要要素の偏りや見切れなど明確な問題がある
- 0〜11点：重要要素が大きく見切れるなど重大な問題がある

2. 明るさ：20点
- 18〜20点：適切な明るさで重要部分が明瞭
- 14〜17点：少し暗い、または少し明るすぎる
- 8〜13点：重要部分が見づらい
- 0〜7点：極端な暗さ・白飛びなど重大な問題がある

3. 視認性：20点
- 18〜20点：文字・人物・主要要素が明確に認識できる
- 14〜17点：一部に小ささや重なりがある
- 8〜13点：複数の要素が見づらい
- 0〜7点：重要情報の認識が困難

4. 情報量：15点
- 14〜15点：必要な情報が整理され、過不足が少ない
- 10〜13点：少し多い、または少ない
- 6〜9点：情報過多または情報不足が目立つ
- 0〜5点：画面理解を妨げるほど問題がある

5. 伝わりやすさ：20点
- 18〜20点：何を見せたい配信画面かすぐ理解できる
- 14〜17点：概ね理解できるが一部不明瞭
- 8〜13点：意図が伝わりにくい
- 0〜7点：画面の目的を判断するのが難しい

【重要ルール】
- 総合スコアは必ず5項目の点数を足した値にしてください。
- 総合スコアを感覚で別途決めてはいけません。
- 画像から確認できる事実だけを評価してください。
- 視聴者数・コメント数・ギフト数など、画像から分からない情報は推測しないでください。
- 人物が写っていないこと自体を減点理由にしないでください。
- 同じ状態の画像には可能な限り同じ採点基準を適用してください。
- 軽微な問題だけで大幅に減点しないでください。
- 改善点には判断根拠を具体的に書いてください。

必ず次の形式で日本語で回答してください。

総合スコア: XX点

内訳:
構図: XX/25点
明るさ: XX/20点
視認性: XX/20点
情報量: XX/15点
伝わりやすさ: XX/20点

良い点:
・

改善点:
・問題:
・根拠:
・重要度: 高 / 中 / 低

すぐできる改善:
・

総合スコアと内訳の合計が必ず一致していることを確認してから回答してください。
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

        prompt = SIMPLIFIED_HYBRID_PROMPT

        self._emit("status", "AI分析中...")

        brightness = BrightnessAnalyzer.analyze(
            self.image_path
        )

        information = InformationAnalyzer.analyze(
            self.image_path
        )

        raw_answer = self.ai.analyze_image(
            self.image_path,
            prompt,
        )

        if not raw_answer or not str(raw_answer).strip():
            raise RuntimeError(
                "AIから分析結果が返されませんでした。"
            )

        raw_answer = str(raw_answer).strip()

        match = re.search(
            r"\{.*\}",
            raw_answer,
            flags=re.DOTALL,
        )

        if not match:
            raise RuntimeError(
                "AI分析結果のJSONを取得できませんでした。"
            )

        ai_data = json.loads(
            match.group(0)
        )

        issue_names = (
            "subject_boundary_issue",
            "content_obstruction_issue",
            "layout_imbalance",
            "readability_issue",
            "subject_separation_issue",
            "focus_confusion",
        )

        issues = {
            name: ai_data.get(name) is True
            for name in issue_names
        }

        scores = HybridScoreCalculator.calculate(
            issues,
            brightness_score=brightness["score"],
            information_score=information["score"],
        )

        score = scores["total"]

        answer = HybridAnalysisFormatter.format(
            issues,
            brightness_score=brightness["score"],
            information_score=information["score"],
        )

        print(
            "[Hybrid Analysis]",
            "score=",
            score,
            "issues=",
            [
                name
                for name, active in issues.items()
                if active
            ],
        )

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
        AppDataのsettings.jsonに保存された
        AIプロンプトを優先する。
        """

        try:
            settings = Settings.load()

            for key in (
                "analysis_prompt",
                "prompt",
                "ai_prompt",
            ):
                value = settings.get(key)

                if (
                    isinstance(value, str)
                    and value.strip()
                ):
                    return value.strip()

            ai_settings = settings.get("ai")

            if isinstance(ai_settings, dict):
                value = ai_settings.get("prompt")

                if (
                    isinstance(value, str)
                    and value.strip()
                ):
                    return value.strip()

        except Exception:
            pass

        return self.DEFAULT_PROMPT
    @staticmethod
    def _extract_score(answer: str) -> Optional[int]:
        """
        AI回答の内訳から総合スコアを計算する。
        5項目すべて取得できた場合は、AIが書いた総合点ではなく
        Livemetry側で合計してスコアを確定する。
        """

        item_patterns = {
            "構図": (r"構図\s*[:：]\s*(\d{1,2})\s*/\s*25\s*点?", 25),
            "明るさ": (r"明るさ\s*[:：]\s*(\d{1,2})\s*/\s*20\s*点?", 20),
            "視認性": (r"視認性\s*[:：]\s*(\d{1,2})\s*/\s*20\s*点?", 20),
            "情報量": (r"情報量\s*[:：]\s*(\d{1,2})\s*/\s*15\s*点?", 15),
            "伝わりやすさ": (
                r"伝わりやすさ\s*[:：]\s*(\d{1,2})\s*/\s*20\s*点?",
                20,
            ),
        }

        scores = {}

        for name, (pattern, maximum) in item_patterns.items():
            match = re.search(pattern, answer)

            if not match:
                scores = {}
                break

            value = int(match.group(1))

            if value < 0 or value > maximum:
                scores = {}
                break

            scores[name] = value

        if len(scores) == 5:
            return sum(scores.values())

        # 内訳を取得できなかった場合のみ総合スコアを利用
        fallback_patterns = [
            r"総合スコア\s*[:：]?\s*(\d{1,3})\s*点",
            r"(\d{1,3})\s*/\s*100",
        ]

        for pattern in fallback_patterns:
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
            lambda: save(
                score=score,
                prompt=prompt,
                result=answer,
            ),
            lambda: save(
                score,
                prompt,
                answer,
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
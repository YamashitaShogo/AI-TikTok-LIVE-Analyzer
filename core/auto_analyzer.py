import json
import os
import re
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
from PIL import Image
from core.ai_client import AIClient
from core.audio_capture import capture_system_audio
from core.brightness_analyzer import BrightnessAnalyzer
from core.information_analyzer import InformationAnalyzer
from core.hybrid_score_calculator import HybridScoreCalculator
from core.hybrid_analysis_formatter import HybridAnalysisFormatter
from core.simplified_hybrid_prompt import SIMPLIFIED_HYBRID_PROMPT
from core.history import HistoryDB
from core.settings import Settings


class AutoAnalyzer:
    """
    TikTok Viewerの最新映像とコメントを一定間隔でAI分析して履歴に保存する。

    callback(event, data) のevent:
        "status" : 状態メッセージ
        "result" : {"score": int | None, "answer": str, "image_path": str}
        "error"  : エラーメッセージ
    """

    DEFAULT_INTERVAL = 30

    VIEWER_CAPTURE_DIR = Path(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    ) / "AI-TikTok-LIVE-Analyzer" / "capture"

    VIEWER_IMAGE_PATH = VIEWER_CAPTURE_DIR / "latest.jpg"
    VIEWER_PAYLOAD_PATH = VIEWER_CAPTURE_DIR / "analysis_payload.json"

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
        callback: Optional[Callable[[str, Any], None]] = None,
        interval: int = DEFAULT_INTERVAL,
    ):
        self.callback = callback
        self.interval = max(5, int(interval))

        self.ai = AIClient()
        self.history = HistoryDB()

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # Prevent manual and automatic analyses from running
        # at the same time.
        self._analysis_lock = threading.Lock()

        # Temporal information-density state.
        self._high_density_streak = 0
        self._very_high_density_streak = 0

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

            self._high_density_streak = 0
            self._very_high_density_streak = 0

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
        if not self._analysis_lock.acquire(
            blocking=False
        ):
            self._emit(
                "status",
                "\u5206\u6790\u51e6\u7406\u304c"
                "\u5b9f\u884c\u4e2d\u3067\u3059\u3002"
            )
            return None

        try:
            return self._analyze_once_impl()
        finally:
            self._analysis_lock.release()

    def _analyze_once_impl(self) -> Optional[dict]:
        """
        TikTok Viewerが保存した最新フレームと直近コメントを使って分析する。
        OBS接続は映像分析には必須としない。
        """
        self.VIEWER_CAPTURE_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        image_path = self.VIEWER_IMAGE_PATH
        payload_path = self.VIEWER_PAYLOAD_PATH

        self._emit(
            "status",
            "TikTok LIVE映像を取得しています...",
        )

        if not image_path.exists():
            raise FileNotFoundError(
                "TikTok Viewerの映像がまだありません。"
                f"\n{image_path}"
            )

        if image_path.stat().st_size <= 0:
            raise RuntimeError(
                "TikTok Viewerの最新映像が空です。"
            )

        # 書き込み途中の画像を読まないように確認する
        for _ in range(10):
            try:
                with Image.open(image_path) as img:
                    img.verify()
                break
            except (OSError, IOError):
                time.sleep(0.2)
        else:
            raise RuntimeError(
                "TikTok Viewerの最新映像を読み込めませんでした。"
            )

        comments = []

        if payload_path.exists():
            try:
                with payload_path.open(
                    "r",
                    encoding="utf-8",
                ) as file:
                    payload = json.load(file)

                if isinstance(payload, dict):
                    raw_comments = payload.get(
                        "comments",
                        [],
                    )

                    if isinstance(raw_comments, list):
                        for item in raw_comments:
                            if not isinstance(item, dict):
                                continue

                            username = str(
                                item.get("username", "")
                            ).strip()

                            comment = str(
                                item.get("comment", "")
                            ).strip()

                            if not comment:
                                continue

                            comments.append(
                                {
                                    "username": username,
                                    "comment": comment,
                                }
                            )

            except (
                OSError,
                json.JSONDecodeError,
            ):
                traceback.print_exc()

        # Viewerから取った映像は既にvideo要素そのものなので、
        # 従来のOBS用固定クロップは行わない。
        analysis_image_path = str(image_path)

        comment_categories = (
            self._classify_comment_categories(comments)
            if comments
            else {}
        )

        prompt = SIMPLIFIED_HYBRID_PROMPT

        if comments:
            comment_lines = []

            for item in comments[-30:]:
                username = (
                    item["username"]
                    or "ユーザー名不明"
                )

                comment_lines.append(
                    f"・{username}: {item['comment']}"
                )

            prompt = (
                prompt
                + "\n\n"
                + "【直近30秒の視聴者コメント】\n"
                + f"コメント件数: {len(comments)}件\n"
                + "コメント分類: "
                + (
                    " / ".join(
                        f"{name}:{count}件"
                        for name, count in comment_categories.items()
                        if count > 0
                    )
                    or "分類なし"
                )
                + "\n"
                + "\n".join(comment_lines)
                + "\n\n"
                + "【コメント利用ルール】\n"
                + "・上記コメントは実際に取得された視聴者コメントです。\n"
                + "・コメント本文から確認できる反応だけを扱ってください。\n"
                + "・映像に写っていない事実をコメントだけから断定しないでください。\n"
                + "・コメント内容は画面構図・明るさ・視認性などの"
                  "issue判定や画面スコアには影響させないでください。\n"
                + "・visual_observation と priority_action は"
                  "映像についてだけ記述してください。\n"
                + "・コメントが1件以上ある場合、main_reasonを必ず次の形式にしてください。\n"
                + "  映像についての分析理由"
                  "[[COMMENT_TREND]]"
                  "コメント全体から読み取れる話題・反応"
                  "[[COMMENT_ACTION]]"
                  "配信者が次に拾うとよい話題や返し方"
                  "[[NEXT_BEST_ACTION]]"
                  "今この瞬間に最優先で実行するとよい一手\n"
                + "・[[COMMENT_TREND]]、[[COMMENT_ACTION]]、"
                  "[[NEXT_BEST_ACTION]] は角括弧を含めて完全一致で出力し、"
                  "表記を変更しないでください。\n"
                + "・COMMENT_TRENDはコメントの内容を要約し、"
                  "見えていない視聴者心理を断定しないでください。\n"
                + "・コメント件数は上に明示された実数をそのまま扱ってください。"
                  "3件以上ある場合は「コメント数が少ない」と表現しないでください。\n"
                + "・3件以上あっても共通話題が見つからない場合は、"
                  "「話題が分散しており、傾向判断は限定的です」としてください。\n"
                + "・1〜2件しかない場合だけ、"
                  "「コメント数が少なく、傾向判断は限定的です」と表現できます。\n"
                + "・コメントに明記されていないジャンルや状況を推測しないでください。"
                  "例えば「戦う」という語だけからゲーム配信と断定してはいけません。\n"
                + "・ゲーム、恋愛、課金、ギフト、イベント等の分類は、"
                  "コメント本文にそれを裏付ける明示的な語がある場合だけ使ってください。\n"
                + "・COMMENT_ACTIONは1文で、実際のコメントに書かれている"
                  "語句や話題を根拠にした『口頭での返答・質問』だけを書いてください。\n"
                + "・COMMENT_ACTIONでは、スマホ・商品・物体を動かす、指で示す、"
                  "カメラへ近づける、画面を見せる等の物理動作を提案しないでください。\n"
                + "・NEXT_BEST_ACTIONは1文だけにし、コメントが1件以上ある場合は"
                  "必ず視聴者への『発話』だけを提案してください。\n"
                + "・コメントがある場合、NEXT_BEST_ACTIONにはカメラ位置、構図、照明、"
                  "マイク位置、スマホ操作、物体の移動などの画面改善・物理動作を"
                  "含めないでください。画面改善はpriority_actionだけに書いてください。\n"
                + "・NEXT_BEST_ACTIONはCOMMENT_ACTIONをさらに短くした"
                  "『今すぐ口に出す一言・質問』にしてください。\n"
                + "・『見どころはここです』『今のポイントは〜』のように、"
                  "コメント本文に根拠のない内容を新しく足さないでください。\n"
                + "・バトル、TAP、初見などがコメントに明示されている場合は、"
                  "その語をそのまま活かした短い返答を優先してください。\n"
                + "・視聴者コメントに『できない』『持っていけない』などの制約が"
                  "書かれている場合、その制約に反する提案をしないでください。\n"
                + "・NEXT_BEST_ACTIONで新しい事実や新しい問題を作らず、"
                  "実際のコメントに根拠がある内容だけを使ってください。"
            )

        self._emit(
            "status",
            "AI分析中...",
        )

        brightness = BrightnessAnalyzer.analyze(
            analysis_image_path
        )

        information = InformationAnalyzer.analyze(
            analysis_image_path
        )

        no_stream_visual = (
            float(brightness.get("mean", 0)) <= 35
            and float(
                brightness.get(
                    "dark_ratio",
                    0,
                )
            ) >= 99.5
            and int(
                information.get(
                    "element_count",
                    0,
                )
            ) == 0
        )

        if no_stream_visual:
            self._high_density_streak = 0
            self._very_high_density_streak = 0

            message = (
                "配信映像を検出できなかったため、"
                "今回の分析をスキップしました。"
            )

            self._emit(
                "status",
                message,
            )

            return {
                "skipped": True,
                "reason": "no_stream_visual",
                "score": None,
                "answer": message,
                "image_path": str(image_path),
                "analysis_image_path": analysis_image_path,
                "scene": "TikTok Viewer",
                "comments": comments,
                "analyzed_at": datetime.now().isoformat(
                    timespec="seconds"
                ),
            }

        element_count = int(
            information.get(
                "element_count",
                0,
            )
        )

        if element_count >= 180:
            self._high_density_streak += 1
        else:
            self._high_density_streak = 0

        if element_count >= 250:
            self._very_high_density_streak += 1
        else:
            self._very_high_density_streak = 0

        single_frame_score = information["score"]

        if self._very_high_density_streak >= 2:
            temporal_information_score = 11
        elif self._high_density_streak >= 2:
            temporal_information_score = 13
        else:
            temporal_information_score = 15

        information["single_frame_score"] = (
            single_frame_score
        )
        information["score"] = (
            temporal_information_score
        )
        information["high_density_streak"] = (
            self._high_density_streak
        )
        information["very_high_density_streak"] = (
            self._very_high_density_streak
        )

        audio_transcript = ""

        try:
            audio_path = capture_system_audio(
                seconds=10,
            )

            audio_transcript = (
                self.ai.transcribe_audio(
                    audio_path
                )
            )

        except Exception as exc:
            print(
                f"[AUTO ANALYZER AUDIO] "
                f"{type(exc).__name__}: {exc}"
            )

            try:
                import os
                import traceback

                log_dir = os.path.join(
                    os.getenv("LOCALAPPDATA", ""),
                    "AI-TikTok-LIVE-Analyzer",
                    "logs",
                )
                os.makedirs(log_dir, exist_ok=True)

                log_path = os.path.join(
                    log_dir,
                    "audio_error.log",
                )

                with open(
                    log_path,
                    "a",
                    encoding="utf-8",
                ) as log_file:
                    log_file.write(
                        f"{type(exc).__name__}: {exc}\n"
                    )
                    log_file.write(
                        traceback.format_exc()
                    )
                    log_file.write("\n")
            except Exception:
                pass

        if audio_transcript:
            prompt = (
                prompt
                + "\n\n"
                + "\u3010\u76f4\u8fd110\u79d2\u306e\u914d\u4fe1\u97f3\u58f0"
                  "\uff08\u6587\u5b57\u8d77\u3053\u3057\uff09\u3011\n"
                + audio_transcript
                + "\n\n"
                + "\u3010\u97f3\u58f0\u5229\u7528\u30eb\u30fc\u30eb\u3011\n"
                + "\u30fb\u4e0a\u8a18\u306f\u914d\u4fe1\u4e2d\u306b"
                  "\u53d6\u5f97\u3057\u305f\u97f3\u58f0\u306e"
                  "\u6587\u5b57\u8d77\u3053\u3057\u3067\u3059\u3002\n"
                + "\u30fb\u6587\u5b57\u8d77\u3053\u3057\u306b\u306f"
                  "\u8a8d\u8b58\u8aa4\u308a\u304c\u542b\u307e\u308c\u308b"
                  "\u53ef\u80fd\u6027\u304c\u3042\u308a\u307e\u3059\u3002\n"
                + "\u30fb\u97f3\u58f0\u306f\u914d\u4fe1\u8005\u306e"
                  "\u767a\u8a71\u5185\u5bb9\u3084\u4f1a\u8a71\u306e"
                  "\u6587\u8108\u3092\u628a\u63e1\u3059\u308b\u305f\u3081"
                  "\u3060\u3051\u306b\u4f7f\u7528\u3057\u3066"
                  "\u304f\u3060\u3055\u3044\u3002\n"
                + "\u30fb\u97f3\u58f0\u5185\u5bb9\u306f\u753b\u9762\u69cb\u56f3"
                  "\u30fb\u660e\u308b\u3055\u30fb\u8996\u8a8d\u6027\u306a\u3069"
                  "\u306e\u753b\u9762\u30b9\u30b3\u30a2\u306b"
                  "\u5f71\u97ff\u3055\u305b\u306a\u3044\u3067"
                  "\u304f\u3060\u3055\u3044\u3002\n"
                + "\u30fb\u6587\u5b57\u8d77\u3053\u3057\u306bBGM\u3001\u97f3\u697d\u3001"
                  "\u6b4c\u5531\u3001\u6b4c\u8a5e\u304c\u6df7\u3056\u308b"
                  "\u53ef\u80fd\u6027\u304c\u3042\u308a\u307e\u3059\u3002\n"
                + "\u30fb\u6b4c\u8a5e\u3084BGM\u7531\u6765\u3068\u8003\u3048\u3089\u308c\u308b"
                  "\u6587\u5b57\u5217\u3092\u3001\u914d\u4fe1\u8005\u306e"
                  "\u767a\u8a71\u3068\u65ad\u5b9a\u3057\u306a\u3044\u3067"
                  "\u304f\u3060\u3055\u3044\u3002\n"
                + "\u914d\u4fe1\u8005\u306e\u767a\u8a71\u304bBGM\u304b"
                  "\u5224\u5225\u3067\u304d\u306a\u3044\u5834\u5408\u306f\u3001"
                  "\u4f1a\u8a71\u5185\u5bb9\u306e\u6839\u62e0\u3068\u3057\u3066"
                  "\u4f7f\u7528\u3057\u306a\u3044\u3067\u304f\u3060\u3055\u3044\u3002"
            )

        raw_answer = self.ai.analyze_image(
            analysis_image_path,
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
            "excessive_dead_space",
            "subject_scale_issue",
            "ui_dominance_issue",
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

        if brightness.get("is_black_screen") is True:
            score = 0
        elif brightness["score"] <= 10:
            score = min(score, 75)
        elif brightness["score"] <= 12:
            score = min(score, 82)

        gift_summary = self.history.get_recent_gift_summary(
            window_seconds=max(
                30,
                int(self.interval),
            )
        )

        fallback_answer = HybridAnalysisFormatter.format(
            issues,
            brightness_score=brightness["score"],
            information_score=information["score"],
            is_black_screen=brightness.get(
                "is_black_screen",
                False,
            ),
        )

        visual_observation = str(
            ai_data.get(
                "visual_observation",
                "",
            )
            or ""
        ).strip()

        main_reason = str(
            ai_data.get(
                "main_reason",
                "",
            )
            or ""
        ).strip()

        priority_action = str(
            ai_data.get(
                "priority_action",
                "",
            )
            or ""
        ).strip()

        # コメント分析は画面分析と分離して表示する。
        visual_main_reason = main_reason
        comment_trend = ""
        comment_action = ""
        next_best_action = ""

        if comments and re.search(
            r"\[+COMMENT_TREND\]+",
            main_reason,
        ):
            parts = re.split(
                r"\[+COMMENT_TREND\]+",
                main_reason,
                maxsplit=1,
            )

            visual_main_reason = parts[0].strip()
            comment_part = parts[1].strip() if len(parts) > 1 else ""

            action_parts = re.split(
                r"\[+COMMENT_ACTION\]+",
                comment_part,
                maxsplit=1,
            )

            comment_trend = (
                action_parts[0].strip()
                if action_parts
                else ""
            )

            action_part = (
                action_parts[1].strip()
                if len(action_parts) > 1
                else ""
            )

            next_parts = re.split(
                r"\[+NEXT_BEST_ACTION\]+",
                action_part,
                maxsplit=1,
            )

            comment_action = (
                next_parts[0].strip()
                if next_parts
                else ""
            )

            next_best_action = (
                next_parts[1].strip()
                if len(next_parts) > 1
                else ""
            )

            if not comment_action:
                comment_action = (
                    "直近コメントの話題を1つ拾い、"
                    "視聴者が返しやすい質問につなげてください。"
                )

            if not next_best_action:
                next_best_action = comment_action

        elif comments:
            # 旧形式の回答が返った場合の互換フォールバック。
            match_comment = re.search(
                r"(視聴者コメントでは[^。！？]*[。！？]?)",
                main_reason,
            )

            if match_comment:
                comment_trend = match_comment.group(1).strip()
                visual_main_reason = (
                    main_reason[:match_comment.start()]
                    + main_reason[match_comment.end():]
                ).strip()

            if not comment_trend:
                comment_trend = (
                    "取得したコメントはありますが、"
                    "今回のAI回答から明確な傾向を分離できませんでした。"
                )

            comment_action = (
                "直近コメントの話題を1つ拾い、"
                "視聴者が返しやすい質問につなげてください。"
            )
            next_best_action = comment_action

        if not next_best_action:
            next_best_action = (
                comment_action
                if comments
                else priority_action
            )

        # コメント用アクションに画面改善・物理動作が混ざった場合は、
        # 安全な「発話のみ」のフォールバックに戻す。
        if comments:
            physical_terms = (
                "カメラ",
                "フレーム",
                "構図",
                "照明",
                "ライト",
                "マイク",
                "画角",
                "背景",
                "レンズ",
                "スマホ",
                "画面",
                "商品",
                "物体",
                "指で",
                "指し",
                "近づけ",
                "持って",
                "持ち",
                "見せ",
                "映し",
                "中央に",
                "距離",
                "固定",
                "移動",
            )

            if any(
                term in comment_action
                for term in physical_terms
            ):
                comment_action = (
                    "直近コメントの話題を1つ拾って短く返し、"
                    "視聴者が答えやすい質問を1つ返してください。"
                )

            if any(
                term in next_best_action
                for term in physical_terms
            ):
                next_best_action = comment_action

        # 実際の件数と矛盾する表現を補正する。
        if len(comments) >= 3 and comment_trend:
            comment_trend = comment_trend.replace(
                "コメント数が少なく、傾向判断は限定的です",
                "話題が分散しており、傾向判断は限定的です",
            ).replace(
                "コメント数が少ないため、傾向判断は限定的です",
                "話題が分散しており、傾向判断は限定的です",
            )

        # ???????AI????
        # Python????????????
        if brightness.get("is_black_screen") is True:
            answer = fallback_answer

        elif (
            visual_observation
            and visual_main_reason
            and priority_action
        ):
            answer = (
                "\u3010AI\u306b\u3088\u308b\u753b\u9762\u5206\u6790\u3011\n"
                f"{visual_observation}\n\n"
                "\u3010\u5206\u6790\u7406\u7531\u3011\n"
                f"{visual_main_reason}"
            )

            if comments:
                category_text = (
                    " / ".join(
                        f"{name} {count}件"
                        for name, count in comment_categories.items()
                        if count > 0
                    )
                    or "分類なし"
                )

                answer = (
                    f"{answer}\n\n"
                    "【コメント分類】\n"
                    f"{category_text}\n\n"
                    "【視聴者コメントの傾向】\n"
                    f"{comment_trend}\n\n"
                    "【配信で拾うとよい反応】\n"
                    f"{comment_action}\n\n"
                    "【今この配信でやると良い一手】\n"
                    f"{next_best_action}"
                )

            answer = (
                f"{answer}\n\n"
                "\u3010\u6700\u512a\u5148\u306e\u6539\u5584\u3011\n"
                f"{priority_action}"
            )

        else:
            # ?????????AI??????
            # ??????????????????
            answer = fallback_answer

        # 実際に取得したコメントを分析結果にも残して、
        # コメント連携が目視で確認できるようにする。
        if comments:
            comment_preview_lines = []

            for item in comments[-5:]:
                username = (
                    item.get("username")
                    or "ユーザー名不明"
                )
                comment_text = (
                    item.get("comment")
                    or ""
                ).strip()

                if not comment_text:
                    continue

                comment_preview_lines.append(
                    f"・{username}: {comment_text}"
                )

            if comment_preview_lines:
                answer = (
                    f"{answer}\n\n"
                    "【直近30秒の視聴者コメント】\n"
                    + "\n".join(comment_preview_lines)
                )

        if audio_transcript:
            answer = (
                f"{answer}\n\n"
                + "\u3010\u76f4\u8fd110\u79d2\u306e\u914d\u4fe1\u97f3\u58f0"
                  "\uff08\u6587\u5b57\u8d77\u3053\u3057\uff09\u3011\n"
                + audio_transcript
            )

        gift_insight = self._format_gift_insight(
            gift_summary
        )

        if gift_insight:
            answer = (
                f"{answer}\n\n"
                "\u3010\u8996\u8074\u8005\u53cd\u5fdc\u3011\n"
                f"{gift_insight}"
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
            image_path=str(image_path),
        )
        print("履歴保存成功")

        result = {
            "score": score,
            "answer": answer,
            "image_path": str(image_path),
            "scene": "TikTok Viewer",
            "gift_summary": gift_summary,
            "comments": comments,
            "comment_categories": comment_categories,
            "score_breakdown": {
                "composition": scores["composition"],
                "brightness": scores["brightness"],
                "visibility": scores["visibility"],
                "information": scores["information"],
                "clarity": scores["clarity"],
                "calculated_total": scores["total"],
                "final_total": score,
            },
            "brightness_analysis": dict(brightness),
            "information_analysis": dict(information),
            "active_issues": [
                name
                for name, active in issues.items()
                if active
            ],
            "ai_explanation": {
                "visual_observation": visual_observation,
                "main_reason": visual_main_reason,
                "comment_trend": comment_trend,
                "comment_action": comment_action,
                "next_best_action": next_best_action,
                "priority_action": priority_action,
            },
            "analyzed_at": datetime.now().isoformat(
                timespec="seconds"
            ),
        }

        self._emit("result", result)
        return result

    # ==================================================
    # Helpers
    # ==================================================

    @staticmethod
    def _classify_comment_categories(
        comments: list[dict[str, str]],
    ) -> dict[str, int]:
        """
        直近コメントを軽量ルールで1件につき1カテゴリへ分類する。
        AIの推測ではなく、本文に現れた表現だけを使う。
        """
        categories = {
            "質問": 0,
            "挨拶": 0,
            "バトル・応援": 0,
            "ギフト関連": 0,
            "参加・誘い": 0,
            "見た目・ビジュアル": 0,
            "ツッコミ・笑い": 0,
            "リアクション": 0,
            "雑談": 0,
        }

        greeting_words = (
            "おはよ",
            "おはよう",
            "こんにちは",
            "こんばんは",
            "おつ",
            "お疲れ",
            "またね",
            "ばいばい",
            "バイバイ",
            "初見",
        )

        battle_words = (
            "バトル",
            "battle",
            "tap",
            "タップ",
            "応援",
            "ヒーロー",
            "勝とう",
            "勝つ",
            "勝ち",
        )

        gift_words = (
            "ギフト",
            "gift",
            "投げ",
            "コイン",
            "バラ",
            "薔薇",
        )

        participation_words = (
            "一緒に",
            "参加",
            "来て",
            "おいで",
            "また行く",
            "また来る",
            "戦おう",
            "やろう",
            "入る",
            "入って",
        )

        visual_words = (
            "かわいい",
            "可愛い",
            "かっこいい",
            "イケメン",
            "顔",
            "髪",
            "服",
            "衣装",
            "メイク",
            "背景",
            "色",
            "ピンク",
            "赤",
            "青",
            "白",
            "黒",
        )

        laugh_words = (
            "www",
            "ww",
            "w",
            "笑",
            "🤣",
            "😂",
            "草",
            "うるさ",
            "なんで",
            "ツッコミ",
        )

        for item in comments:
            comment = str(
                item.get("comment", "")
            ).strip()

            if not comment:
                continue

            lower = comment.lower()

            if (
                "?" in comment
                or "？" in comment
                or any(
                    word in comment
                    for word in (
                        "ですか",
                        "なの",
                        "なに",
                        "何",
                        "どう",
                        "どこ",
                        "いつ",
                        "誰",
                    )
                )
            ):
                categories["質問"] += 1
                continue

            member_level_limit = re.search(
                r"メンレ[ベべ]\s*"
                r"(?:[0-9０-９]+|[〇○]+)\s*"
                r"(?:以下|未満)",
                comment,
            )

            if (
                any(word in lower for word in battle_words)
                or member_level_limit
            ):
                categories["バトル・応援"] += 1
                continue

            if any(word in lower for word in greeting_words):
                categories["挨拶"] += 1
                continue

            if any(word in lower for word in gift_words):
                categories["ギフト関連"] += 1
                continue

            if any(word in comment for word in participation_words):
                categories["参加・誘い"] += 1
                continue

            if any(word in comment for word in visual_words):
                categories["見た目・ビジュアル"] += 1
                continue

            if any(word in lower for word in laugh_words):
                categories["ツッコミ・笑い"] += 1
                continue

            visible_chars = re.sub(
                r"[\s\W_]+",
                "",
                comment,
                flags=re.UNICODE,
            )

            if len(visible_chars) <= 2:
                categories["リアクション"] += 1
                continue

            categories["雑談"] += 1

        return {
            name: count
            for name, count in categories.items()
            if count > 0
        }

    @staticmethod
    def _format_gift_insight(
        summary: dict[str, Any],
    ) -> str:
        event_count = int(
            summary.get("event_count", 0)
            or 0
        )

        if event_count <= 0:
            return ""

        window_seconds = int(
            summary.get("window_seconds", 30)
            or 30
        )

        quantity = int(
            summary.get("quantity", 0)
            or 0
        )

        sender_count = int(
            summary.get("sender_count", 0)
            or 0
        )

        unknown_count = int(
            summary.get("unknown_event_count", 0)
            or 0
        )

        lines = [
            (
                "視聴者反応: "
                f"直近{window_seconds}秒で"
                f"ギフト反応を{event_count}件"
                f"（数量{quantity}）検出。"
            )
        ]

        if sender_count >= 2:
            lines.append(
                "複数の視聴者から"
                "反応が発生しています。"
            )

        lines.append(
            "前後の配信内容と合わせて"
            "確認すると、"
            "反応のきっかけを"
            "特定しやすくなります。"
        )

        if unknown_count > 0:
            lines.append(
                "未確認ギフトを含むため、"
                "コイン数は評価に"
                "使用していません。"
            )

        return " ".join(lines)

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
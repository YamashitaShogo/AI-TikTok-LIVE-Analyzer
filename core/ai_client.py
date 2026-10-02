import base64
import json
import logging
from io import BytesIO
from pathlib import Path
from urllib import error, request

from PIL import Image

from core.license_manager import LicenseManager


logger = logging.getLogger(__name__)


class AIClient:
    SERVER_ANALYZE_URL = (
        "https://ai-tiktok-live-analyzer.onrender.com/ai/analyze"
    )
    SERVER_TRANSCRIBE_URL = (
        "https://ai-tiktok-live-analyzer.onrender.com/ai/transcribe"
    )
    SERVER_TIMEOUT = 120

    @staticmethod
    def _raise_with_details(action: str, exc: Exception):
        logger.error(
            "AI処理エラー (%s): %s",
            action,
            exc,
            exc_info=True,
        )
        raise exc

    @staticmethod
    def _resolve_image_path(image_path) -> Path:
        """渡された画像パスを通常のファイルパスとして解決する。"""
        return Path(str(image_path)).expanduser().resolve()

    def analyze_image(self, image_path, prompt):
        try:
            image_path = self._resolve_image_path(image_path)

            if not image_path.exists():
                raise FileNotFoundError(
                    f"分析画像が見つかりません: {image_path}"
                )

            if image_path.stat().st_size <= 0:
                raise ValueError(
                    "分析画像のファイルサイズが0です。"
                )

            # サーバー送信用にJPEGへ変換・軽量化
            with Image.open(image_path) as image:
                image = image.convert("RGB")

                image.thumbnail(
                    (1280, 1280),
                    Image.Resampling.LANCZOS,
                )

                buffer = BytesIO()

                image.save(
                    buffer,
                    format="JPEG",
                    quality=85,
                    optimize=True,
                )

                image_bytes = buffer.getvalue()

            image_base64 = base64.b64encode(
                image_bytes
            ).decode("utf-8")

            prompt = str(prompt or "").strip()

            if not prompt:
                raise ValueError(
                    "AI分析プロンプトが空です。"
                )

            license_data = (
                LicenseManager.get_license_data()
            )

            license_key = str(
                license_data.get("license_key", "")
            ).strip()

            if not license_key:
                raise ValueError(
                    "ライセンスキーが保存されていません。"
                )

            payload = json.dumps(
                {
                    "license_key": license_key,
                    "prompt": prompt,
                    "image_base64": image_base64,
                }
            ).encode("utf-8")

            req = request.Request(
                self.SERVER_ANALYZE_URL,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )

            try:
                with request.urlopen(
                    req,
                    timeout=self.SERVER_TIMEOUT,
                ) as response:
                    result = json.loads(
                        response.read().decode(
                            "utf-8"
                        )
                    )

            except error.HTTPError as exc:
                try:
                    error_data = json.loads(
                        exc.read().decode("utf-8")
                    )

                    message = error_data.get(
                        "detail",
                        f"HTTPエラー: {exc.code}",
                    )

                except Exception:
                    message = (
                        f"HTTPエラー: {exc.code}"
                    )

                raise RuntimeError(
                    message
                ) from exc

            except error.URLError as exc:
                raise RuntimeError(
                    "AIサーバーへ接続できませんでした。"
                ) from exc

            if not isinstance(result, dict):
                raise RuntimeError(
                    "AIサーバーから不正な応答が返されました。"
                )

            if not result.get("success"):
                raise RuntimeError(
                    result.get(
                        "message",
                        "AI分析に失敗しました。",
                    )
                )

            output_text = str(
                result.get("result", "")
            ).strip()

            if not output_text:
                raise RuntimeError(
                    "AIサーバーから分析結果が返されませんでした。"
                )

            return output_text

        except Exception as exc:
            self._raise_with_details(
                "analyze_image",
                exc,
            )


    def transcribe_audio(self, audio_path):
        try:
            audio_path = (
                Path(str(audio_path))
                .expanduser()
                .resolve()
            )

            if not audio_path.exists():
                raise FileNotFoundError(
                    f"\u97f3\u58f0\u30d5\u30a1\u30a4\u30eb\u304c\u898b\u3064\u304b\u308a\u307e\u305b\u3093: {audio_path}"
                )

            if audio_path.stat().st_size <= 0:
                raise ValueError(
                    "\u97f3\u58f0\u30d5\u30a1\u30a4\u30eb\u306e\u30b5\u30a4\u30ba\u304c0\u3067\u3059\u3002"
                )

            if audio_path.stat().st_size > 10 * 1024 * 1024:
                raise ValueError(
                    "\u97f3\u58f0\u30d5\u30a1\u30a4\u30eb\u304c\u5927\u304d\u3059\u304e\u307e\u3059\u3002"
                )

            audio_base64 = base64.b64encode(
                audio_path.read_bytes()
            ).decode("utf-8")

            license_data = (
                LicenseManager.get_license_data()
            )

            license_key = str(
                license_data.get("license_key", "")
            ).strip()

            if not license_key:
                raise ValueError(
                    "\u30e9\u30a4\u30bb\u30f3\u30b9\u30ad\u30fc\u304c\u4fdd\u5b58\u3055\u308c\u3066\u3044\u307e\u305b\u3093\u3002"
                )

            payload = json.dumps(
                {
                    "license_key": license_key,
                    "audio_base64": audio_base64,
                }
            ).encode("utf-8")

            req = request.Request(
                self.SERVER_TRANSCRIBE_URL,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )

            try:
                with request.urlopen(
                    req,
                    timeout=self.SERVER_TIMEOUT,
                ) as response:
                    result = json.loads(
                        response.read().decode("utf-8")
                    )

            except error.HTTPError as exc:
                try:
                    error_data = json.loads(
                        exc.read().decode("utf-8")
                    )

                    message = error_data.get(
                        "detail",
                        f"HTTP\u30a8\u30e9\u30fc: {exc.code}",
                    )

                except Exception:
                    message = f"HTTP\u30a8\u30e9\u30fc: {exc.code}"

                raise RuntimeError(message) from exc

            except error.URLError as exc:
                raise RuntimeError(
                    "AI\u30b5\u30fc\u30d0\u30fc\u3078\u63a5\u7d9a\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002"
                ) from exc

            if not isinstance(result, dict):
                raise RuntimeError(
                    "AI\u30b5\u30fc\u30d0\u30fc\u304b\u3089\u4e0d\u6b63\u306a\u5fdc\u7b54\u304c\u8fd4\u3055\u308c\u307e\u3057\u305f\u3002"
                )

            output_text = str(
                result.get("text", "")
            ).strip()

            if not output_text:
                raise RuntimeError(
                    "\u6587\u5b57\u8d77\u3053\u3057\u7d50\u679c\u304c\u8fd4\u3055\u308c\u307e\u305b\u3093\u3067\u3057\u305f\u3002"
                )

            return output_text

        except Exception as exc:
            self._raise_with_details(
                "transcribe_audio",
                exc,
            )

    def clear_client(self):
        # サーバー方式ではローカルOpenAIクライアントを
        # 保持しないため、互換性維持用のno-op。
        pass
    def analyze_images(self, image_paths, prompt):
        try:
            if not image_paths:
                raise ValueError(
                    "分析画像が指定されていません。"
                )

            if len(image_paths) > 12:
                raise ValueError(
                    "一度に分析できる画像は最大12枚です。"
                )

            images_base64 = []
            frame_labels = []

            for image_path in image_paths:
                image_path = self._resolve_image_path(
                    image_path
                )

                if not image_path.exists():
                    raise FileNotFoundError(
                        f"分析画像が見つかりません: {image_path}"
                    )

                if image_path.stat().st_size <= 0:
                    raise ValueError(
                        f"分析画像のファイルサイズが0です: {image_path}"
                    )

                # JPEGへ変換・軽量化
                with Image.open(image_path) as image:
                    image = image.convert("RGB")

                    image.thumbnail(
                        (1280, 1280),
                        Image.Resampling.LANCZOS,
                    )

                    buffer = BytesIO()

                    image.save(
                        buffer,
                        format="JPEG",
                        quality=85,
                        optimize=True,
                    )

                    image_bytes = buffer.getvalue()

                image_base64 = base64.b64encode(
                    image_bytes
                ).decode("utf-8")

                images_base64.append(
                    image_base64
                )

                timestamp_text = image_path.stem.rsplit("_", 1)[-1]

                if timestamp_text.endswith("s"):
                    timestamp_text = timestamp_text[:-1]

                frame_labels.append(timestamp_text)

            prompt = str(prompt or "").strip()

            if not prompt:
                raise ValueError(
                    "AI分析プロンプトが空です。"
                )

            timeline_text = "\n".join(
                f"画像{i}: {timestamp}秒時点"
                for i, timestamp in enumerate(
                    frame_labels,
                    start=1,
                )
            )

            prompt = (
                prompt
                + "\n\n"
                + "【Replay動画の時系列情報】\n"
                + "以下の画像は同じReplay動画から"
                "時間順に抽出したフレームです。\n"
                + timeline_text
                + "\n"
                + "画像1が最も古く、最後の画像が最も新しいです。\n"
                + "各画像単体だけでなく、"
                "時間経過による変化も含めて分析してください。"
            )

            license_data = (
                LicenseManager.get_license_data()
            )

            license_key = str(
                license_data.get("license_key", "")
            ).strip()

            if not license_key:
                raise ValueError(
                    "ライセンスキーが保存されていません。"
                )

            payload = json.dumps(
                {
                    "license_key": license_key,
                    "prompt": prompt,
                    "images_base64": images_base64,
                }
            ).encode("utf-8")

            req = request.Request(
                self.SERVER_ANALYZE_URL,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )

            try:
                with request.urlopen(
                    req,
                    timeout=self.SERVER_TIMEOUT,
                ) as response:
                    result = json.loads(
                        response.read().decode(
                            "utf-8"
                        )
                    )

            except error.HTTPError as exc:
                try:
                    error_data = json.loads(
                        exc.read().decode("utf-8")
                    )

                    message = error_data.get(
                        "detail",
                        f"HTTPエラー: {exc.code}",
                    )

                except Exception:
                    message = (
                        f"HTTPエラー: {exc.code}"
                    )

                raise RuntimeError(
                    message
                ) from exc

            except error.URLError as exc:
                raise RuntimeError(
                    "AIサーバーへ接続できませんでした。"
                ) from exc

            if not isinstance(result, dict):
                raise RuntimeError(
                    "AIサーバーから不正な応答が返されました。"
                )

            if not result.get("success"):
                raise RuntimeError(
                    result.get(
                        "message",
                        "AI分析に失敗しました。",
                    )
                )

            output_text = str(
                result.get("result", "")
            ).strip()

            if not output_text:
                raise RuntimeError(
                    "AIサーバーから分析結果が返されませんでした。"
                )

            return output_text

        except Exception as exc:
            self._raise_with_details(
                "analyze_images",
                exc,
            )
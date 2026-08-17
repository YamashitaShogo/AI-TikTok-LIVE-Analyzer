import base64
import json
import logging
from io import BytesIO
from urllib import error, request

from PIL import Image

from core.license_manager import LicenseManager
from core.obs_client import OBSClient


logger = logging.getLogger(__name__)


class AIClient:
    SERVER_ANALYZE_URL = (
        "https://ai-tiktok-live-analyzer.onrender.com/ai/analyze"
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

    def analyze_image(self, image_path, prompt):
        try:
            image_path = OBSClient.resolve_screenshot_path(
                image_path
            )

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

            for image_path in image_paths:
                image_path = OBSClient.resolve_screenshot_path(
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
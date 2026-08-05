import base64
import json
import logging
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from openai import APIStatusError, OpenAI
from core.secure_storage import SecureStorage
from core.obs_client import OBSClient
from io import BytesIO
from PIL import Image
from urllib import error, request
from core.license_manager import LicenseManager

load_dotenv()
logger = logging.getLogger(__name__)


class AIClient:
    MODEL = "gpt-5"
    SERVER_ANALYZE_URL = (
    "https://ai-tiktok-live-analyzer-dev.onrender.com/ai/analyze"
    )
    SERVER_TIMEOUT = 120

    def __init__(self):
        self.client: Optional[OpenAI] = None
        self._current_api_key: Optional[str] = None

    def _get_api_key(self) -> Optional[str]:
        # 開発者が環境変数を設定している場合は最優先
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if api_key:
            return api_key

        # 通常のアプリ利用ではWindows Credential Managerから取得
        try:
            api_key = SecureStorage.get_openai_api_key()
            if api_key:
                return api_key
        except Exception as exc:
            logger.warning(
                "Windows Credential Managerから"
                "OpenAI APIキーを読み込めませんでした: %s",
                exc,
            )

        return None

    def has_api_key(self) -> bool:
        return bool(self._get_api_key())

    def _get_client(self) -> OpenAI:
        api_key = self._get_api_key()

        if not api_key:
            raise ValueError(
                "OpenAI APIキーが設定されていません。\n\n"
                "設定画面でAPIキーを入力して保存するか、"
                "Windowsの環境変数 OPENAI_API_KEY を設定してください。"
            )

        if self.client is None or self._current_api_key != api_key:
            self.client = OpenAI(api_key=api_key)
            self._current_api_key = api_key

        return self.client

    @staticmethod
    def _raise_with_details(action: str, exc: Exception):
        if isinstance(exc, APIStatusError):
            status_code = getattr(exc, "status_code", "不明")
            request_id = getattr(exc, "request_id", None)

            response_text = ""
            response = getattr(exc, "response", None)
            if response is not None:
                try:
                    response_text = response.text
                except Exception:
                    response_text = ""

            logger.error(
                "OpenAI APIエラー (%s) | status=%s | request_id=%s | response=%s",
                action,
                status_code,
                request_id,
                response_text,
                exc_info=True,
            )
        else:
            logger.error(
                "AI処理エラー (%s): %s",
                action,
                exc,
                exc_info=True,
            )

        raise exc

    def test_connection(self):
        try:
            client = self._get_client()

            response = client.responses.create(
                model=self.MODEL,
                input="『接続成功』とだけ返してください。",
            )

            return response.output_text

        except Exception as exc:
            self._raise_with_details("test_connection", exc)

    def analyze_image(self, image_path, prompt):
        try:
            image_path = OBSClient.resolve_screenshot_path(image_path)

            if not image_path.exists():
                raise FileNotFoundError(
                    f"分析画像が見つかりません: {image_path}"
                )

            if image_path.stat().st_size <= 0:
                raise ValueError("分析画像のファイルサイズが0です。")

            # OpenAI送信用に画像をRGB JPEGへ変換して軽量化
            with Image.open(image_path) as image:
                image = image.convert("RGB")

                # 必要以上に大きい画像は縮小
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
                raise ValueError("AI分析プロンプトが空です。")

            license_data = LicenseManager.get_license_data()
            license_key = str(
                license_data.get("license_key", "")
            ).strip()

            if not prompt:
                raise ValueError("AI分析プロンプトが空です.")

            license_data = LicenseManager.get_license_data()

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
                        response.read().decode("utf-8")
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
                    message = f"HTTPエラー: {exc.code}"

                raise RuntimeError(message) from exc

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
            self._raise_with_details("analyze_image", exc)

    def clear_client(self):
        self.client = None
        self._current_api_key = None
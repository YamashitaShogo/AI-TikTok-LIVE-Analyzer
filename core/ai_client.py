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

load_dotenv()
logger = logging.getLogger(__name__)


class AIClient:
    MODEL = "gpt-5"

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
            client = self._get_client()
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

            response = client.responses.create(
                model=self.MODEL,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": prompt,
                            },
                            {
                                "type": "input_image",
                                "image_url": (
                                    "data:image/jpeg;base64,"
                                    f"{image_base64}"
                                ),
                            },
                        ],
                    }
                ],
            )

            output_text = getattr(response, "output_text", "")
            if not output_text:
                raise RuntimeError(
                    "OpenAIから分析結果が返されませんでした。"
                )

            return output_text

        except Exception as exc:
            self._raise_with_details("analyze_image", exc)

    def clear_client(self):
        self.client = None
        self._current_api_key = None
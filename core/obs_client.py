import logging
import os
from pathlib import Path
from typing import Optional

from obsws_python import ReqClient

for logger_name in (
    "obsws_python",
    "obsws_python.baseclient",
    "obsws_python.reqs",
):
    logging.getLogger(logger_name).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


class OBSClient:
    DEFAULT_HOST = "localhost"
    DEFAULT_PORT = 4455
    APP_NAME = "AI-TikTok-LIVE-Analyzer"

    def __init__(self):
        self.client: Optional[ReqClient] = None

    @classmethod
    def get_app_data_dir(cls) -> Path:
        base = os.getenv("LOCALAPPDATA")
        if not base:
            base = os.path.join(
                os.path.expanduser("~"),
                "AppData",
                "Local",
            )

        app_dir = Path(base) / cls.APP_NAME
        app_dir.mkdir(parents=True, exist_ok=True)
        return app_dir

    @classmethod
    def resolve_screenshot_path(cls, image_path) -> Path:
        raw_path = Path(os.fspath(image_path))

        if raw_path.is_absolute():
            resolved = raw_path
        else:
            resolved = cls.get_app_data_dir() / raw_path

        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved

    def connect(self, host, port, password):
        self.disconnect()

        host = str(host or self.DEFAULT_HOST).strip()

        try:
            port = int(port)
        except (TypeError, ValueError):
            logger.error("OBSポートが不正です。")
            return False

        if not 1 <= port <= 65535:
            logger.error("OBSポートが範囲外です。")
            return False

        try:
            self.client = ReqClient(
                host=host,
                port=port,
                password=password or "",
                timeout=5,
            )
            self.client.get_version()

            logger.info(
                "OBS WebSocketへ接続しました。host=%s port=%s",
                host,
                port,
            )
            return True

        except Exception as exc:
            logger.error("OBS接続エラー: %s", exc)
            self.client = None
            return False

    def disconnect(self):
        client = self.client
        self.client = None

        if client is None:
            return

        try:
            disconnect = getattr(client, "disconnect", None)
            if callable(disconnect):
                disconnect()
        except Exception:
            pass

    def is_connected(self):
        if self.client is None:
            return False

        try:
            self.client.get_version()
            return True
        except Exception:
            return False

    def get_current_scene(self):
        if self.client is None:
            return None

        try:
            scene = self.client.get_current_program_scene()
            return scene.current_program_scene_name
        except Exception as exc:
            logger.error("現在シーン取得エラー: %s", exc)
            return None

    def get_sources(self):
        if self.client is None:
            return None

        try:
            scene = self.client.get_current_program_scene()

            items = self.client.get_scene_item_list(
                scene.current_program_scene_name
            )

            result = []

            for item in items.scene_items:
                if isinstance(item, dict):
                    source_name = (
                        item.get("sourceName")
                        or item.get("source_name")
                    )
                else:
                    source_name = getattr(item, "source_name", None)

                if source_name:
                    result.append(source_name)

            return result

        except Exception as exc:
            logger.error("ソース取得エラー: %s", exc)
            return None

    def is_streaming(self):
        if self.client is None:
            return False

        try:
            status = self.client.get_stream_status()
            return bool(status.output_active)
        except Exception as exc:
            logger.debug("配信状態取得エラー: %s", exc)
            return False

    def is_recording(self):
        if self.client is None:
            return False

        try:
            status = self.client.get_record_status()
            return bool(status.output_active)
        except Exception as exc:
            logger.debug("録画状態取得エラー: %s", exc)
            return False

    def is_replay_buffer_active(self):
        if self.client is None:
            return False

        try:
            status = self.client.get_replay_buffer_status()
            return bool(status.output_active)

        except Exception as exc:
            logger.debug(
                "リプレイバッファ状態取得エラー: %s",
                exc,
            )
            return False

    def start_replay_buffer(self):
        if not self.is_connected():
            logger.warning(
                "OBS未接続のためリプレイバッファを開始できません。"
            )
            return False

        try:
            if self.is_replay_buffer_active():
                return True

            self.client.start_replay_buffer()

            logger.info(
                "OBSリプレイバッファを開始しました。"
            )
            return True

        except Exception as exc:
            logger.error(
                "OBSリプレイバッファ開始エラー: %s",
                exc,
            )
            return False

    def save_replay_buffer(self):
        if not self.is_connected():
            logger.warning(
                "OBS未接続のためリプレイを保存できません。"
            )
            return False

        try:
            if not self.is_replay_buffer_active():
                logger.warning(
                    "リプレイバッファが開始されていません。"
                )
                return False

            self.client.save_replay_buffer()

            logger.info(
                "OBSリプレイバッファを保存しました。"
            )
            return True

        except Exception as exc:
            logger.error(
                "OBSリプレイ保存エラー: %s",
                exc,
            )
            return False

    def stop_replay_buffer(self):
        if not self.is_connected():
            return False

        try:
            if not self.is_replay_buffer_active():
                return True

            self.client.stop_replay_buffer()

            logger.info(
                "OBSリプレイバッファを停止しました。"
            )
            return True

        except Exception as exc:
            logger.error(
                "OBSリプレイバッファ停止エラー: %s",
                exc,
            )
            return False

    def get_last_replay_path(self):
        if not self.is_connected():
            return None

        try:
            replay = self.client.get_last_replay_buffer_replay()

            return getattr(
                replay,
                "saved_replay_path",
                None,
            )

        except Exception as exc:
            logger.error(
                "最後のリプレイパス取得エラー: %s",
                exc,
            )
            return None   

    def start_stream(self):
        if not self.is_connected():
            logger.warning("OBS未接続のため開始処理を実行できません。")
            return False

        logger.info(
            "TikTok LIVE Studio運用のためOBS配信開始はスキップしました。"
        )
        return True

    def stop_stream(self):
        if not self.is_connected():
            return False

        logger.info(
            "TikTok LIVE Studio運用のためOBS配信停止はスキップしました。"
        )
        return True

    def save_screenshot(
        self,
        source_name,
        image_path,
        width=1920,
        height=1080,
        quality=100,
    ):
        if self.client is None:
            logger.warning(
                "OBS未接続のためスクリーンショットを取得できません。"
            )
            return False

        if not source_name:
            logger.error("スクリーンショット対象名が空です。")
            return False

        try:
            resolved_path = self.resolve_screenshot_path(image_path)

            self.client.save_source_screenshot(
                source_name,
                "png",
                str(resolved_path),
                int(width),
                int(height),
                int(quality),
            )

            if not resolved_path.exists():
                logger.error(
                    "スクリーンショット保存後にファイルが見つかりません。path=%s",
                    resolved_path,
                )
                return False

            if resolved_path.stat().st_size <= 0:
                logger.error("保存されたスクリーンショットが空です。")
                return False

            logger.debug(
                "スクリーンショット保存成功: %s",
                resolved_path,
            )
            return True

        except PermissionError as exc:
            logger.error(
                "スクリーンショット保存権限エラー: %s",
                exc,
            )
            return False

        except Exception as exc:
            logger.error(
                "スクリーンショット取得エラー: %s",
                exc,
            )
            return False

    def close(self):
        self.disconnect()
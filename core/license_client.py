import json
import socket
import time
from urllib import error, request


class LicenseClient:
    VERIFY_URL = "https://ai-tiktok-live-analyzer.onrender.com/license/verify"

    # Render Freeのスリープ復帰を考慮
    TIMEOUT = 30
    RETRY_COUNT = 2
    RETRY_WAIT = 2

    @classmethod
    def verify(cls, license_key: str) -> dict:
        key = "".join(str(license_key or "").split()).upper()

        if not key:
            return {
                "valid": False,
                "status": "invalid",
                "message": "ライセンスキーを入力してください。",
            }

        body = json.dumps(
            {
                "license_key": key
            }
        ).encode("utf-8")

        last_error = None

        for attempt in range(cls.RETRY_COUNT + 1):
            req = request.Request(
                cls.VERIFY_URL,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )

            try:
                with request.urlopen(
                    req,
                    timeout=cls.TIMEOUT,
                ) as response:
                    data = json.loads(
                        response.read().decode("utf-8")
                    )

                if not isinstance(data, dict):
                    return {
                        "valid": False,
                        "status": "error",
                        "message": "サーバーの応答形式が不正です。",
                    }

                return data

            except error.HTTPError as exc:
                try:
                    response_data = json.loads(
                        exc.read().decode("utf-8")
                    )

                    message = response_data.get(
                        "detail",
                        f"HTTPエラー: {exc.code}",
                    )

                except Exception:
                    message = f"HTTPエラー: {exc.code}"

                return {
                    "valid": False,
                    "status": "server_error",
                    "message": str(message),
                }

            except (
                error.URLError,
                socket.timeout,
                TimeoutError,
            ) as exc:
                last_error = exc

                if attempt < cls.RETRY_COUNT:
                    time.sleep(cls.RETRY_WAIT)
                    continue

            except Exception as exc:
                last_error = exc

                if attempt < cls.RETRY_COUNT:
                    time.sleep(cls.RETRY_WAIT)
                    continue

        return {
            "valid": False,
            "status": "offline",
            "message": (
                "ライセンスサーバーへ接続できませんでした。\n"
                "しばらく待ってからもう一度お試しください。"
            ),
            "error": str(last_error) if last_error else "",
        }
import json
from urllib import error, request


class LicenseClient:
    VERIFY_URL = "https://公開したURL/license/verify"
    TIMEOUT = 10

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

        except error.URLError:
            return {
                "valid": False,
                "status": "offline",
                "message": (
                    "ライセンスサーバーへ接続できません。"
                    "サーバーが起動しているか確認してください。"
                ),
            }

        except Exception as exc:
            return {
                "valid": False,
                "status": "error",
                "message": f"ライセンス認証エラー: {exc}",
            }
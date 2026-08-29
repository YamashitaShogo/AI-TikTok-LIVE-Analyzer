from core.license_client import LicenseClient
from core.settings import Settings


class LicenseManager:
    """Livemetry Pulse のオンラインライセンス管理。"""

    @classmethod
    def get_license_data(cls) -> dict:
        data = Settings.load()

        if not isinstance(data, dict):
            data = {}

        return {
            "license_key": str(data.get("license_key", "")).strip(),
            "license_status": str(data.get("license_status", "未認証")).strip(),
            "license_plan": str(data.get("license_plan", "")).strip(),
            "license_expires_at": str(data.get("license_expires_at", "")).strip(),
        }

    @classmethod
    def is_licensed(cls) -> bool:
        data = cls.get_license_data()

        return (
            bool(data["license_key"])
            and "認証済み" in data["license_status"]
        )

    @classmethod
    def verify_online(cls) -> dict:
        current = Settings.load()

        if not isinstance(current, dict):
            current = {}

        license_key = str(current.get("license_key", "")).strip()

        if not license_key:
            result = {
                "valid": False,
                "status": "missing",
                "message": "保存済みライセンスキーがありません。",
            }
            cls._save_result(current, "", result)
            return result

        result = LicenseClient.verify(license_key)

        cls._save_result(
            current,
            license_key,
            result,
        )

        return result

    @classmethod
    def verify_key_online(cls, license_key: str) -> dict:
        key = "".join(str(license_key or "").split()).upper()

        current = Settings.load()

        if not isinstance(current, dict):
            current = {}

        result = LicenseClient.verify(key)

        cls._save_result(
            current,
            key,
            result,
        )

        return result

    @classmethod
    def _save_result(
        cls,
        current: dict,
        license_key: str,
        result: dict,
    ):
        valid = bool(result.get("valid"))

        current["license_key"] = license_key

        if valid:
            current["license_status"] = "✅ 認証済み"
            current["license_plan"] = str(result.get("plan", ""))
            current["license_expires_at"] = str(
                result.get("expires_at", "")
            )
        else:
            current["license_status"] = "❌ 未認証"
            current["license_plan"] = ""
            current["license_expires_at"] = ""

        Settings.save(current)

    @classmethod
    def clear_license(cls):
        current = Settings.load()

        if not isinstance(current, dict):
            current = {}

        current["license_key"] = ""
        current["license_status"] = "未認証"
        current["license_plan"] = ""
        current["license_expires_at"] = ""

        Settings.save(current)
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import json
from datetime import datetime


app = FastAPI(
    title="AI TikTok LIVE Analyzer License Server",
    version="1.0.0"
)


class LicenseRequest(BaseModel):
    license_key: str


def load_licenses():
    """
    Renderの環境変数 LICENSES_JSON から
    ライセンス情報を読み込む。
    """
    licenses_json = os.getenv("LICENSES_JSON")

    if not licenses_json:
        print("WARNING: LICENSES_JSON is not set.")
        return {}

    try:
        data = json.loads(licenses_json)
    except json.JSONDecodeError as e:
        print(f"ERROR: LICENSES_JSON is invalid JSON: {e}")
        return {}

    if not isinstance(data, dict):
        print("ERROR: LICENSES_JSON must contain a JSON object.")
        return {}

    return data


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "AI TikTok LIVE Analyzer License Server"
    }


@app.post("/license/verify")
def verify_license(request: LicenseRequest):
    key = request.license_key.strip().upper()

    if not key:
        raise HTTPException(
            status_code=400,
            detail="ライセンスキーが空です。"
        )

    licenses = load_licenses()
    license_data = licenses.get(key)

    if not license_data:
        return {
            "valid": False,
            "status": "invalid",
            "message": "ライセンスキーが無効です。"
        }

    if not license_data.get("active", False):
        return {
            "valid": False,
            "status": "inactive",
            "message": "このライセンスは停止されています。"
        }

    expires_at = license_data.get("expires_at")

    if expires_at:
        try:
            expires_date = datetime.fromisoformat(expires_at)

            if datetime.now() > expires_date:
                return {
                    "valid": False,
                    "status": "expired",
                    "message": "ライセンスの有効期限が切れています。"
                }

        except ValueError:
            return {
                "valid": False,
                "status": "error",
                "message": "ライセンスデータの有効期限形式が不正です。"
            }

    return {
        "valid": True,
        "status": "active",
        "plan": license_data.get("plan", "standard"),
        "expires_at": expires_at,
        "message": "ライセンス認証に成功しました。"
    }
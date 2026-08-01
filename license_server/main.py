from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import json
from pathlib import Path
from datetime import datetime


app = FastAPI(
    title="AI TikTok LIVE Analyzer License Server",
    version="1.0.0"
)

BASE_DIR = Path(__file__).resolve().parent
LICENSE_FILE = BASE_DIR / "licenses.json"


class LicenseRequest(BaseModel):
    license_key: str


def load_licenses():
    if not LICENSE_FILE.exists():
        return {}

    with LICENSE_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
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
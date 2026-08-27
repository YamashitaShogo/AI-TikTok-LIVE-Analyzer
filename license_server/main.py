import time
from collections import defaultdict, deque
from threading import Lock
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
import os
import json
import urllib.request
import urllib.error
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware

AI_RATE_LIMIT = 5          # 回
AI_RATE_WINDOW = 60       # 60秒

_ai_request_history = defaultdict(deque)
_ai_rate_lock = Lock()

app = FastAPI(
    title="AI TikTok LIVE Analyzer License Server",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "https://yamashitashogo.github.io",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LicenseRequest(BaseModel):
    license_key: str

class AIAnalyzeRequest(BaseModel):
    license_key: str
    prompt: str
    image_base64: str | None = None
    images_base64: list[str] | None = None

class ContactRequest(BaseModel):
    name: str
    email: str
    category: str
    message: str

def send_contact_email(
    name: str,
    email: str,
    category: str,
    message: str,
):
    resend_api_key = os.getenv(
        "RESEND_API_KEY",
        "",
    ).strip()

    contact_to = os.getenv(
        "CONTACT_TO_EMAIL",
        "",
    ).strip()

    if not resend_api_key:
        raise RuntimeError(
            "RESEND_API_KEY が設定されていません。"
        )

    if not contact_to:
        raise RuntimeError(
            "CONTACT_TO_EMAIL が設定されていません。"
        )

    payload = {
        "from": (
            "AI TikTok LIVE Analyzer "
            "<onboarding@resend.dev>"
        ),
        "to": [
            contact_to
        ],
        "subject": (
            "[AI TikTok LIVE Analyzer] "
            f"お問い合わせ: {category}"
        ),
        "reply_to": email,
        "text": (
            "AI TikTok LIVE Analyzer\n"
            "お問い合わせフォームから"
            "新しい問い合わせが届きました。\n\n"

            f"お名前:\n{name}\n\n"

            f"メールアドレス:\n{email}\n\n"

            f"お問い合わせ種別:\n{category}\n\n"

            f"お問い合わせ内容:\n{message}"
        ),
    }

    body = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=body,
        method="POST",
        headers={
            "Authorization": (
                f"Bearer {resend_api_key}"
            ),
            "Content-Type": "application/json",
            "User-Agent": "AI-TikTok-LIVE-Analyzer/1.0",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
        ) as response:

            result = response.read().decode(
                "utf-8"
            )

            print(
                f"[CONTACT EMAIL] {result}"
            )

    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        raise RuntimeError(
            f"Resend API error "
            f"{exc.code}: {error_body}"
        ) from exc
    

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

def check_ai_rate_limit(license_key: str):
    now = time.time()

    with _ai_rate_lock:
        history = _ai_request_history[license_key]

        while history and now - history[0] >= AI_RATE_WINDOW:
            history.popleft()

        if len(history) >= AI_RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="AI分析の利用回数が多すぎます。しばらく待ってから再試行してください。",
            )

        history.append(now)


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
@app.post("/ai/analyze")
def analyze_ai(request: AIAnalyzeRequest):
    key = request.license_key.strip().upper()

    if not key:
        raise HTTPException(
            status_code=400,
            detail="ライセンスキーが空です。",
        )

    licenses = load_licenses()
    license_data = licenses.get(key)

    if not license_data:
        raise HTTPException(
            status_code=403,
            detail="ライセンスキーが無効です。",
        )

    if not license_data.get("active", False):
        raise HTTPException(
            status_code=403,
            detail="このライセンスは停止されています。",
        )

    expires_at = license_data.get("expires_at")

    if expires_at:
        try:
            expires_date = datetime.fromisoformat(expires_at)

            if datetime.now() > expires_date:
                raise HTTPException(
                    status_code=403,
                    detail="ライセンスの有効期限が切れています。",
                )

        except ValueError:
            raise HTTPException(
                status_code=500,
                detail="ライセンスの有効期限データが不正です。",
            )

    check_ai_rate_limit(key)

    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="サーバーのOpenAI APIキーが設定されていません。",
        )

    prompt = request.prompt.strip()

    if not prompt:
        raise HTTPException(
            status_code=400,
            detail="AI分析プロンプトが空です。",
        )

    images_base64 = []

    # 新しい複数画像形式
    if request.images_base64:
        images_base64 = [
            str(image).strip()
            for image in request.images_base64
            if str(image).strip()
        ]

    # 従来の1画像形式との後方互換
    elif request.image_base64:
        image_base64 = request.image_base64.strip()

        if image_base64:
            images_base64 = [image_base64]

    if not images_base64:
        raise HTTPException(
            status_code=400,
            detail="画像データが空です。",
        )

    # Replay解析側の上限と合わせる
    if len(images_base64) > 12:
        raise HTTPException(
            status_code=400,
            detail="一度に分析できる画像は最大12枚です。",
        )

    try:
        client = OpenAI(api_key=api_key)

        content = [
            {
                "type": "input_text",
                "text": (
                    prompt
                    + "\n\n"
                    + "以下の画像はReplay Bufferから抽出した"
                    + "時系列フレームです。"
                    + "最初の画像が最も古く、最後の画像が最も新しいです。"
                    + "各画像を個別に見るだけでなく、"
                    + "時間経過による変化も含めて分析してください。"
                ),
            }
        ]

        for image_base64 in images_base64:
            content.append(
                {
                    "type": "input_image",
                    "image_url": (
                        "data:image/jpeg;base64,"
                        + image_base64
                    ),
                }
            )

        response = client.responses.create(
            model="gpt-5",
            input=[
                {
                    "role": "user",
                    "content": content,
                }
            ],
        )
        

        output_text = getattr(
            response,
            "output_text",
            "",
        )

        if not output_text:
            raise RuntimeError(
                "OpenAIから分析結果が返されませんでした。"
            )

        return {
            "success": True,
            "result": output_text,
            "plan": license_data.get(
                "plan",
                "standard",
            ),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"AI分析に失敗しました: {exc}",
        )

@app.post("/contact")
def contact(request: ContactRequest):

    name = request.name.strip()
    email = request.email.strip()
    category = request.category.strip()
    message = request.message.strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="お名前を入力してください。",
        )

    if not email or "@" not in email:
        raise HTTPException(
            status_code=400,
            detail="メールアドレスが正しくありません。",
        )

    if not category:
        raise HTTPException(
            status_code=400,
            detail="お問い合わせ種別を選択してください。",
        )

    if not message:
        raise HTTPException(
            status_code=400,
            detail="お問い合わせ内容を入力してください。",
        )

    try:
        send_contact_email(
            name=name,
            email=email,
            category=category,
            message=message,
        )

    except Exception as exc:
        print(
            f"[CONTACT ERROR] "
            f"{type(exc).__name__}: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail="お問い合わせメールの送信に失敗しました。",
        )

    return {
        "ok": True,
        "message": "お問い合わせを受け付けました。",
    }
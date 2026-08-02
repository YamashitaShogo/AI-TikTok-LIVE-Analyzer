import keyring


class SecureStorage:
    SERVICE_NAME = "AI-TikTok-LIVE-Analyzer"
    OPENAI_API_KEY_NAME = "openai_api_key"

    @classmethod
    def save_openai_api_key(cls, api_key: str) -> None:
        key = str(api_key or "").strip()

        if not key:
            cls.delete_openai_api_key()
            return

        keyring.set_password(
            cls.SERVICE_NAME,
            cls.OPENAI_API_KEY_NAME,
            key,
        )

    @classmethod
    def get_openai_api_key(cls) -> str:
        value = keyring.get_password(
            cls.SERVICE_NAME,
            cls.OPENAI_API_KEY_NAME,
        )

        return str(value or "").strip()

    @classmethod
    def delete_openai_api_key(cls) -> None:
        try:
            keyring.delete_password(
                cls.SERVICE_NAME,
                cls.OPENAI_API_KEY_NAME,
            )
        except keyring.errors.PasswordDeleteError:
            pass
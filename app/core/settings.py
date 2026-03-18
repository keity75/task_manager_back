from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["local", "development", "production"]


class Settings(BaseSettings):
    """環境変数と.envファイルから設定を読み込む。

    設定の読み込み優先順位(高い順):
    1. 環境変数(システムまたはDocker Composeから渡されたもの)
    2. .envファイル
    3. フィールドのデフォルト値

    """

    # --------------------------------------------------------------------------
    # Pydanticモデル自体の設定
    # --------------------------------------------------------------------------
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,  # 環境変数名の大文字/小文字を区別する
        extra="forbid",  # .envに定義されていないフィールドがあればエラー
    )

    # --------------------------------------------------------------------------
    # アプリケーション基本設定
    # (FastAPI本体や、CORS設定などで利用)
    # --------------------------------------------------------------------------
    LOG_LEVEL: str = "INFO"
    FRONTEND_URL: str = "http://localhost:3000"
    GOOGLE_CLOUD_PROJECT: str
    FIRESTORE_EMULATOR_HOST: str | None = None
    FIRESTORE_EMULATOR_PROJECT: str | None = None
    FIRESTORE_DATABASE_ID: str = "(default)"
    DEFAULT_TIMEZONE: str = "Asia/Tokyo"
    API_PREFIX: str = "/api"
    API_VERSION: str = "/v1"

    # --------------------------------------------------------------------------
    # 外部APIクライアント共通設定
    # (app/clients/ 以下のモジュールで利用)
    # --------------------------------------------------------------------------
    HTTP_CLIENT_TIMEOUT: float = 120.0
    HTTP_CLIENT_MAX_RETRIES: int = 3

    # --------------------------------------------------------------------------
    # 外部サービスURL
    # --------------------------------------------------------------------------
    GOOGLE_CALENDAR_BASE_URL: str = (
        "https://www.google.com/calendar/render?action=TEMPLATE"
    )

    # --------------------------------------------------------------------------
    # OAuth2プロバイダー設定 (プロバイダートークンリフレッシュ用)
    # --------------------------------------------------------------------------
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str

    # --------------------------------------------------------------------------
    # 暗号化設定 (プロバイダートークン暗号化用)
    # --------------------------------------------------------------------------
    ENCRYPTION_KEY: str

    # --------------------------------------------------------------------------
    # 認証・JWT設定
    # --------------------------------------------------------------------------
    BACKEND_JWT_SECRET: str
    ACCESS_TOKEN_EXPIRE_HOURS: int = 1
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    ALLOWED_EMAIL_DOMAINS: list[str] = []  # 空 = 制限なし


# アプリケーション全体で共有するシングルトンインスタンス
settings = Settings()

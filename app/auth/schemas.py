from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict

from pydantic import EmailStr, Field

from app.core.schemas import CamelModel

# =============================================================================
# 内部モデル (リポジトリ戻り値用)
# =============================================================================


class BackendSession(CamelModel):
    """バックエンドセッション情報 (リポジトリ戻り値用の内部モデル)"""

    session_id: str = Field(..., description="セッションID")
    user_id: str = Field(..., description="内部ユーザーID")
    refresh_token_hash: str = Field(..., description="リフレッシュトークンのハッシュ")
    expires_at: datetime = Field(..., description="有効期限")
    is_revoked: bool = Field(default=False, description="無効化フラグ")


@dataclass
class ProviderTokens:
    """プロバイダートークンリフレッシュの結果

    プロバイダーAPI(Google等)からトークンをリフレッシュした際の結果を保持する。
    """

    access_token: str  # 新しいアクセストークン
    expires_at: datetime  # 新しい有効期限


@dataclass
class ProviderCredentials:
    """プロバイダーのOAuth2クライアント認証情報

    プロバイダートークンをリフレッシュする際に必要なクライアントID/シークレット。
    """

    client_id: str  # OAuth2クライアントID
    client_secret: str  # OAuth2クライアントシークレット


@dataclass
class ProviderTokenData:
    """Firestoreから取得したプロバイダートークンデータ

    auth_providersコレクションから取得した暗号化トークン情報。
    """

    encrypted_access_token: str  # 暗号化されたアクセストークン
    encrypted_refresh_token: str  # 暗号化されたリフレッシュトークン
    expires_at: datetime  # トークンの有効期限


# =============================================================================
# 認証情報同期 (/auth/sync)
# =============================================================================


class AuthSyncRequest(CamelModel):
    """認証情報同期リクエスト

    OAuth2認証後にNextAuthから呼び出され、
    プロバイダー認証情報をバックエンドと同期するためのスキーマ。
    """

    provider: str = Field(..., description="認証プロバイダー (例: google, microsoft)")
    provider_account_id: str = Field(..., description="プロバイダーアカウントID")
    email: EmailStr = Field(..., description="ユーザーメールアドレス")
    name: str = Field(..., description="ユーザー名")
    provider_access_token: str = Field(
        ..., description="暗号化されたプロバイダーアクセストークン"
    )
    provider_refresh_token: str = Field(
        ..., description="暗号化されたプロバイダーリフレッシュトークン"
    )
    provider_token_expires_at: int = Field(
        ..., description="プロバイダートークン有効期限(UNIXタイム秒)"
    )


class AuthSyncResponse(CamelModel):
    """認証情報同期レスポンス

    同期結果としてバックエンドAPIトークンを返す。
    """

    user_id: str = Field(..., description="ユーザーID")
    access_token: str = Field(..., description="APIアクセストークン")
    refresh_token: str = Field(..., description="リフレッシュトークン")
    expires_at: int = Field(
        ..., description="アクセストークン有効期限(Unixタイムスタンプ)"
    )
    is_new_user: bool = Field(..., description="新規ユーザーフラグ")
    user_name: str | None = Field(None, description="ユーザー名")


# =============================================================================
# トークンリフレッシュ (/auth/token/refresh)
# =============================================================================


class AuthTokenRefreshRequest(CamelModel):
    """トークンリフレッシュリクエスト"""

    refresh_token: str = Field(..., description="リフレッシュトークン")


class AuthTokenRefreshResponse(CamelModel):
    """トークンリフレッシュレスポンス"""

    access_token: str = Field(..., description="新しいAPIアクセストークン")
    expires_at: int = Field(
        ..., description="新しいアクセストークン有効期限(Unixタイムスタンプ)"
    )


# =============================================================================
# ログアウト (/auth/logout)
# =============================================================================


class LogoutRequest(CamelModel):
    """ログアウトリクエスト"""

    refresh_token: str = Field(..., description="無効化するリフレッシュトークン")


# =============================================================================
# OAuth2プロバイダーのAPIレスポンス型(内部使用)
# =============================================================================


class GoogleTokenResponse(TypedDict):
    """GoogleのトークンエンドポイントAPIレスポンス

    エンドポイント: https://oauth2.googleapis.com/token
    参考: https://developers.google.com/identity/protocols/oauth2/web-server

    Note: YAGNI原則に従い、実際に使用するフィールドのみ定義
    """

    access_token: str
    expires_in: int

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from app.auth.error_messages import AuthErrorMessages
from app.auth.exceptions import (
    AuthSyncError,
    EmailDomainNotAllowedError,
    InvalidRefreshTokenError,
)
from app.auth.repository import AuthRepository
from app.auth.schemas import (
    AuthSyncRequest,
    AuthSyncResponse,
    AuthTokenRefreshRequest,
    AuthTokenRefreshResponse,
)
from app.auth.validation import validate_email_domain
from app.core.logging import get_logger
from app.core.settings import settings

log = get_logger(__name__)


class AuthService:
    """認証機能のビジネスロジック"""

    def __init__(self, auth_repository: AuthRepository) -> None:
        self.repo = auth_repository

    # =========================================================================
    # 認証情報同期 (/auth/sync)
    # =========================================================================

    def sync_auth(self, request: AuthSyncRequest) -> AuthSyncResponse:
        """認証情報の同期

        1. ユーザーを検索/作成
        2. プロバイダートークンを保存
        3. バックエンドJWTを発行
        4. リフレッシュトークンをハッシュ化してDBに保存
        """
        # ドメインチェック(Repositoryアクセス前に実行)
        try:
            validate_email_domain(request.email, settings.ALLOWED_EMAIL_DOMAINS)
        except ValueError as err:
            raise EmailDomainNotAllowedError(
                AuthErrorMessages.EMAIL_DOMAIN_NOT_ALLOWED
            ) from err

        try:
            # プロバイダートークン有効期限をUTC datetimeに変換
            provider_expires_at_dt = datetime.fromtimestamp(
                request.provider_token_expires_at,
                tz=UTC,
            )

            # 既存ユーザーの確認
            existing_user_id = self.repo.find_user_by_provider_id(
                request.provider_account_id
            )

            if existing_user_id:
                user_id = existing_user_id
                is_new_user = False
                # プロバイダートークンを更新
                self.repo.update_user_tokens(
                    user_id=user_id,
                    provider_access_token=request.provider_access_token,
                    provider_refresh_token=request.provider_refresh_token,
                    expires_at=provider_expires_at_dt,
                )
                # 旧セッションを全て無効化
                self.repo.revoke_all_user_sessions(user_id)
                # 既存ユーザーの名前をDBから取得(取得できない場合はリクエストから、それもなければNone)
                user_name = self.repo.get_user_name(user_id) or request.name or None
            else:
                # 新規ユーザー作成
                user_id = self.repo.create_user(
                    name=request.name,
                    email=request.email,
                    provider=request.provider,
                    provider_account_id=request.provider_account_id,
                    provider_access_token=request.provider_access_token,
                    provider_refresh_token=request.provider_refresh_token,
                    expires_at=provider_expires_at_dt,
                )
                is_new_user = True
                # 新規ユーザーはリクエストから名前を使用
                user_name = request.name

            # APIトークンを生成
            access_token, expires_at = self._generate_access_token(user_id)
            refresh_token = self._generate_refresh_token()

            # リフレッシュトークンをハッシュ化してDBに保存
            refresh_token_hash = self._hash_token(refresh_token)
            refresh_expires_at = datetime.now(UTC) + timedelta(
                days=settings.REFRESH_TOKEN_EXPIRE_DAYS
            )
            self.repo.create_backend_session(
                user_id=user_id,
                refresh_token_hash=refresh_token_hash,
                expires_at=refresh_expires_at,
            )

            return AuthSyncResponse(
                user_id=user_id,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                is_new_user=is_new_user,
                user_name=user_name,
            )
        except AuthSyncError:
            raise
        except Exception as err:
            log.warning(
                "Auth sync failed.",
                error_type=type(err).__name__,
                original_error=str(err),
            )
            raise AuthSyncError(AuthErrorMessages.AUTH_SYNC_FAILED) from err

    # =========================================================================
    # トークンリフレッシュ (/auth/token/refresh)
    # =========================================================================

    def refresh_token(
        self, request: AuthTokenRefreshRequest
    ) -> AuthTokenRefreshResponse:
        """アクセストークンのリフレッシュ

        リフレッシュトークンを検証し、新しいアクセストークンを発行
        """
        # リフレッシュトークンをハッシュ化して検証
        refresh_token_hash = self._hash_token(request.refresh_token)
        session = self.repo.find_backend_session_by_token_hash(refresh_token_hash)

        if not session:
            log.warning(
                "Refresh token validation failed: session not found.",
                error_type="InvalidRefreshTokenError",
                original_error="Invalid or expired refresh token",
            )
            raise InvalidRefreshTokenError(
                AuthErrorMessages.INVALID_OR_EXPIRED_REFRESH_TOKEN
            )

        if session.is_revoked:
            log.warning(
                "Refresh token validation failed: token has been revoked.",
                error_type="InvalidRefreshTokenError",
                original_error="Refresh token has been revoked",
            )
            raise InvalidRefreshTokenError(AuthErrorMessages.REFRESH_TOKEN_REVOKED)

        now = datetime.now(UTC)
        if session.expires_at < now:
            log.warning(
                "Refresh token validation failed: token has expired.",
                error_type="InvalidRefreshTokenError",
                original_error="Refresh token has expired",
            )
            raise InvalidRefreshTokenError(AuthErrorMessages.REFRESH_TOKEN_EXPIRED)

        # 新しいアクセストークンを生成
        access_token, expires_at = self._generate_access_token(session.user_id)

        return AuthTokenRefreshResponse(
            access_token=access_token,
            expires_at=expires_at,
        )

    # =========================================================================
    # ログアウト (/auth/logout)
    # =========================================================================

    def revoke_refresh_token(self, refresh_token: str) -> bool:
        """リフレッシュトークンを無効化"""
        refresh_token_hash = self._hash_token(refresh_token)
        result = self.repo.revoke_backend_session(refresh_token_hash)

        return result

    # =========================================================================
    # プライベートメソッド
    # =========================================================================

    def _generate_access_token(self, user_id: str) -> tuple[str, int]:
        """バックエンドAPIアクセストークン(JWT)を生成"""
        expires_at = datetime.now(UTC) + timedelta(
            hours=settings.ACCESS_TOKEN_EXPIRE_HOURS
        )
        expires_timestamp = int(expires_at.timestamp())

        payload = {
            "sub": user_id,  # Subject: user ID
            "type": "access",  # Token type
            "iat": datetime.now(UTC),  # Issued at
            "exp": expires_at,  # Expiration
        }

        token = jwt.encode(
            payload,
            settings.BACKEND_JWT_SECRET,
            algorithm="HS256",
        )

        return token, expires_timestamp

    def _generate_refresh_token(self) -> str:
        """セキュアなリフレッシュトークンを生成"""
        return secrets.token_urlsafe(64)

    def _hash_token(self, token: str) -> str:
        """トークンをSHA-256でハッシュ化"""
        return hashlib.sha256(token.encode()).hexdigest()

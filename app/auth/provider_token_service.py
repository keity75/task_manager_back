"""プロバイダートークン管理サービス

OAuth2プロバイダー(Google等)から取得したアクセストークンと
リフレッシュトークンの保存・取得・自動リフレッシュを担当する。

責務:
- プロバイダートークンの取得(復号化)
- 有効期限チェック(5分前にリフレッシュ)
- トークンのリフレッシュ(プロバイダーAPIコール)
- 新しいトークンの保存(暗号化)
"""

from datetime import UTC, datetime, timedelta

from app.auth.error_messages import AuthErrorMessages
from app.auth.exceptions import TokenRefreshError
from app.auth.repository import AuthRepository
from app.auth.schemas import GoogleTokenResponse, ProviderCredentials, ProviderTokens
from app.clients.http import HttpClient
from app.core import encryption
from app.core.logging import get_logger
from app.core.provider_config import get_provider_token_endpoint
from app.core.settings import settings

log = get_logger(__name__)


class ProviderTokenService:
    """プロバイダートークン管理サービス

    プロバイダー(Google, Microsoft等)から取得したアクセストークンと
    リフレッシュトークンの保存・取得・自動リフレッシュを担当する。
    """

    # 有効期限のバッファ(秒): トークンの期限切れ5分前にリフレッシュ
    TOKEN_REFRESH_BUFFER_SECONDS = 300

    # プロバイダーAPIから取得したexpires_inが存在しない場合のデフォルト値(秒)
    DEFAULT_TOKEN_EXPIRY_SECONDS = 3600  # 1時間

    def __init__(
        self, auth_repository: AuthRepository, http_client: HttpClient
    ) -> None:
        self.auth_repo = auth_repository
        self.http_client = http_client

    async def get_valid_access_token(self, user_id: str, provider: str) -> str:
        """有効なプロバイダーアクセストークンを取得

        期限切れの場合は自動でリフレッシュする。

        Args:
            user_id: ユーザーID
            provider: プロバイダーID(デフォルト: "google")

        Returns:
            復号化されたアクセストークン

        Raises:
            ProviderNotFoundError: プロバイダー情報が見つからない場合
            TokenRefreshError: リフレッシュに失敗した場合

        """
        # 1. AuthRepository経由でプロバイダートークンを取得
        token_data = self.auth_repo.get_provider_tokens(user_id, provider)

        # 2. 暗号化されたトークンを復号化
        access_token = encryption.decrypt(token_data.encrypted_access_token)
        refresh_token = encryption.decrypt(token_data.encrypted_refresh_token)

        # 3. 有効期限チェック(5分前 = 300秒)
        now = datetime.now(UTC)
        expires_at = token_data.expires_at
        buffer_time = timedelta(seconds=self.TOKEN_REFRESH_BUFFER_SECONDS)

        if now >= (expires_at - buffer_time):
            # 4. 期限切れ(または5分前)なら_refresh_provider_token()を呼び出し
            log.info(
                "Provider token is expiring soon, refreshing...",
                user_id=user_id,
                provider=provider,
                expires_at=expires_at.isoformat(),
            )

            refreshed_tokens = await self._refresh_provider_token(
                provider, refresh_token
            )

            # 5. 新しいトークンを暗号化してFirestoreに保存
            encrypted_new_access_token = encryption.encrypt(
                refreshed_tokens.access_token
            )
            self.auth_repo.update_provider_tokens(
                user_id=user_id,
                provider=provider,
                encrypted_access_token=encrypted_new_access_token,
                expires_at=refreshed_tokens.expires_at,
            )

            log.info(
                "Provider token refreshed successfully.",
                user_id=user_id,
                provider=provider,
                new_expires_at=refreshed_tokens.expires_at.isoformat(),
            )

            # 6. 新しいアクセストークンを返す
            return refreshed_tokens.access_token

        # トークンがまだ有効な場合はそのまま返す
        return access_token

    async def _refresh_provider_token(
        self, provider: str, refresh_token: str
    ) -> ProviderTokens:
        """プロバイダートークンをリフレッシュ

        Args:
            provider: プロバイダーID
            refresh_token: リフレッシュトークン(復号化済み)

        Returns:
            ProviderTokens: 新しいアクセストークンと有効期限

        Raises:
            TokenRefreshError: リフレッシュに失敗した場合

        """
        # 1. プロバイダー別のトークンエンドポイントを取得
        token_endpoint = get_provider_token_endpoint(provider)

        # 2. プロバイダー認証情報を取得
        credentials = self._get_provider_credentials(provider)

        # 3. HttpClient でPOSTリクエスト
        try:
            data: GoogleTokenResponse = await self.http_client.post_json(
                token_endpoint,
                data={
                    "grant_type": "refresh_token",
                    "client_id": credentials.client_id,
                    "client_secret": credentials.client_secret,
                    "refresh_token": refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            # 4. レスポンスから access_token, expires_in を取得
            new_access_token = data.get("access_token")
            expires_in = data.get("expires_in", self.DEFAULT_TOKEN_EXPIRY_SECONDS)

            if not new_access_token:
                log.warning(
                    "access_token not found in refresh response.",
                    provider=provider,
                    response_data=data,
                )
                raise TokenRefreshError(
                    AuthErrorMessages.ACCESS_TOKEN_NOT_FOUND_IN_RESPONSE
                )

            # 5. ProviderTokens オブジェクトを返す
            new_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

            return ProviderTokens(
                access_token=new_access_token,
                expires_at=new_expires_at,
            )

        except TokenRefreshError:
            raise
        except Exception as err:
            log.warning(
                "Provider token refresh error.",
                provider=provider,
                error_type=type(err).__name__,
                original_error=str(err),
            )
            raise TokenRefreshError(
                AuthErrorMessages.PROVIDER_TOKEN_REFRESH_FAILED
            ) from err

    def _get_provider_credentials(self, provider: str) -> ProviderCredentials:
        """プロバイダーのクライアント認証情報を取得

        Args:
            provider: プロバイダーID

        Returns:
            ProviderCredentials: client_id と client_secret

        Raises:
            ValueError: 未知のプロバイダーの場合

        """
        if provider == "google":
            return ProviderCredentials(
                client_id=settings.GOOGLE_CLIENT_ID,
                client_secret=settings.GOOGLE_CLIENT_SECRET,
            )

        message = AuthErrorMessages.UNKNOWN_PROVIDER_TEMPLATE.format(provider=provider)
        raise ValueError(message)

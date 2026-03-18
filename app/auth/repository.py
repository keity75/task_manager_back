from datetime import UTC, datetime

from google.cloud.firestore import Client as FirestoreClient
from google.cloud.firestore_v1.base_query import FieldFilter

from app.auth.error_messages import AuthErrorMessages
from app.auth.exceptions import (
    AuthRepositoryError,
    ProviderNotFoundError,
    TokenUpdateError,
)
from app.auth.schemas import BackendSession, ProviderTokenData
from app.core.logging import get_logger

log = get_logger(__name__)


class AuthRepository:
    """認証データアクセス層 (Firestore実装)"""

    def __init__(self, client: FirestoreClient) -> None:
        self.client = client

    # =========================================================================
    # ユーザー・認証プロバイダー関連
    # =========================================================================

    def find_user_by_provider_id(self, provider_account_id: str) -> str | None:
        """プロバイダーアカウントID(例: Googleのsub)でユーザーを検索してuserIdを返す"""
        if not provider_account_id:
            raise AuthRepositoryError(AuthErrorMessages.PROVIDER_ACCOUNT_ID_REQUIRED)

        try:
            auth_providers_ref = self.client.collection("auth_providers")
            query = auth_providers_ref.where(
                filter=FieldFilter("providerAccountId", "==", provider_account_id)
            )
            docs = query.get()
            if not docs:
                return None
            doc = docs[0]
            data = doc.to_dict()
            return data.get("userId")
        except Exception as err:
            log.warning(
                "Failed to find user by provider ID.",
                error_type=type(err).__name__,
                original_error=str(err),
            )
            raise AuthRepositoryError(AuthErrorMessages.FAILED_TO_FIND_USER) from err

    def get_user_name(self, user_id: str) -> str | None:
        """ユーザーIDからユーザー名を取得

        Args:
            user_id: ユーザーID

        Returns:
            ユーザー名(存在しない場合はNone)

        Raises:
            AuthRepositoryError: user_idが空の場合

        """
        if not user_id:
            raise AuthRepositoryError(AuthErrorMessages.USER_ID_REQUIRED)

        try:
            user_ref = self.client.collection("users").document(user_id)
            user_doc = user_ref.get()

            if not user_doc.exists:
                return None

            data = user_doc.to_dict()
            return data.get("name")
        except Exception as err:
            log.warning(
                "Failed to get user name.",
                user_id=user_id,
                error_type=type(err).__name__,
                original_error=str(err),
            )
            raise AuthRepositoryError(
                AuthErrorMessages.FAILED_TO_GET_USER_NAME
            ) from err

    def create_user(
        self,
        name: str,
        email: str,
        provider: str,
        provider_account_id: str,
        provider_access_token: str,
        provider_refresh_token: str,
        expires_at: datetime,
    ) -> str:
        """ユーザーと認証プロバイダー情報を作成し、userId を返す"""
        if not provider_account_id:
            raise AuthRepositoryError(AuthErrorMessages.PROVIDER_ACCOUNT_ID_REQUIRED)

        # expires_atがdatetime(UTC)であることを検証
        self._validate_expires_at(expires_at)

        try:
            users_col = self.client.collection("users")
            user_ref = users_col.document()  # Auto-ID
            user_id = user_ref.id

            now_utc = datetime.now(UTC)
            user_ref.set(
                {
                    "name": name,
                    "createdAt": now_utc,
                    "updatedAt": now_utc,
                }
            )

            self.client.collection("auth_providers").add(
                {
                    "userId": user_id,
                    "provider": provider,
                    "providerAccountId": provider_account_id,
                    "email": email,
                    "encryptedAccessToken": provider_access_token,
                    "encryptedRefreshToken": provider_refresh_token,
                    "expiresAt": expires_at,
                    "createdAt": now_utc,
                    "updatedAt": now_utc,
                }
            )
        except Exception as err:
            log.warning(
                "Failed to create user/auth_provider.",
                error_type=type(err).__name__,
                original_error=str(err),
            )
            raise AuthRepositoryError(AuthErrorMessages.FAILED_TO_CREATE_USER) from err
        else:
            return user_id

    def update_user_tokens(
        self,
        user_id: str,
        provider_access_token: str,
        provider_refresh_token: str,
        expires_at: datetime,
    ) -> None:
        """既存ユーザーのトークンを更新する"""
        if not user_id:
            raise TokenUpdateError(AuthErrorMessages.USER_ID_REQUIRED)

        # expires_atがdatetime(UTC)であることを検証
        self._validate_expires_at(expires_at)

        try:
            ref = self.client.collection("auth_providers")
            docs = ref.where(filter=FieldFilter("userId", "==", user_id)).get()
            if not docs:
                raise TokenUpdateError(AuthErrorMessages.AUTH_PROVIDER_RECORD_NOT_FOUND)
            doc_ref = docs[0].reference
            doc_ref.update(
                {
                    "encryptedAccessToken": provider_access_token,
                    "encryptedRefreshToken": provider_refresh_token,
                    "expiresAt": expires_at,
                    "updatedAt": datetime.now(UTC),
                }
            )
        except TokenUpdateError:
            raise
        except Exception as err:
            log.warning(
                "Failed to update tokens.",
                user_id=user_id,
                error_type=type(err).__name__,
                original_error=str(err),
            )
            raise TokenUpdateError(AuthErrorMessages.FAILED_TO_UPDATE_TOKENS) from err

    # =========================================================================
    # プロバイダートークン管理 (auth_providers コレクション)
    # =========================================================================

    def get_provider_tokens(self, user_id: str, provider: str) -> ProviderTokenData:
        """プロバイダートークンをFirestoreから取得する

        Args:
            user_id: ユーザーID
            provider: プロバイダーID (例: "google")

        Returns:
            ProviderTokenData: 暗号化されたトークンと有効期限

        Raises:
            AuthRepositoryError: user_idまたはproviderが空の場合
            ProviderNotFoundError: プロバイダー情報が見つからない場合

        """
        if not user_id:
            raise AuthRepositoryError(AuthErrorMessages.USER_ID_REQUIRED)
        if not provider:
            raise AuthRepositoryError(AuthErrorMessages.PROVIDER_REQUIRED)

        try:
            # auth_providersコレクションからuserIdとproviderで検索
            ref = self.client.collection("auth_providers")
            query = ref.where(filter=FieldFilter("userId", "==", user_id)).where(
                filter=FieldFilter("provider", "==", provider)
            )
            docs = query.get()

            if not docs:
                message = AuthErrorMessages.PROVIDER_NOT_FOUND_TEMPLATE.format(
                    provider=provider
                )
                raise ProviderNotFoundError(message)

            doc = docs[0]
            data = doc.to_dict()

            expires_at = data.get("expiresAt")
            # Firestoreから取得したexpires_atが契約通りdatetime(UTC)であることを検証
            self._validate_expires_at(expires_at)

        except ProviderNotFoundError:
            raise
        except Exception as err:
            log.warning(
                "Failed to get provider tokens.",
                user_id=user_id,
                provider=provider,
                error_type=type(err).__name__,
                original_error=str(err),
            )
            raise AuthRepositoryError(
                AuthErrorMessages.FAILED_TO_GET_PROVIDER_TOKENS
            ) from err

        return ProviderTokenData(
            encrypted_access_token=data.get("encryptedAccessToken", ""),
            encrypted_refresh_token=data.get("encryptedRefreshToken", ""),
            expires_at=expires_at,
        )

    def update_provider_tokens(
        self,
        user_id: str,
        provider: str,
        encrypted_access_token: str,
        expires_at: datetime,
    ) -> None:
        """プロバイダーアクセストークンを更新する

        Args:
            user_id: ユーザーID
            provider: プロバイダーID (例: "google")
            encrypted_access_token: 暗号化された新しいアクセストークン
            expires_at: 新しい有効期限

        Raises:
            AuthRepositoryError: パラメータが空の場合

        Note:
            encrypted_refresh_tokenは更新しない(長期間有効のため)

        """
        if not user_id:
            raise AuthRepositoryError(AuthErrorMessages.USER_ID_REQUIRED)
        if not provider:
            raise AuthRepositoryError(AuthErrorMessages.PROVIDER_REQUIRED)
        if not encrypted_access_token:
            raise AuthRepositoryError(AuthErrorMessages.ENCRYPTED_ACCESS_TOKEN_REQUIRED)

        # expires_atがdatetime(UTC)であることを検証
        self._validate_expires_at(expires_at)

        try:
            # auth_providersコレクションから該当ドキュメントを検索
            ref = self.client.collection("auth_providers")
            query = ref.where(filter=FieldFilter("userId", "==", user_id)).where(
                filter=FieldFilter("provider", "==", provider)
            )
            docs = query.get()

            if not docs:
                message = AuthErrorMessages.PROVIDER_NOT_FOUND_TEMPLATE.format(
                    provider=provider
                )
                raise ProviderNotFoundError(message)

            doc_ref = docs[0].reference

            # アクセストークンと有効期限のみ更新
            doc_ref.update(
                {
                    "encryptedAccessToken": encrypted_access_token,
                    "expiresAt": expires_at,
                    "updatedAt": datetime.now(UTC),
                }
            )

        except ProviderNotFoundError:
            raise
        except Exception as err:
            log.warning(
                "Failed to update provider tokens.",
                user_id=user_id,
                provider=provider,
                error_type=type(err).__name__,
                original_error=str(err),
            )
            raise AuthRepositoryError(
                AuthErrorMessages.FAILED_TO_UPDATE_PROVIDER_TOKENS
            ) from err

    # =========================================================================
    # バックエンドセッション関連 (backend_sessions コレクション)
    # =========================================================================

    def create_backend_session(
        self,
        user_id: str,
        refresh_token_hash: str,
        expires_at: datetime,
    ) -> str:
        """バックエンドセッション(リフレッシュトークンハッシュ)を作成する"""
        if not user_id:
            raise AuthRepositoryError(AuthErrorMessages.USER_ID_REQUIRED)
        if not refresh_token_hash:
            raise AuthRepositoryError(AuthErrorMessages.REFRESH_TOKEN_HASH_REQUIRED)

        # expires_atがdatetime(UTC)であることを検証
        self._validate_expires_at(expires_at)

        try:
            sessions_col = self.client.collection("backend_sessions")
            session_ref = sessions_col.document()  # Auto-ID
            session_id = session_ref.id

            now_utc = datetime.now(UTC)
            session_ref.set(
                {
                    "userId": user_id,
                    "refreshTokenHash": refresh_token_hash,
                    "expiresAt": expires_at,
                    "isRevoked": False,
                    "createdAt": now_utc,
                    "updatedAt": now_utc,
                }
            )
        except Exception as err:
            log.warning(
                "Failed to create backend session.",
                error_type=type(err).__name__,
                original_error=str(err),
            )
            raise AuthRepositoryError(
                AuthErrorMessages.FAILED_TO_CREATE_BACKEND_SESSION
            ) from err
        else:
            return session_id

    def find_backend_session_by_token_hash(
        self, refresh_token_hash: str
    ) -> BackendSession | None:
        """リフレッシュトークンハッシュでセッションを検索する"""
        if not refresh_token_hash:
            raise AuthRepositoryError(AuthErrorMessages.REFRESH_TOKEN_HASH_REQUIRED)

        try:
            sessions_ref = self.client.collection("backend_sessions")
            query = sessions_ref.where(
                filter=FieldFilter("refreshTokenHash", "==", refresh_token_hash)
            )
            docs = query.get()
            if not docs:
                return None
            doc = docs[0]
            data = doc.to_dict()

            expires_at = data.get("expiresAt")
            # Firestoreから取得したexpires_atが契約通りdatetime(UTC)であることを検証
            self._validate_expires_at(expires_at)

            return BackendSession(
                session_id=doc.id,
                user_id=data.get("userId"),
                refresh_token_hash=data.get("refreshTokenHash"),
                expires_at=expires_at,
                is_revoked=data.get("isRevoked", False),
            )
        except Exception as err:
            log.warning(
                "Failed to find backend session.",
                error_type=type(err).__name__,
                original_error=str(err),
            )
            raise AuthRepositoryError(
                AuthErrorMessages.FAILED_TO_FIND_BACKEND_SESSION
            ) from err

    def revoke_backend_session(self, refresh_token_hash: str) -> bool:
        """リフレッシュトークンハッシュでセッションを無効化する"""
        if not refresh_token_hash:
            raise AuthRepositoryError(AuthErrorMessages.REFRESH_TOKEN_HASH_REQUIRED)

        try:
            sessions_ref = self.client.collection("backend_sessions")
            query = sessions_ref.where(
                filter=FieldFilter("refreshTokenHash", "==", refresh_token_hash)
            )
            docs = query.get()
            if not docs:
                return False
            doc_ref = docs[0].reference
            doc_ref.update(
                {
                    "isRevoked": True,
                    "updatedAt": datetime.now(UTC),
                }
            )
        except Exception as err:
            log.warning(
                "Failed to revoke backend session.",
                error_type=type(err).__name__,
                original_error=str(err),
            )
            raise AuthRepositoryError(
                AuthErrorMessages.FAILED_TO_REVOKE_BACKEND_SESSION
            ) from err
        else:
            return True

    def revoke_all_user_sessions(self, user_id: str) -> int:
        """指定ユーザーの全アクティブセッションを無効化する

        Args:
            user_id: ユーザーID

        Returns:
            無効化したセッション数

        Raises:
            AuthRepositoryError: user_idが空の場合、またはFirestoreエラー

        """
        if not user_id:
            raise AuthRepositoryError(AuthErrorMessages.USER_ID_REQUIRED)

        try:
            sessions_ref = self.client.collection("backend_sessions")
            is_not_revoked = False
            query = sessions_ref.where(
                filter=FieldFilter("userId", "==", user_id)
            ).where(filter=FieldFilter("isRevoked", "==", is_not_revoked))
            docs = query.get()

            count = 0
            now_utc = datetime.now(UTC)
            for doc in docs:
                doc.reference.update(
                    {
                        "isRevoked": True,
                        "updatedAt": now_utc,
                    }
                )
                count += 1
        except Exception as err:
            log.warning(
                "Failed to revoke all user sessions.",
                user_id=user_id,
                error_type=type(err).__name__,
                original_error=str(err),
            )
            raise AuthRepositoryError(
                AuthErrorMessages.FAILED_TO_REVOKE_ALL_USER_SESSIONS
            ) from err
        else:
            return count

    # -------------------------------------------------------------------------
    # 内部ヘルパー
    # -------------------------------------------------------------------------

    def _validate_expires_at(self, expires_at: datetime) -> None:
        """expires_atがdatetime(UTC)であることを検証する

        契約違反の場合は正規化せず、即座にエラーをスローする。
        これにより、データの整合性を保証し、バグを早期に発見できる。

        Note:
            - expires_atは常にUTCタイムゾーンを持つdatetimeオブジェクトである必要がある
            - naive datetime(タイムゾーンなし)は許容しない
            - UTC以外のタイムゾーンも許容しない
            - Service層はこの契約に依存しており、型変換を担当する

        Raises:
            AuthRepositoryError: expires_atがdatetime(UTC)でない場合


        """
        if not isinstance(expires_at, datetime):
            raise AuthRepositoryError(AuthErrorMessages.EXPIRES_AT_MUST_BE_UTC_DATETIME)
        if expires_at.tzinfo is None:
            raise AuthRepositoryError(AuthErrorMessages.EXPIRES_AT_MUST_BE_UTC_DATETIME)
        if expires_at.tzinfo != UTC:
            # 契約違反として即座にエラーをスロー(正規化しない)
            raise AuthRepositoryError(AuthErrorMessages.EXPIRES_AT_MUST_BE_UTC_DATETIME)

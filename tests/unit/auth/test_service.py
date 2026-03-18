"""AuthService単体テスト

Repository層をモック化してAuthServiceのビジネスロジックをテストする。
"""

# ruff: noqa: S105, S106, SLF001, PLR2004

import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import jwt
import pytest

from app.auth.error_messages import AuthErrorMessages
from app.auth.exceptions import (
    AuthRepositoryError,
    AuthSyncError,
    EmailDomainNotAllowedError,
    InvalidRefreshTokenError,
    TokenUpdateError,
)
from app.auth.repository import AuthRepository
from app.auth.schemas import (
    AuthSyncRequest,
    AuthTokenRefreshRequest,
    BackendSession,
)
from app.auth.service import AuthService
from app.core.settings import settings


@pytest.fixture
def mock_repo() -> Mock:
    """AuthRepositoryのモックを作成"""
    return Mock(spec=AuthRepository)


@pytest.fixture
def auth_service(mock_repo: Mock) -> AuthService:
    """AuthServiceインスタンスを作成"""
    return AuthService(mock_repo)


class TestSyncAuth:
    """sync_authメソッドのテスト"""

    def test_new_user_flow(self, auth_service: AuthService, mock_repo: Mock) -> None:
        """正常系: 新規ユーザー作成フロー(is_new_user=True)"""
        # モック設定
        mock_repo.find_user_by_provider_id.return_value = None
        mock_repo.create_user.return_value = "new-user-id"
        mock_repo.create_backend_session.return_value = "session-id"

        # リクエスト作成
        request = AuthSyncRequest(
            provider="google",
            provider_account_id="new-provider-id",
            email="new@example.com",
            name="New User",
            provider_access_token="encrypted-access-token",
            provider_refresh_token="encrypted-refresh-token",
            provider_token_expires_at=int(
                (datetime.now(UTC) + timedelta(hours=1)).timestamp()
            ),
        )

        # テスト実行
        response = auth_service.sync_auth(request)

        # 検証: Repositoryメソッドが呼ばれる
        mock_repo.find_user_by_provider_id.assert_called_once_with("new-provider-id")
        mock_repo.create_user.assert_called_once()

        # expires_atがdatetime(UTC)として渡されていることを確認
        _, create_kwargs = mock_repo.create_user.call_args
        expires_at = create_kwargs["expires_at"]

        # 型とタイムゾーンの検証
        assert isinstance(expires_at, datetime)
        assert expires_at.tzinfo == UTC

        # 変換の正確性を検証(時間経過の影響を受けない方法)
        expected_datetime = datetime.fromtimestamp(
            request.provider_token_expires_at,
            tz=UTC,
        )
        assert expires_at == expected_datetime

        # 検証: レスポンスに正しい値が含まれる
        assert response.user_id == "new-user-id"
        assert response.is_new_user is True
        assert response.user_name == "New User"
        assert response.access_token is not None
        assert response.refresh_token is not None
        assert response.expires_at > 0

        # 検証: JWTアクセストークンが正しく生成される
        decoded = jwt.decode(
            response.access_token,
            settings.BACKEND_JWT_SECRET,
            algorithms=["HS256"],
        )
        assert decoded["sub"] == "new-user-id"
        assert decoded["type"] == "access"

    def test_existing_user_flow(
        self, auth_service: AuthService, mock_repo: Mock
    ) -> None:
        """正常系: 既存ユーザー更新フロー(is_new_user=False)"""
        # モック設定
        mock_repo.find_user_by_provider_id.return_value = "existing-user-id"
        mock_repo.update_user_tokens.return_value = None
        mock_repo.get_user_name.return_value = "Existing User"
        mock_repo.create_backend_session.return_value = "session-id"

        # リクエスト作成
        request = AuthSyncRequest(
            provider="google",
            provider_account_id="existing-provider-id",
            email="existing@example.com",
            name="Request Name",
            provider_access_token="encrypted-access-token",
            provider_refresh_token="encrypted-refresh-token",
            provider_token_expires_at=int(
                (datetime.now(UTC) + timedelta(hours=1)).timestamp()
            ),
        )

        # テスト実行
        response = auth_service.sync_auth(request)

        # 検証: Repositoryメソッドが呼ばれる
        mock_repo.find_user_by_provider_id.assert_called_once_with(
            "existing-provider-id"
        )
        mock_repo.update_user_tokens.assert_called_once()
        mock_repo.revoke_all_user_sessions.assert_called_once_with("existing-user-id")
        mock_repo.get_user_name.assert_called_once_with("existing-user-id")

        # expires_atがdatetime(UTC)として渡されていることを確認
        _, update_kwargs = mock_repo.update_user_tokens.call_args
        expires_at = update_kwargs["expires_at"]

        # 型とタイムゾーンの検証
        assert isinstance(expires_at, datetime)
        assert expires_at.tzinfo == UTC

        # 変換の正確性を検証(時間経過の影響を受けない方法)
        expected_datetime = datetime.fromtimestamp(
            request.provider_token_expires_at,
            tz=UTC,
        )
        assert expires_at == expected_datetime

        # 検証: レスポンスに正しい値が含まれる
        assert response.user_id == "existing-user-id"
        assert response.is_new_user is False
        assert response.user_name == "Existing User"
        assert response.access_token is not None
        assert response.refresh_token is not None
        assert response.expires_at > 0

        # 検証: JWTアクセストークンが正しく生成される
        decoded = jwt.decode(
            response.access_token,
            settings.BACKEND_JWT_SECRET,
            algorithms=["HS256"],
        )
        assert decoded["sub"] == "existing-user-id"
        assert decoded["type"] == "access"

    def test_existing_user_no_name_in_db(
        self, auth_service: AuthService, mock_repo: Mock
    ) -> None:
        """正常系: 既存ユーザーでDBに名前がない場合、リクエストの名前を使用"""
        # モック設定
        mock_repo.find_user_by_provider_id.return_value = "existing-user-id"
        mock_repo.update_user_tokens.return_value = None
        mock_repo.get_user_name.return_value = None
        mock_repo.create_backend_session.return_value = "session-id"

        # リクエスト作成
        request = AuthSyncRequest(
            provider="google",
            provider_account_id="existing-provider-id",
            email="existing@example.com",
            name="Request Name",
            provider_access_token="encrypted-access-token",
            provider_refresh_token="encrypted-refresh-token",
            provider_token_expires_at=int(
                (datetime.now(UTC) + timedelta(hours=1)).timestamp()
            ),
        )

        # テスト実行
        response = auth_service.sync_auth(request)

        # 検証
        assert response.user_name == "Request Name"

    def test_existing_user_no_name_anywhere(
        self, auth_service: AuthService, mock_repo: Mock
    ) -> None:
        """正常系: 既存ユーザーでDBにもリクエストにも名前がない場合、Noneを返す"""
        # モック設定
        mock_repo.find_user_by_provider_id.return_value = "existing-user-id"
        mock_repo.update_user_tokens.return_value = None
        mock_repo.get_user_name.return_value = None
        mock_repo.create_backend_session.return_value = "session-id"

        # リクエスト作成(nameを空文字列に)
        request = AuthSyncRequest(
            provider="google",
            provider_account_id="existing-provider-id",
            email="existing@example.com",
            name="",
            provider_access_token="encrypted-access-token",
            provider_refresh_token="encrypted-refresh-token",
            provider_token_expires_at=int(
                (datetime.now(UTC) + timedelta(hours=1)).timestamp()
            ),
        )

        # テスト実行
        response = auth_service.sync_auth(request)

        # 検証
        assert response.user_name is None

    def test_find_user_by_provider_id_error(
        self, auth_service: AuthService, mock_repo: Mock
    ) -> None:
        """異常系: Repositoryのfind_user_by_provider_idが例外を発生した場合、AuthSyncErrorを発生"""
        # モック設定
        mock_repo.find_user_by_provider_id.side_effect = AuthRepositoryError(
            "Repository error"
        )

        # リクエスト作成
        request = AuthSyncRequest(
            provider="google",
            provider_account_id="test-provider-id",
            email="test@example.com",
            name="Test User",
            provider_access_token="encrypted-access-token",
            provider_refresh_token="encrypted-refresh-token",
            provider_token_expires_at=int(
                (datetime.now(UTC) + timedelta(hours=1)).timestamp()
            ),
        )

        # テスト実行
        with pytest.raises(AuthSyncError):
            auth_service.sync_auth(request)

    def test_create_user_error(
        self, auth_service: AuthService, mock_repo: Mock
    ) -> None:
        """異常系: Repositoryのcreate_userが例外を発生した場合、AuthSyncErrorを発生"""
        # モック設定
        mock_repo.find_user_by_provider_id.return_value = None
        mock_repo.create_user.side_effect = AuthRepositoryError("Repository error")

        # リクエスト作成
        request = AuthSyncRequest(
            provider="google",
            provider_account_id="test-provider-id",
            email="test@example.com",
            name="Test User",
            provider_access_token="encrypted-access-token",
            provider_refresh_token="encrypted-refresh-token",
            provider_token_expires_at=int(
                (datetime.now(UTC) + timedelta(hours=1)).timestamp()
            ),
        )

        # テスト実行
        with pytest.raises(AuthSyncError):
            auth_service.sync_auth(request)

    def test_update_user_tokens_error(
        self, auth_service: AuthService, mock_repo: Mock
    ) -> None:
        """異常系: Repositoryのupdate_user_tokensが例外を発生した場合、AuthSyncErrorを発生"""
        # モック設定
        mock_repo.find_user_by_provider_id.return_value = "existing-user-id"
        mock_repo.update_user_tokens.side_effect = TokenUpdateError("Update error")

        # リクエスト作成
        request = AuthSyncRequest(
            provider="google",
            provider_account_id="test-provider-id",
            email="test@example.com",
            name="Test User",
            provider_access_token="encrypted-access-token",
            provider_refresh_token="encrypted-refresh-token",
            provider_token_expires_at=int(
                (datetime.now(UTC) + timedelta(hours=1)).timestamp()
            ),
        )

        # テスト実行
        with pytest.raises(AuthSyncError):
            auth_service.sync_auth(request)

    def test_create_backend_session_error(
        self, auth_service: AuthService, mock_repo: Mock
    ) -> None:
        """異常系: Repositoryのcreate_backend_sessionが例外を発生した場合、AuthSyncErrorを発生"""
        # モック設定
        mock_repo.find_user_by_provider_id.return_value = None
        mock_repo.create_user.return_value = "new-user-id"
        mock_repo.create_backend_session.side_effect = AuthRepositoryError(
            "Session error"
        )

        # リクエスト作成
        request = AuthSyncRequest(
            provider="google",
            provider_account_id="test-provider-id",
            email="test@example.com",
            name="Test User",
            provider_access_token="encrypted-access-token",
            provider_refresh_token="encrypted-refresh-token",
            provider_token_expires_at=int(
                (datetime.now(UTC) + timedelta(hours=1)).timestamp()
            ),
        )

        # テスト実行
        with pytest.raises(AuthSyncError):
            auth_service.sync_auth(request)

    def test_disallowed_email_domain_raises_email_domain_not_allowed_error(
        self, auth_service: AuthService, mock_repo: Mock
    ) -> None:
        """異常系: 許可されていないメールドメインの場合、EmailDomainNotAllowedErrorを送出"""
        # Arrange
        request = AuthSyncRequest(
            provider="google",
            provider_account_id="test-provider-id",
            email="user@other.com",
            name="Test User",
            provider_access_token="encrypted-access-token",
            provider_refresh_token="encrypted-refresh-token",
            provider_token_expires_at=int(
                (datetime.now(UTC) + timedelta(hours=1)).timestamp()
            ),
        )

        # Act & Assert
        with (
            patch.object(settings, "ALLOWED_EMAIL_DOMAINS", ["allowed.com"]),
            pytest.raises(EmailDomainNotAllowedError),
        ):
            auth_service.sync_auth(request)

        # Assert: Repositoryメソッドが呼ばれないことを確認
        mock_repo.find_user_by_provider_id.assert_not_called()
        mock_repo.create_user.assert_not_called()


class TestRefreshToken:
    """refresh_tokenメソッドのテスト"""

    def test_valid_refresh_token(
        self, auth_service: AuthService, mock_repo: Mock
    ) -> None:
        """正常系: 有効なリフレッシュトークンで新しいアクセストークンを発行"""
        # モック設定
        refresh_token = "valid-refresh-token"
        refresh_token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

        mock_session = BackendSession(
            session_id="session-id",
            user_id="test-user-id",
            refresh_token_hash=refresh_token_hash,
            expires_at=datetime.now(UTC) + timedelta(days=30),
            is_revoked=False,
        )
        mock_repo.find_backend_session_by_token_hash.return_value = mock_session

        # リクエスト作成
        request = AuthTokenRefreshRequest(refresh_token=refresh_token)

        # テスト実行
        response = auth_service.refresh_token(request)

        # 検証: Repositoryメソッドが呼ばれる
        mock_repo.find_backend_session_by_token_hash.assert_called_once_with(
            refresh_token_hash
        )

        # 検証: レスポンスに正しい値が含まれる
        assert response.access_token is not None
        assert response.expires_at > 0

        # 検証: 新しいアクセストークンが正しく生成される
        decoded = jwt.decode(
            response.access_token,
            settings.BACKEND_JWT_SECRET,
            algorithms=["HS256"],
        )
        assert decoded["sub"] == "test-user-id"
        assert decoded["type"] == "access"

    def test_nonexistent_token_hash(
        self, auth_service: AuthService, mock_repo: Mock
    ) -> None:
        """異常系: 存在しないトークンハッシュの場合、InvalidRefreshTokenErrorを発生"""
        # モック設定
        mock_repo.find_backend_session_by_token_hash.return_value = None

        # リクエスト作成
        request = AuthTokenRefreshRequest(refresh_token="nonexistent-token")

        # テスト実行
        with pytest.raises(
            InvalidRefreshTokenError,
            match=AuthErrorMessages.INVALID_OR_EXPIRED_REFRESH_TOKEN,
        ):
            auth_service.refresh_token(request)

    def test_revoked_session(self, auth_service: AuthService, mock_repo: Mock) -> None:
        """異常系: セッションが無効化されている場合、InvalidRefreshTokenErrorを発生"""
        # モック設定
        refresh_token = "revoked-token"
        refresh_token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

        mock_session = BackendSession(
            session_id="session-id",
            user_id="test-user-id",
            refresh_token_hash=refresh_token_hash,
            expires_at=datetime.now(UTC) + timedelta(days=30),
            is_revoked=True,  # 無効化されている
        )
        mock_repo.find_backend_session_by_token_hash.return_value = mock_session

        # リクエスト作成
        request = AuthTokenRefreshRequest(refresh_token=refresh_token)

        # テスト実行
        with pytest.raises(
            InvalidRefreshTokenError, match=AuthErrorMessages.REFRESH_TOKEN_REVOKED
        ):
            auth_service.refresh_token(request)

    def test_expired_session(self, auth_service: AuthService, mock_repo: Mock) -> None:
        """異常系: セッションが期限切れの場合、InvalidRefreshTokenErrorを発生"""
        # モック設定
        refresh_token = "expired-token"
        refresh_token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

        mock_session = BackendSession(
            session_id="session-id",
            user_id="test-user-id",
            refresh_token_hash=refresh_token_hash,
            expires_at=datetime.now(UTC) - timedelta(days=1),  # 期限切れ
            is_revoked=False,
        )
        mock_repo.find_backend_session_by_token_hash.return_value = mock_session

        # リクエスト作成
        request = AuthTokenRefreshRequest(refresh_token=refresh_token)

        # テスト実行
        with pytest.raises(
            InvalidRefreshTokenError, match=AuthErrorMessages.REFRESH_TOKEN_EXPIRED
        ):
            auth_service.refresh_token(request)

    def test_find_backend_session_error(
        self, auth_service: AuthService, mock_repo: Mock
    ) -> None:
        """異常系: Repositoryのfind_backend_session_by_token_hashが例外を発生した場合、その例外を伝播する"""
        # モック設定
        mock_repo.find_backend_session_by_token_hash.side_effect = AuthRepositoryError(
            "Repository error"
        )

        # リクエスト作成
        request = AuthTokenRefreshRequest(refresh_token="test-token")

        # テスト実行: AuthRepositoryError がそのまま伝播されることを確認
        with pytest.raises(AuthRepositoryError):
            auth_service.refresh_token(request)


class TestRevokeRefreshToken:
    """revoke_refresh_tokenメソッドのテスト"""

    def test_revoke_existing_token(
        self, auth_service: AuthService, mock_repo: Mock
    ) -> None:
        """正常系: 存在するリフレッシュトークンを無効化してTrueを返す"""
        # モック設定
        refresh_token = "existing-token"
        refresh_token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

        mock_repo.revoke_backend_session.return_value = True

        # テスト実行
        result = auth_service.revoke_refresh_token(refresh_token)

        # 検証: Repositoryメソッドが呼ばれる
        mock_repo.revoke_backend_session.assert_called_once_with(refresh_token_hash)

        # 検証: 結果がTrueである
        assert result is True

    def test_revoke_nonexistent_token(
        self, auth_service: AuthService, mock_repo: Mock
    ) -> None:
        """正常系: 存在しないリフレッシュトークンでFalseを返す"""
        # モック設定
        mock_repo.revoke_backend_session.return_value = False

        # テスト実行
        refresh_token = "nonexistent-token"
        result = auth_service.revoke_refresh_token(refresh_token)

        # 検証: Repositoryメソッドが正しいハッシュで呼ばれる
        refresh_token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        mock_repo.revoke_backend_session.assert_called_once_with(refresh_token_hash)

        # 検証: 結果がFalseである
        assert result is False

    def test_revoke_backend_session_error(
        self, auth_service: AuthService, mock_repo: Mock
    ) -> None:
        """異常系: Repositoryのrevoke_backend_sessionが例外を発生した場合、例外を再スロー"""
        # モック設定
        mock_repo.revoke_backend_session.side_effect = AuthRepositoryError(
            "Repository error"
        )

        # テスト実行
        with pytest.raises(AuthRepositoryError):
            auth_service.revoke_refresh_token("test-token")


class TestGenerateAccessToken:
    """_generate_access_tokenメソッドのテスト(プライベートメソッド)"""

    def test_generate_valid_jwt(self, auth_service: AuthService) -> None:
        """正常系: 正しいJWTトークンと有効期限タイムスタンプを返す"""
        user_id = "test-user-id"

        # テスト実行
        token, expires_at = auth_service._generate_access_token(user_id)

        # 検証: トークンが文字列である
        assert isinstance(token, str)
        assert isinstance(expires_at, int)

    def test_jwt_payload_fields(self, auth_service: AuthService) -> None:
        """正常系: JWTペイロードにsub(user_id)、type("access")、iat、expが含まれる"""
        user_id = "test-user-id"

        # テスト実行
        token, _ = auth_service._generate_access_token(user_id)

        # 検証: JWTをデコードしてペイロードを確認
        decoded = jwt.decode(token, settings.BACKEND_JWT_SECRET, algorithms=["HS256"])
        assert decoded["sub"] == user_id
        assert decoded["type"] == "access"
        assert "iat" in decoded
        assert "exp" in decoded

    def test_expires_at_calculation(self, auth_service: AuthService) -> None:
        """正常系: 有効期限がsettings.ACCESS_TOKEN_EXPIRE_HOURSに基づいて計算される"""
        user_id = "test-user-id"

        # テスト実行
        _, expires_at = auth_service._generate_access_token(user_id)

        # 検証: 有効期限が現在時刻 + ACCESS_TOKEN_EXPIRE_HOURS
        expected_expires_at = datetime.now(UTC) + timedelta(
            hours=settings.ACCESS_TOKEN_EXPIRE_HOURS
        )
        assert abs(expires_at - int(expected_expires_at.timestamp())) < 2

    def test_jwt_signature(self, auth_service: AuthService) -> None:
        """正常系: JWTがsettings.BACKEND_JWT_SECRETで署名される"""
        user_id = "test-user-id"

        # テスト実行
        token, _ = auth_service._generate_access_token(user_id)

        # 検証: 正しいシークレットでデコードできる
        decoded = jwt.decode(token, settings.BACKEND_JWT_SECRET, algorithms=["HS256"])
        assert decoded["sub"] == user_id

        # 検証: 誤ったシークレットではデコードできない
        with pytest.raises(jwt.InvalidSignatureError):
            jwt.decode(
                token,
                "wrong-secret-key-with-minimum-32-bytes!!",
                algorithms=["HS256"],
            )


class TestGenerateRefreshToken:
    """_generate_refresh_tokenメソッドのテスト(プライベートメソッド)"""

    def test_generate_secure_token(self, auth_service: AuthService) -> None:
        """正常系: セキュアなランダムトークン(64バイト、URL-safe)を生成"""
        # テスト実行
        token = auth_service._generate_refresh_token()

        # 検証: トークンが文字列である
        assert isinstance(token, str)
        # 検証: トークンが空でない
        assert len(token) > 0

    def test_generate_different_tokens(self, auth_service: AuthService) -> None:
        """正常系: 毎回異なるトークンを生成する"""
        # テスト実行
        token1 = auth_service._generate_refresh_token()
        token2 = auth_service._generate_refresh_token()

        # 検証: 2つのトークンが異なる
        assert token1 != token2


class TestHashToken:
    """_hash_tokenメソッドのテスト(プライベートメソッド)"""

    def test_hash_token_sha256(self, auth_service: AuthService) -> None:
        """正常系: トークンをSHA-256でハッシュ化してhex文字列を返す"""
        token = "test-token"

        # テスト実行
        hashed = auth_service._hash_token(token)

        # 検証: ハッシュが文字列である
        assert isinstance(hashed, str)
        # 検証: ハッシュがSHA-256のhex文字列である(64文字)
        assert len(hashed) == 64

    def test_same_token_same_hash(self, auth_service: AuthService) -> None:
        """正常系: 同じトークンは常に同じハッシュを返す"""
        token = "test-token"

        # テスト実行
        hash1 = auth_service._hash_token(token)
        hash2 = auth_service._hash_token(token)

        # 検証
        assert hash1 == hash2

    def test_different_tokens_different_hashes(self, auth_service: AuthService) -> None:
        """正常系: 異なるトークンは異なるハッシュを返す"""
        token1 = "test-token-1"
        token2 = "test-token-2"

        # テスト実行
        hash1 = auth_service._hash_token(token1)
        hash2 = auth_service._hash_token(token2)

        # 検証
        assert hash1 != hash2

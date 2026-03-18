"""認証APIの結合テスト

テストコードでの例外使用(TRY002)は、Firestoreエラーをシミュレートするために必要。
"""
# ruff: noqa: TRY002

import hashlib
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import jwt
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.auth.error_messages import AuthErrorMessages
from app.core.dependencies import get_db
from app.core.schemas import ErrorResponse, SuccessResponse
from app.core.settings import settings
from app.main import app

# テスト用定数
TIMESTAMP_COMPARISON_TOLERANCE_SECONDS = 2
TEST_CONNECTION_ERROR_MESSAGE = "Connection error"

API_V1_PREFIX = f"{settings.API_PREFIX}{settings.API_VERSION}"


@pytest.fixture
def client(db: firestore.Client) -> Generator[TestClient]:
    """FastAPI TestClient を提供するフィクスチャ。

    - Firestore Emulator 用の db フィクスチャを FastAPI の依存関係に注入する。
    - lifespan(Firestore クライアント初期化)はスキップし、テスト専用の db を使用する。
    """

    def _get_test_db() -> firestore.Client:
        return db

    app.dependency_overrides[get_db] = _get_test_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _build_auth_sync_payload(
    provider_account_id: str,
    *,
    email: str = "user@example.com",
    name: str = "Test User",
    provider: str = "google",
) -> dict[str, Any]:
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    return {
        "provider": provider,
        "providerAccountId": provider_account_id,
        "email": email,
        "name": name,
        "providerAccessToken": "encrypted-access-token",
        "providerRefreshToken": "encrypted-refresh-token",
        "providerTokenExpiresAt": int(expires_at.timestamp()),
    }


def _auth_sync_and_get_tokens(
    client: TestClient,
    provider_account_id: str = "provider-id-refresh",
) -> tuple[str, str, str]:
    """`/auth/sync` を呼び出して userId / accessToken / refreshToken を取得するヘルパー。"""
    url = f"{API_V1_PREFIX}/auth/sync"
    payload = _build_auth_sync_payload(provider_account_id)

    response = client.post(url, json=payload)
    assert response.status_code == status.HTTP_200_OK

    body: SuccessResponse[dict[str, Any]] = SuccessResponse.model_validate(
        response.json()
    )
    assert body.status == "success"

    data = body.data  # type: ignore[assignment]
    assert isinstance(data, dict)

    user_id = data["userId"]
    access_token = data["accessToken"]
    refresh_token = data["refreshToken"]
    assert isinstance(user_id, str)
    assert user_id != ""
    assert isinstance(access_token, str)
    assert access_token != ""
    assert isinstance(refresh_token, str)
    assert refresh_token != ""

    return user_id, access_token, refresh_token


# =============================================================================
# /auth/sync の結合テスト
# =============================================================================


class TestAuthSync:
    """`/api/v1/auth/sync` の結合テスト。"""

    def test_sync_auth_creates_new_user(
        self,
        client: TestClient,
        db: firestore.Client,
    ) -> None:
        """正常系: 新規ユーザー登録フロー。"""
        url = f"{API_V1_PREFIX}/auth/sync"
        payload = _build_auth_sync_payload("provider-id-new")

        response = client.post(url, json=payload)
        assert response.status_code == status.HTTP_200_OK

        # レスポンス契約 (SuccessResponse[AuthSyncResponse] 相当) の主要項目を検証
        body: SuccessResponse[dict[str, Any]] = SuccessResponse.model_validate(
            response.json()
        )
        assert body.status == "success"

        auth_data = body.data  # type: ignore[assignment]
        assert isinstance(auth_data, dict)
        assert auth_data["isNewUser"] is True

        user_id = auth_data["userId"]
        assert isinstance(user_id, str)
        assert user_id != ""

        access_token = auth_data["accessToken"]
        refresh_token = auth_data["refreshToken"]
        expires_at = auth_data["expiresAt"]
        assert isinstance(access_token, str)
        assert access_token != ""
        assert isinstance(refresh_token, str)
        assert refresh_token != ""
        assert isinstance(expires_at, int)
        assert expires_at > 0

        # Firestore 上に新規ユーザーが作成されていることを検証
        user_doc = db.collection("users").document(user_id).get()
        assert user_doc.exists
        user_data = user_doc.to_dict()
        assert user_data is not None
        assert user_data["name"] == "Test User"
        assert isinstance(user_data.get("createdAt"), datetime)
        assert isinstance(user_data.get("updatedAt"), datetime)

        # auth_providers にプロバイダー情報が保存されていることを検証
        providers = (
            db.collection("auth_providers")
            .where(filter=FieldFilter("userId", "==", user_id))
            .get()
        )
        assert len(providers) == 1
        provider_data = providers[0].to_dict()
        assert provider_data is not None
        assert provider_data["userId"] == user_id
        assert provider_data["providerAccountId"] == "provider-id-new"
        assert provider_data["encryptedAccessToken"] == "encrypted-access-token"
        assert provider_data["encryptedRefreshToken"] == "encrypted-refresh-token"
        expires_at_utc = provider_data["expiresAt"]
        assert isinstance(expires_at_utc, datetime)
        expected_expires_at = datetime.fromtimestamp(
            payload["providerTokenExpiresAt"],
            tz=UTC,
        )
        assert (
            abs(expires_at_utc.timestamp() - expected_expires_at.timestamp())
            < TIMESTAMP_COMPARISON_TOLERANCE_SECONDS
        )

        # backend_sessions にセッションが1件作成され、isRevoked=False であることを検証
        sessions = (
            db.collection("backend_sessions")
            .where(filter=FieldFilter("userId", "==", user_id))
            .get()
        )
        assert len(sessions) == 1
        session_data = sessions[0].to_dict()
        assert session_data is not None
        assert session_data["userId"] == user_id
        assert session_data["isRevoked"] is False

    def test_sync_auth_updates_existing_user(
        self,
        client: TestClient,
        db: firestore.Client,
    ) -> None:
        """正常系: 既存ユーザー更新フロー。"""
        user_ref = db.collection("users").document()
        user_id = user_ref.id
        user_ref.set({"name": "Existing User", "createdAt": datetime.now(UTC)})

        db.collection("auth_providers").add(
            {
                "userId": user_id,
                "provider": "google",
                "providerAccountId": "provider-id-existing",
                "email": "old@example.com",
                "encryptedAccessToken": "old-access-token",
                "encryptedRefreshToken": "old-refresh-token",
                "expiresAt": datetime.now(UTC),
            }
        )

        url = f"{API_V1_PREFIX}/auth/sync"
        payload = _build_auth_sync_payload(
            "provider-id-existing",
            email="new@example.com",
            name="Request Name",
        )

        response = client.post(url, json=payload)
        assert response.status_code == status.HTTP_200_OK

        # レスポンス契約 (SuccessResponse[AuthSyncResponse] 相当) の主要項目を検証
        body: SuccessResponse[dict[str, Any]] = SuccessResponse.model_validate(
            response.json()
        )
        assert body.status == "success"

        data = body.data  # type: ignore[assignment]
        assert isinstance(data, dict)
        assert data["isNewUser"] is False
        assert data["userId"] == user_id
        assert data["userName"] == "Existing User"

        providers = (
            db.collection("auth_providers")
            .where(filter=FieldFilter("userId", "==", user_id))
            .get()
        )
        assert len(providers) == 1
        provider_data = providers[0].to_dict()
        assert provider_data is not None
        assert provider_data["encryptedAccessToken"] == "encrypted-access-token"
        assert provider_data["encryptedRefreshToken"] == "encrypted-refresh-token"

    def test_sync_auth_validation_error(
        self,
        client: TestClient,
    ) -> None:
        """異常系: バリデーションエラー (必須フィールド不足で422)。"""
        url = f"{API_V1_PREFIX}/auth/sync"
        payload: dict[str, Any] = {
            "providerAccountId": "missing-provider",
        }

        response = client.post(url, json=payload)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.status == "error"
        assert body.error.code == "VALIDATION_ERROR"

    def test_sync_auth_firestore_error_returns_500(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        db: firestore.Client,
    ) -> None:
        """異常系: Firestore 障害により AuthRepositoryError が発生した場合は 500 を返す。"""

        def _broken_collection(*_args: Any, **_kwargs: Any) -> Any:
            raise Exception(TEST_CONNECTION_ERROR_MESSAGE)

        monkeypatch.setattr(db, "collection", _broken_collection)

        url = f"{API_V1_PREFIX}/auth/sync"
        payload = _build_auth_sync_payload("provider-id-error")

        response = client.post(url, json=payload)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.status == "error"
        assert body.error.code == "AUTH_REPOSITORY_ERROR"


# =============================================================================
# /auth/token/refresh の結合テスト
# =============================================================================


class TestAuthTokenRefresh:
    """`/api/v1/auth/token/refresh` の結合テスト。"""

    def test_token_refresh_success(
        self,
        client: TestClient,
    ) -> None:
        """正常系: 有効なリフレッシュトークンで新しいアクセストークンを発行。"""
        # Arrange: /auth/sync でセッションを作成
        user_id, _access_token, refresh_token = _auth_sync_and_get_tokens(client)

        url = f"{API_V1_PREFIX}/auth/token/refresh"
        payload: dict[str, Any] = {"refreshToken": refresh_token}

        # Act
        response = client.post(url, json=payload)

        # Assert: レスポンス契約と JWT 内容
        assert response.status_code == status.HTTP_200_OK
        body: SuccessResponse[dict[str, Any]] = SuccessResponse.model_validate(
            response.json()
        )
        assert body.status == "success"

        data = body.data  # type: ignore[assignment]
        assert isinstance(data, dict)
        new_access_token = data["accessToken"]
        expires_at = data["expiresAt"]
        assert isinstance(new_access_token, str)
        assert new_access_token != ""
        assert isinstance(expires_at, int)
        assert expires_at > 0

        decoded = jwt.decode(
            new_access_token,
            settings.BACKEND_JWT_SECRET,
            algorithms=["HS256"],
        )
        assert decoded["sub"] == user_id
        assert decoded["type"] == "access"

    def test_token_refresh_nonexistent_session(
        self,
        client: TestClient,
    ) -> None:
        """異常系: 存在しないリフレッシュトークンの場合、401 Unauthorized。"""
        url = f"{API_V1_PREFIX}/auth/token/refresh"
        payload: dict[str, Any] = {"refreshToken": "nonexistent-refresh-token"}

        response = client.post(url, json=payload)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.status == "error"
        assert body.error.code == "INVALID_REFRESH_TOKEN"
        assert body.error.message == AuthErrorMessages.INVALID_OR_EXPIRED_REFRESH_TOKEN

    def test_token_refresh_revoked_session(
        self,
        client: TestClient,
        db: firestore.Client,
    ) -> None:
        """異常系: isRevoked=True のセッションは 401 (リフレッシュトークン無効化済み)。"""
        # Arrange: 正常なセッションを作成
        user_id, _access_token, refresh_token = _auth_sync_and_get_tokens(client)

        # backend_sessions の該当セッションを revoked に更新
        refresh_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        sessions = (
            db.collection("backend_sessions")
            .where(filter=FieldFilter("userId", "==", user_id))
            .where(filter=FieldFilter("refreshTokenHash", "==", refresh_hash))
            .get()
        )
        assert len(sessions) == 1
        session_ref = sessions[0].reference
        session_ref.update({"isRevoked": True})

        url = f"{API_V1_PREFIX}/auth/token/refresh"
        payload: dict[str, Any] = {"refreshToken": refresh_token}

        # Act
        response = client.post(url, json=payload)

        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.status == "error"
        assert body.error.code == "INVALID_REFRESH_TOKEN"
        assert body.error.message == AuthErrorMessages.REFRESH_TOKEN_REVOKED

    def test_token_refresh_expired_session(
        self,
        client: TestClient,
        db: firestore.Client,
    ) -> None:
        """異常系: 有効期限切れのセッションは 401。"""
        # Arrange: 正常なセッションを作成
        user_id, _access_token, refresh_token = _auth_sync_and_get_tokens(client)

        # backend_sessions の expiresAt を過去日に変更
        refresh_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        sessions = (
            db.collection("backend_sessions")
            .where(filter=FieldFilter("userId", "==", user_id))
            .where(filter=FieldFilter("refreshTokenHash", "==", refresh_hash))
            .get()
        )
        assert len(sessions) == 1
        session_ref = sessions[0].reference
        expired_at = datetime.now(UTC) - timedelta(days=1)
        session_ref.update({"expiresAt": expired_at})

        url = f"{API_V1_PREFIX}/auth/token/refresh"
        payload: dict[str, Any] = {"refreshToken": refresh_token}

        # Act
        response = client.post(url, json=payload)

        # Assert
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.status == "error"
        assert body.error.code == "INVALID_REFRESH_TOKEN"
        assert body.error.message == AuthErrorMessages.REFRESH_TOKEN_EXPIRED

    def test_token_refresh_firestore_error_returns_500(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        db: firestore.Client,
    ) -> None:
        """異常系: Firestore 障害により AuthRepositoryError が発生した場合は 500 を返す。"""

        def _broken_collection(*_args: Any, **_kwargs: Any) -> Any:
            raise Exception(TEST_CONNECTION_ERROR_MESSAGE)

        monkeypatch.setattr(db, "collection", _broken_collection)

        url = f"{API_V1_PREFIX}/auth/token/refresh"
        payload: dict[str, Any] = {"refreshToken": "any-token"}

        response = client.post(url, json=payload)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.status == "error"
        assert body.error.code == "AUTH_REPOSITORY_ERROR"


# =============================================================================
# /auth/logout の結合テスト
# =============================================================================


class TestAuthLogout:
    """`/api/v1/auth/logout` の結合テスト。"""

    def test_logout_revokes_session(
        self,
        client: TestClient,
        db: firestore.Client,
    ) -> None:
        """正常系: 既存セッションを revoke して 200 を返す。"""
        # Arrange: /auth/sync でセッションを作成
        user_id, _access_token, refresh_token = _auth_sync_and_get_tokens(client)
        refresh_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

        url = f"{API_V1_PREFIX}/auth/logout"
        payload: dict[str, Any] = {"refreshToken": refresh_token}

        # Act
        response = client.post(url, json=payload)

        # Assert: レスポンスと Firestore の状態
        assert response.status_code == status.HTTP_200_OK
        body: SuccessResponse[dict[str, Any]] = SuccessResponse.model_validate(
            response.json()
        )
        assert body.status == "success"
        data = body.data  # type: ignore[assignment]
        assert isinstance(data, dict)
        assert data["message"] == "Logged out successfully"

        sessions = (
            db.collection("backend_sessions")
            .where(filter=FieldFilter("userId", "==", user_id))
            .where(filter=FieldFilter("refreshTokenHash", "==", refresh_hash))
            .get()
        )
        assert len(sessions) == 1
        session_data = sessions[0].to_dict()
        assert session_data is not None
        assert session_data["isRevoked"] is True

    def test_logout_idempotent(
        self,
        client: TestClient,
    ) -> None:
        """正常系: 同じリフレッシュトークンで複数回呼び出しても常に 200 を返す。"""
        # Arrange
        _user_id, _access_token, refresh_token = _auth_sync_and_get_tokens(client)
        url = f"{API_V1_PREFIX}/auth/logout"
        payload: dict[str, Any] = {"refreshToken": refresh_token}

        # Act & Assert
        first = client.post(url, json=payload)
        second = client.post(url, json=payload)

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK

    def test_logout_validation_error(
        self,
        client: TestClient,
    ) -> None:
        """異常系: 必須フィールド不足で 422。"""
        url = f"{API_V1_PREFIX}/auth/logout"
        payload: dict[str, Any] = {}

        response = client.post(url, json=payload)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.status == "error"
        assert body.error.code == "VALIDATION_ERROR"

    def test_logout_firestore_error_returns_500(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        db: firestore.Client,
    ) -> None:
        """異常系: Firestore 障害により AuthRepositoryError が発生した場合は 500 を返す。"""

        def _broken_collection(*_args: Any, **_kwargs: Any) -> Any:
            raise Exception(TEST_CONNECTION_ERROR_MESSAGE)

        monkeypatch.setattr(db, "collection", _broken_collection)

        url = f"{API_V1_PREFIX}/auth/logout"
        payload: dict[str, Any] = {"refreshToken": "any-token"}

        response = client.post(url, json=payload)
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.status == "error"
        assert body.error.code == "AUTH_REPOSITORY_ERROR"


# =============================================================================
# /auth/sync ドメイン制限の結合テスト
# =============================================================================


class TestAuthSyncDomainRestriction:
    """`/api/v1/auth/sync` のドメイン制限に関する結合テスト。"""

    def test_sync_auth_disallowed_domain_returns_403(
        self,
        client: TestClient,
    ) -> None:
        """異常系: 許可されていないドメインで /auth/sync を呼ぶと 403 を返す。"""
        url = f"{API_V1_PREFIX}/auth/sync"
        payload = _build_auth_sync_payload(
            "provider-id-domain-test",
            email="user@other.com",
        )

        with patch.object(settings, "ALLOWED_EMAIL_DOMAINS", ["allowed.com"]):
            response = client.post(url, json=payload)

        assert response.status_code == status.HTTP_403_FORBIDDEN

        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.status == "error"
        assert body.error.code == "EMAIL_DOMAIN_NOT_ALLOWED"
        assert body.error.message == AuthErrorMessages.EMAIL_DOMAIN_NOT_ALLOWED

    def test_sync_auth_allowed_domain_succeeds(
        self,
        client: TestClient,
    ) -> None:
        """正常系: 許可ドメインで /auth/sync を呼ぶと正常に同期される。"""
        url = f"{API_V1_PREFIX}/auth/sync"
        payload = _build_auth_sync_payload(
            "provider-id-domain-allowed",
            email="user@allowed.com",
        )

        with patch.object(settings, "ALLOWED_EMAIL_DOMAINS", ["allowed.com"]):
            response = client.post(url, json=payload)

        assert response.status_code == status.HTTP_200_OK

        body: SuccessResponse[dict[str, Any]] = SuccessResponse.model_validate(
            response.json()
        )
        assert body.status == "success"

        data = body.data  # type: ignore[assignment]
        assert isinstance(data, dict)
        assert data["isNewUser"] is True


# =============================================================================
# セッション重複防止の結合テスト
# =============================================================================


class TestSessionDuplicatePrevention:
    """`/api/v1/auth/sync` のセッション重複防止に関する結合テスト。"""

    def test_sync_auth_revokes_old_sessions(
        self,
        client: TestClient,
        db: firestore.Client,
    ) -> None:
        """正常系: 2回 sync すると旧セッションが isRevoked=True になる。"""
        # 1回目の sync
        user_id, _access_token1, refresh_token1 = _auth_sync_and_get_tokens(
            client, "provider-id-revoke-test"
        )

        # 2回目の sync (同じプロバイダーID)
        _user_id2, _access_token2, refresh_token2 = _auth_sync_and_get_tokens(
            client, "provider-id-revoke-test"
        )

        # Firestore の状態を確認
        refresh_hash1 = hashlib.sha256(refresh_token1.encode()).hexdigest()
        refresh_hash2 = hashlib.sha256(refresh_token2.encode()).hexdigest()

        # 旧セッションが無効化されている
        old_sessions = (
            db.collection("backend_sessions")
            .where(filter=FieldFilter("refreshTokenHash", "==", refresh_hash1))
            .get()
        )
        assert len(old_sessions) == 1
        old_data = old_sessions[0].to_dict()
        assert old_data is not None
        assert old_data["isRevoked"] is True

        # 新セッションはアクティブ
        new_sessions = (
            db.collection("backend_sessions")
            .where(filter=FieldFilter("refreshTokenHash", "==", refresh_hash2))
            .get()
        )
        assert len(new_sessions) == 1
        new_data = new_sessions[0].to_dict()
        assert new_data is not None
        assert new_data["isRevoked"] is False

    def test_old_refresh_token_rejected_after_reauth(
        self,
        client: TestClient,
    ) -> None:
        """正常系: 再認証後に旧リフレッシュトークンで refresh すると 401。"""
        # 1回目の sync
        _user_id, _access_token1, refresh_token1 = _auth_sync_and_get_tokens(
            client, "provider-id-reject-test"
        )

        # 2回目の sync (旧セッションが無効化される)
        _auth_sync_and_get_tokens(client, "provider-id-reject-test")

        # 旧リフレッシュトークンで refresh を試行
        url = f"{API_V1_PREFIX}/auth/token/refresh"
        payload: dict[str, Any] = {"refreshToken": refresh_token1}
        response = client.post(url, json=payload)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.status == "error"
        assert body.error.code == "INVALID_REFRESH_TOKEN"
        assert body.error.message == AuthErrorMessages.REFRESH_TOKEN_REVOKED

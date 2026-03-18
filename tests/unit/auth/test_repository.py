"""AuthRepository単体テスト

Firestore Emulatorを使用してAuthRepositoryの全メソッドをテストする。
"""

# ruff: noqa: S105, S106, PLR2004

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.auth.error_messages import AuthErrorMessages
from app.auth.exceptions import (
    AuthRepositoryError,
    ProviderNotFoundError,
    TokenUpdateError,
)
from app.auth.repository import AuthRepository
from app.auth.schemas import BackendSession, ProviderTokenData

# プロバイダートークンの有効期限(テストデータ用)
TEST_ACCESS_TOKEN_EXPIRE_HOURS = 1

# バックエンドセッションの有効期限(テストデータ用)
TEST_SESSION_EXPIRE_DAYS = 30

# タイムスタンプ比較の許容誤差(秒)
# Firestoreとの往復でミリ秒以下が丸められる可能性を考慮
TIMESTAMP_COMPARISON_TOLERANCE_SECONDS = 1


class TestFindUserByProviderId:
    """find_user_by_provider_idメソッドのテスト"""

    def test_find_existing_user(self, db: firestore.Client) -> None:
        """正常系: プロバイダーIDで既存ユーザーを検索してuserIdを返す"""
        # テストデータ作成
        user_ref = db.collection("users").document()
        user_id = user_ref.id
        user_ref.set({"name": "Test User", "createdAt": datetime.now(UTC)})

        db.collection("auth_providers").add(
            {
                "userId": user_id,
                "provider": "google",
                "providerAccountId": "test-provider-id-123",
                "email": "test@example.com",
            }
        )

        # テスト実行
        repo = AuthRepository(db)
        result = repo.find_user_by_provider_id("test-provider-id-123")

        # 検証
        assert result == user_id

    def test_find_nonexistent_user(self, db: firestore.Client) -> None:
        """正常系: 存在しないプロバイダーIDでNoneを返す"""
        repo = AuthRepository(db)
        result = repo.find_user_by_provider_id("nonexistent-provider-id")

        assert result is None

    def test_empty_provider_account_id(self, db: firestore.Client) -> None:
        """異常系: provider_account_idが空文字の場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError, match=AuthErrorMessages.PROVIDER_ACCOUNT_ID_REQUIRED
        ):
            repo.find_user_by_provider_id("")

    def test_firestore_connection_error(self, db: firestore.Client) -> None:
        """異常系: Firestore接続エラー時にAuthRepositoryErrorを発生"""
        # Arrange (準備)
        repo = AuthRepository(db)

        # Act & Assert (実行・検証)
        with (
            patch.object(db, "collection", side_effect=Exception("Connection error")),
            pytest.raises(
                AuthRepositoryError, match=AuthErrorMessages.FAILED_TO_FIND_USER
            ) as exc_info,
        ):
            repo.find_user_by_provider_id("test-provider-id")

        # 元の例外がConnectionエラーであることを確認
        assert exc_info.value.__cause__ is not None
        assert "Connection error" in str(exc_info.value.__cause__)


class TestGetUserName:
    """get_user_nameメソッドのテスト"""

    def test_get_existing_user_name(self, db: firestore.Client) -> None:
        """正常系: 存在するユーザーIDでユーザー名を返す"""
        # テストデータ作成
        user_ref = db.collection("users").document()
        user_id = user_ref.id
        user_ref.set({"name": "Test User", "createdAt": datetime.now(UTC)})

        # テスト実行
        repo = AuthRepository(db)
        result = repo.get_user_name(user_id)

        # 検証
        assert result == "Test User"

    def test_get_nonexistent_user_name(self, db: firestore.Client) -> None:
        """正常系: 存在しないユーザーIDでNoneを返す"""
        repo = AuthRepository(db)
        result = repo.get_user_name("nonexistent-user-id")

        assert result is None

    def test_empty_user_id(self, db: firestore.Client) -> None:
        """異常系: user_idが空文字の場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError, match=AuthErrorMessages.USER_ID_REQUIRED
        ):
            repo.get_user_name("")

    def test_firestore_connection_error(self, db: firestore.Client) -> None:
        """異常系: Firestore接続エラー時にAuthRepositoryErrorを発生"""
        # Arrange (準備)
        repo = AuthRepository(db)

        # Act & Assert (実行・検証)
        with (
            patch.object(db, "collection", side_effect=Exception("Connection error")),
            pytest.raises(
                AuthRepositoryError, match=AuthErrorMessages.FAILED_TO_GET_USER_NAME
            ) as exc_info,
        ):
            repo.get_user_name("test-user-id")

        # 元の例外がConnectionエラーであることを確認
        assert exc_info.value.__cause__ is not None
        assert "Connection error" in str(exc_info.value.__cause__)


class TestCreateUser:
    """create_userメソッドのテスト"""

    def test_create_user_success(self, db: firestore.Client) -> None:
        """正常系: 新規ユーザーとauth_providerレコードを作成し、userIdを返す"""
        repo = AuthRepository(db)

        # テスト実行
        user_id = repo.create_user(
            name="New User",
            email="new@example.com",
            provider="google",
            provider_account_id="new-provider-id",
            provider_access_token="encrypted-access-token",
            provider_refresh_token="encrypted-refresh-token",
            expires_at=datetime.now(UTC)
            + timedelta(hours=TEST_ACCESS_TOKEN_EXPIRE_HOURS),
        )

        # 検証: userIdが返される
        assert user_id is not None
        assert isinstance(user_id, str)

    def test_create_user_document_fields(self, db: firestore.Client) -> None:
        """正常系: 作成されたユーザードキュメントに正しいフィールドが設定されている"""
        repo = AuthRepository(db)

        user_id = repo.create_user(
            name="New User",
            email="new@example.com",
            provider="google",
            provider_account_id="new-provider-id",
            provider_access_token="encrypted-access-token",
            provider_refresh_token="encrypted-refresh-token",
            expires_at=datetime.now(UTC)
            + timedelta(hours=TEST_ACCESS_TOKEN_EXPIRE_HOURS),
        )

        # ユーザードキュメント検証
        user_doc = db.collection("users").document(user_id).get()
        assert user_doc.exists
        user_data = user_doc.to_dict()
        assert user_data is not None
        assert user_data["name"] == "New User"
        assert "createdAt" in user_data
        assert isinstance(user_data["createdAt"], datetime)
        assert "updatedAt" in user_data
        assert isinstance(user_data["updatedAt"], datetime)

    def test_create_auth_provider_document_fields(self, db: firestore.Client) -> None:
        """正常系: 作成されたauth_providerドキュメントに正しいフィールドが設定されている"""
        repo = AuthRepository(db)

        expires_at = datetime.now(UTC) + timedelta(hours=TEST_ACCESS_TOKEN_EXPIRE_HOURS)
        user_id = repo.create_user(
            name="New User",
            email="new@example.com",
            provider="google",
            provider_account_id="new-provider-id",
            provider_access_token="encrypted-access-token",
            provider_refresh_token="encrypted-refresh-token",
            expires_at=expires_at,
        )

        # auth_providerドキュメント検証
        auth_providers = (
            db.collection("auth_providers")
            .where(filter=FieldFilter("userId", "==", user_id))
            .get()
        )
        assert len(auth_providers) == 1
        auth_data = auth_providers[0].to_dict()
        assert auth_data is not None
        assert auth_data["userId"] == user_id
        assert auth_data["provider"] == "google"
        assert auth_data["providerAccountId"] == "new-provider-id"
        assert auth_data["email"] == "new@example.com"
        assert auth_data["encryptedAccessToken"] == "encrypted-access-token"
        assert auth_data["encryptedRefreshToken"] == "encrypted-refresh-token"
        assert isinstance(auth_data["expiresAt"], datetime)
        assert (
            abs(auth_data["expiresAt"].timestamp() - expires_at.timestamp())
            < TIMESTAMP_COMPARISON_TOLERANCE_SECONDS
        )
        assert "createdAt" in auth_data
        assert "updatedAt" in auth_data

    def test_empty_provider_account_id(self, db: firestore.Client) -> None:
        """異常系: provider_account_idが空文字の場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError, match=AuthErrorMessages.PROVIDER_ACCOUNT_ID_REQUIRED
        ):
            repo.create_user(
                name="New User",
                email="new@example.com",
                provider="google",
                provider_account_id="",
                provider_access_token="encrypted-access-token",
                provider_refresh_token="encrypted-refresh-token",
                expires_at=datetime.now(UTC)
                + timedelta(hours=TEST_ACCESS_TOKEN_EXPIRE_HOURS),
            )

    def test_firestore_connection_error(self, db: firestore.Client) -> None:
        """異常系: Firestore接続エラー時にAuthRepositoryErrorを発生"""
        # Arrange (準備)
        repo = AuthRepository(db)

        # Act & Assert (実行・検証)
        with (
            patch.object(db, "collection", side_effect=Exception("Connection error")),
            pytest.raises(
                AuthRepositoryError, match=AuthErrorMessages.FAILED_TO_CREATE_USER
            ) as exc_info,
        ):
            repo.create_user(
                name="New User",
                email="new@example.com",
                provider="google",
                provider_account_id="new-provider-id",
                provider_access_token="encrypted-access-token",
                provider_refresh_token="encrypted-refresh-token",
                expires_at=datetime.now(UTC)
                + timedelta(hours=TEST_ACCESS_TOKEN_EXPIRE_HOURS),
            )

        # 元の例外がConnectionエラーであることを確認
        assert exc_info.value.__cause__ is not None
        assert "Connection error" in str(exc_info.value.__cause__)

    def test_create_user_invalid_expires_at_type(self, db: firestore.Client) -> None:
        """異常系: expires_atがdatetime以外の型の場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError,
            match=AuthErrorMessages.EXPIRES_AT_MUST_BE_UTC_DATETIME,
        ):
            repo.create_user(
                name="New User",
                email="new@example.com",
                provider="google",
                provider_account_id="new-provider-id",
                provider_access_token="encrypted-access-token",
                provider_refresh_token="encrypted-refresh-token",
                expires_at=int(datetime.now(UTC).timestamp()),  # type: ignore[arg-type]
            )

    def test_create_user_naive_datetime(self, db: firestore.Client) -> None:
        """異常系: expires_atがnaive datetimeの場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)
        naive_expires_at = datetime.now()  # noqa: DTZ005 - タイムゾーンなし(意図的)

        with pytest.raises(
            AuthRepositoryError,
            match=AuthErrorMessages.EXPIRES_AT_MUST_BE_UTC_DATETIME,
        ):
            repo.create_user(
                name="New User",
                email="new@example.com",
                provider="google",
                provider_account_id="new-provider-id",
                provider_access_token="encrypted-access-token",
                provider_refresh_token="encrypted-refresh-token",
                expires_at=naive_expires_at,  # type: ignore[arg-type]
            )

    def test_create_user_non_utc_timezone(self, db: firestore.Client) -> None:
        """異常系: expires_atがUTC以外のタイムゾーンの場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)
        # UTC以外のタイムゾーンを使用
        jst = timezone(timedelta(hours=9))
        non_utc_expires_at = datetime.now(jst)

        with pytest.raises(
            AuthRepositoryError,
            match=AuthErrorMessages.EXPIRES_AT_MUST_BE_UTC_DATETIME,
        ):
            repo.create_user(
                name="New User",
                email="new@example.com",
                provider="google",
                provider_account_id="new-provider-id",
                provider_access_token="encrypted-access-token",
                provider_refresh_token="encrypted-refresh-token",
                expires_at=non_utc_expires_at,  # type: ignore[arg-type]
            )


class TestUpdateUserTokens:
    """update_user_tokensメソッドのテスト"""

    def test_update_tokens_success(self, db: firestore.Client) -> None:
        """正常系: 既存ユーザーのトークンを更新し、更新されたauth_providerドキュメントに正しいフィールドが設定されている"""
        # テストデータ作成
        user_ref = db.collection("users").document()
        user_id = user_ref.id
        user_ref.set({"name": "Test User", "createdAt": datetime.now(UTC)})

        db.collection("auth_providers").add(
            {
                "userId": user_id,
                "provider": "google",
                "providerAccountId": "test-provider-id",
                "email": "test@example.com",
                "encryptedAccessToken": "old-access-token",
                "encryptedRefreshToken": "old-refresh-token",
                "expiresAt": datetime.now(UTC),
            }
        )

        # テスト実行
        repo = AuthRepository(db)
        new_expires_at = datetime.now(UTC) + timedelta(
            hours=TEST_ACCESS_TOKEN_EXPIRE_HOURS
        )
        repo.update_user_tokens(
            user_id=user_id,
            provider_access_token="new-access-token",
            provider_refresh_token="new-refresh-token",
            expires_at=new_expires_at,
        )

        # 検証
        auth_providers = (
            db.collection("auth_providers")
            .where(filter=FieldFilter("userId", "==", user_id))
            .get()
        )
        assert len(auth_providers) == 1
        auth_data = auth_providers[0].to_dict()
        assert auth_data is not None

        # 更新されたフィールド
        assert auth_data["encryptedAccessToken"] == "new-access-token"
        assert auth_data["encryptedRefreshToken"] == "new-refresh-token"
        assert isinstance(auth_data["expiresAt"], datetime)
        assert abs(auth_data["expiresAt"].timestamp() - new_expires_at.timestamp()) < 1

        # updatedAtがdatetime型で設定されていることを確認
        assert "updatedAt" in auth_data
        assert isinstance(auth_data["updatedAt"], datetime)
        assert abs((datetime.now(UTC) - auth_data["updatedAt"]).total_seconds()) < 5

        # 更新されていないフィールド(意図しない変更がないことを確認)
        assert auth_data["userId"] == user_id
        assert auth_data["provider"] == "google"
        assert auth_data["providerAccountId"] == "test-provider-id"
        assert auth_data["email"] == "test@example.com"

    def test_empty_user_id(self, db: firestore.Client) -> None:
        """異常系: user_idが空文字の場合、TokenUpdateErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(TokenUpdateError, match=AuthErrorMessages.USER_ID_REQUIRED):
            repo.update_user_tokens(
                user_id="",
                provider_access_token="new-access-token",
                provider_refresh_token="new-refresh-token",
                expires_at=datetime.now(UTC)
                + timedelta(hours=TEST_ACCESS_TOKEN_EXPIRE_HOURS),
            )

    def test_nonexistent_user_id(self, db: firestore.Client) -> None:
        """異常系: 存在しないユーザーIDの場合、TokenUpdateErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            TokenUpdateError, match=AuthErrorMessages.AUTH_PROVIDER_RECORD_NOT_FOUND
        ):
            repo.update_user_tokens(
                user_id="nonexistent-user-id",
                provider_access_token="new-access-token",
                provider_refresh_token="new-refresh-token",
                expires_at=datetime.now(UTC)
                + timedelta(hours=TEST_ACCESS_TOKEN_EXPIRE_HOURS),
            )

    def test_firestore_connection_error(self, db: firestore.Client) -> None:
        """異常系: Firestore接続エラー時にTokenUpdateErrorを発生"""
        # Arrange (準備)
        repo = AuthRepository(db)

        # Act & Assert (実行・検証)
        with (
            patch.object(db, "collection", side_effect=Exception("Connection error")),
            pytest.raises(
                TokenUpdateError, match=AuthErrorMessages.FAILED_TO_UPDATE_TOKENS
            ) as exc_info,
        ):
            repo.update_user_tokens(
                user_id="test-user-id",
                provider_access_token="new-access-token",
                provider_refresh_token="new-refresh-token",
                expires_at=datetime.now(UTC)
                + timedelta(hours=TEST_ACCESS_TOKEN_EXPIRE_HOURS),
            )

        # 元の例外がConnectionエラーであることを確認
        assert exc_info.value.__cause__ is not None
        assert "Connection error" in str(exc_info.value.__cause__)

    def test_update_tokens_invalid_expires_at_type(self, db: firestore.Client) -> None:
        """異常系: expires_atがdatetime以外の型の場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError,
            match=AuthErrorMessages.EXPIRES_AT_MUST_BE_UTC_DATETIME,
        ):
            repo.update_user_tokens(
                user_id="test-user-id",
                provider_access_token="new-access-token",
                provider_refresh_token="new-refresh-token",
                expires_at=int(datetime.now(UTC).timestamp()),  # type: ignore[arg-type]
            )

    def test_update_tokens_naive_datetime(self, db: firestore.Client) -> None:
        """異常系: expires_atがnaive datetimeの場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)
        naive_expires_at = datetime.now()  # noqa: DTZ005 - タイムゾーンなし(意図的)

        with pytest.raises(
            AuthRepositoryError,
            match=AuthErrorMessages.EXPIRES_AT_MUST_BE_UTC_DATETIME,
        ):
            repo.update_user_tokens(
                user_id="test-user-id",
                provider_access_token="new-access-token",
                provider_refresh_token="new-refresh-token",
                expires_at=naive_expires_at,  # type: ignore[arg-type]
            )

    def test_update_tokens_non_utc_timezone(self, db: firestore.Client) -> None:
        """異常系: expires_atがUTC以外のタイムゾーンの場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)
        # UTC以外のタイムゾーンを使用
        jst = timezone(timedelta(hours=9))
        non_utc_expires_at = datetime.now(jst)

        with pytest.raises(
            AuthRepositoryError,
            match=AuthErrorMessages.EXPIRES_AT_MUST_BE_UTC_DATETIME,
        ):
            repo.update_user_tokens(
                user_id="test-user-id",
                provider_access_token="new-access-token",
                provider_refresh_token="new-refresh-token",
                expires_at=non_utc_expires_at,  # type: ignore[arg-type]
            )


class TestGetProviderTokens:
    """get_provider_tokensメソッドのテスト"""

    def test_get_existing_provider_tokens(self, db: firestore.Client) -> None:
        """正常系: 存在するプロバイダー情報を取得してProviderTokenDataを返す"""
        # テストデータ作成
        user_ref = db.collection("users").document()
        user_id = user_ref.id
        user_ref.set({"name": "Test User", "createdAt": datetime.now(UTC)})

        expires_at = datetime.now(UTC) + timedelta(hours=TEST_ACCESS_TOKEN_EXPIRE_HOURS)
        db.collection("auth_providers").add(
            {
                "userId": user_id,
                "provider": "google",
                "providerAccountId": "test-provider-id",
                "email": "test@example.com",
                "encryptedAccessToken": "encrypted-access-token",
                "encryptedRefreshToken": "encrypted-refresh-token",
                "expiresAt": expires_at,
            }
        )

        # テスト実行
        repo = AuthRepository(db)
        result = repo.get_provider_tokens(user_id, "google")

        # 検証
        assert isinstance(result, ProviderTokenData)
        assert result.encrypted_access_token == "encrypted-access-token"
        assert result.encrypted_refresh_token == "encrypted-refresh-token"
        assert isinstance(result.expires_at, datetime)
        assert abs(result.expires_at.timestamp() - expires_at.timestamp()) < 1

    def test_firestore_timestamp_conversion(self, db: firestore.Client) -> None:
        """正常系: Firestoreに保存したdatetimeがそのままdatetimeとして取得できる"""
        # テストデータ作成(datetimeを使用)
        user_ref = db.collection("users").document()
        user_id = user_ref.id
        user_ref.set({"name": "Test User", "createdAt": datetime.now(UTC)})

        expires_at = datetime.now(UTC) + timedelta(hours=TEST_ACCESS_TOKEN_EXPIRE_HOURS)

        db.collection("auth_providers").add(
            {
                "userId": user_id,
                "provider": "google",
                "providerAccountId": "test-provider-id",
                "email": "test@example.com",
                "encryptedAccessToken": "encrypted-access-token",
                "encryptedRefreshToken": "encrypted-refresh-token",
                "expiresAt": expires_at,
            }
        )

        # テスト実行
        repo = AuthRepository(db)
        result = repo.get_provider_tokens(user_id, "google")

        # 検証
        assert isinstance(result.expires_at, datetime)
        # タイムゾーンを考慮してほぼ同じ時刻であることを確認
        assert abs(result.expires_at.timestamp() - expires_at.timestamp()) < 1

    def test_empty_user_id(self, db: firestore.Client) -> None:
        """異常系: user_idが空文字の場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError, match=AuthErrorMessages.USER_ID_REQUIRED
        ):
            repo.get_provider_tokens("", "google")

    def test_empty_provider(self, db: firestore.Client) -> None:
        """異常系: providerが空文字の場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError, match=AuthErrorMessages.PROVIDER_REQUIRED
        ):
            repo.get_provider_tokens("test-user-id", "")

    def test_nonexistent_provider_document(self, db: firestore.Client) -> None:
        """異常系: auth_providersコレクションに該当するドキュメントが存在しない場合、ProviderNotFoundErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            ProviderNotFoundError,
            match=AuthErrorMessages.PROVIDER_NOT_FOUND_TEMPLATE.format(
                provider="google"
            ),
        ):
            repo.get_provider_tokens("nonexistent-user-id", "google")

    def test_firestore_connection_error(self, db: firestore.Client) -> None:
        """異常系: Firestore接続エラー時にAuthRepositoryErrorを発生"""
        # Arrange (準備)
        repo = AuthRepository(db)

        # Act & Assert (実行・検証)
        with (
            patch.object(db, "collection", side_effect=Exception("Connection error")),
            pytest.raises(
                AuthRepositoryError,
                match=AuthErrorMessages.FAILED_TO_GET_PROVIDER_TOKENS,
            ) as exc_info,
        ):
            repo.get_provider_tokens("test-user-id", "google")

        # 元の例外がConnectionエラーであることを確認
        assert exc_info.value.__cause__ is not None
        assert "Connection error" in str(exc_info.value.__cause__)

    def test_get_provider_tokens_invalid_expires_at_type(
        self, db: firestore.Client
    ) -> None:
        """異常系: expiresAtがdatetime以外の型で保存されている場合、AuthRepositoryErrorを発生"""
        # テストデータ作成
        user_ref = db.collection("users").document()
        user_id = user_ref.id
        user_ref.set({"name": "Test User", "createdAt": datetime.now(UTC)})

        db.collection("auth_providers").add(
            {
                "userId": user_id,
                "provider": "google",
                "providerAccountId": "test-provider-id",
                "email": "test@example.com",
                "encryptedAccessToken": "encrypted-access-token",
                "encryptedRefreshToken": "encrypted-refresh-token",
                "expiresAt": int(datetime.now(UTC).timestamp()),
            }
        )

        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError,
            match=AuthErrorMessages.FAILED_TO_GET_PROVIDER_TOKENS,
        ):
            repo.get_provider_tokens(user_id, "google")

    def test_get_provider_tokens_naive_datetime(self, db: firestore.Client) -> None:
        """メモ: Firestoreはnaive datetimeを自動的にタイムゾーン付きに正規化するため、このケースは実際には発生しない"""
        # Firestoreの挙動依存となりテストの意味が薄いため、ここでは何も検証しない
        # このテストは将来の実装変更に備えて残しておく

    def test_get_provider_tokens_non_utc_timezone(self, db: firestore.Client) -> None:
        """メモ: Firestoreはタイムゾーン情報をUTCに正規化するため、UTC以外のタイムゾーンがそのまま保存されるケースは想定しない"""
        # 実際のFirestoreではUTCに正規化されるため、このケースも契約違反として扱われることはない
        # このテストは将来の実装変更に備えて残しておく


class TestUpdateProviderTokens:
    """update_provider_tokensメソッドのテスト"""

    def test_update_provider_tokens_success(self, db: firestore.Client) -> None:
        """正常系: プロバイダーアクセストークンを更新し、更新されたauth_providerドキュメントに正しいフィールドが設定されている(datetimeをUNIXタイムスタンプに正しく変換する)"""
        # テストデータ作成
        user_ref = db.collection("users").document()
        user_id = user_ref.id
        user_ref.set({"name": "Test User", "createdAt": datetime.now(UTC)})

        db.collection("auth_providers").add(
            {
                "userId": user_id,
                "provider": "google",
                "providerAccountId": "test-provider-id",
                "email": "test@example.com",
                "encryptedAccessToken": "old-access-token",
                "encryptedRefreshToken": "old-refresh-token",
                "expiresAt": int(datetime.now(UTC).timestamp()),
            }
        )

        # テスト実行
        repo = AuthRepository(db)
        new_expires_at = datetime.now(UTC) + timedelta(
            hours=TEST_ACCESS_TOKEN_EXPIRE_HOURS + 1
        )
        repo.update_provider_tokens(
            user_id=user_id,
            provider="google",
            encrypted_access_token="new-access-token",
            expires_at=new_expires_at,
        )

        # 検証
        auth_providers = (
            db.collection("auth_providers")
            .where(filter=FieldFilter("userId", "==", user_id))
            .where(filter=FieldFilter("provider", "==", "google"))
            .get()
        )
        assert len(auth_providers) == 1
        auth_data = auth_providers[0].to_dict()
        assert auth_data is not None
        assert auth_data["encryptedAccessToken"] == "new-access-token"
        assert isinstance(auth_data["expiresAt"], datetime)
        assert abs(auth_data["expiresAt"].timestamp() - new_expires_at.timestamp()) < 1
        assert "updatedAt" in auth_data

    def test_empty_user_id(self, db: firestore.Client) -> None:
        """異常系: user_idが空文字の場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError, match=AuthErrorMessages.USER_ID_REQUIRED
        ):
            repo.update_provider_tokens(
                user_id="",
                provider="google",
                encrypted_access_token="new-access-token",
                expires_at=datetime.now(UTC)
                + timedelta(hours=TEST_ACCESS_TOKEN_EXPIRE_HOURS),
            )

    def test_empty_provider(self, db: firestore.Client) -> None:
        """異常系: providerが空文字の場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError, match=AuthErrorMessages.PROVIDER_REQUIRED
        ):
            repo.update_provider_tokens(
                user_id="test-user-id",
                provider="",
                encrypted_access_token="new-access-token",
                expires_at=datetime.now(UTC)
                + timedelta(hours=TEST_ACCESS_TOKEN_EXPIRE_HOURS),
            )

    def test_empty_encrypted_access_token(self, db: firestore.Client) -> None:
        """異常系: encrypted_access_tokenが空文字の場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError, match=AuthErrorMessages.ENCRYPTED_ACCESS_TOKEN_REQUIRED
        ):
            repo.update_provider_tokens(
                user_id="test-user-id",
                provider="google",
                encrypted_access_token="",
                expires_at=datetime.now(UTC)
                + timedelta(hours=TEST_ACCESS_TOKEN_EXPIRE_HOURS),
            )

    def test_nonexistent_provider_document(self, db: firestore.Client) -> None:
        """異常系: auth_providersコレクションに該当するドキュメントが存在しない場合、ProviderNotFoundErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            ProviderNotFoundError,
            match=AuthErrorMessages.PROVIDER_NOT_FOUND_TEMPLATE.format(
                provider="google"
            ),
        ):
            repo.update_provider_tokens(
                user_id="nonexistent-user-id",
                provider="google",
                encrypted_access_token="new-access-token",
                expires_at=datetime.now(UTC)
                + timedelta(hours=TEST_ACCESS_TOKEN_EXPIRE_HOURS),
            )

    def test_firestore_connection_error(self, db: firestore.Client) -> None:
        """異常系: Firestore接続エラー時にAuthRepositoryErrorを発生"""
        # Arrange (準備)
        repo = AuthRepository(db)

        # Act & Assert (実行・検証)
        with (
            patch.object(db, "collection", side_effect=Exception("Connection error")),
            pytest.raises(
                AuthRepositoryError,
                match=AuthErrorMessages.FAILED_TO_UPDATE_PROVIDER_TOKENS,
            ) as exc_info,
        ):
            repo.update_provider_tokens(
                user_id="test-user-id",
                provider="google",
                encrypted_access_token="new-access-token",
                expires_at=datetime.now(UTC)
                + timedelta(hours=TEST_ACCESS_TOKEN_EXPIRE_HOURS),
            )

        # 元の例外がConnectionエラーであることを確認
        assert exc_info.value.__cause__ is not None
        assert "Connection error" in str(exc_info.value.__cause__)

    def test_update_provider_tokens_invalid_expires_at_type(
        self, db: firestore.Client
    ) -> None:
        """異常系: expires_atがdatetime以外の型の場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError,
            match=AuthErrorMessages.EXPIRES_AT_MUST_BE_UTC_DATETIME,
        ):
            repo.update_provider_tokens(
                user_id="test-user-id",
                provider="google",
                encrypted_access_token="new-access-token",
                expires_at=int(datetime.now(UTC).timestamp()),  # type: ignore[arg-type]
            )

    def test_update_provider_tokens_naive_datetime(self, db: firestore.Client) -> None:
        """異常系: expires_atがnaive datetimeの場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)
        naive_expires_at = datetime.now()  # noqa: DTZ005 - タイムゾーンなし(意図的)

        with pytest.raises(
            AuthRepositoryError,
            match=AuthErrorMessages.EXPIRES_AT_MUST_BE_UTC_DATETIME,
        ):
            repo.update_provider_tokens(
                user_id="test-user-id",
                provider="google",
                encrypted_access_token="new-access-token",
                expires_at=naive_expires_at,  # type: ignore[arg-type]
            )

    def test_update_provider_tokens_non_utc_timezone(
        self, db: firestore.Client
    ) -> None:
        """異常系: expires_atがUTC以外のタイムゾーンの場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)
        # UTC以外のタイムゾーンを使用
        jst = timezone(timedelta(hours=9))
        non_utc_expires_at = datetime.now(jst)

        with pytest.raises(
            AuthRepositoryError,
            match=AuthErrorMessages.EXPIRES_AT_MUST_BE_UTC_DATETIME,
        ):
            repo.update_provider_tokens(
                user_id="test-user-id",
                provider="google",
                encrypted_access_token="new-access-token",
                expires_at=non_utc_expires_at,  # type: ignore[arg-type]
            )


class TestCreateBackendSession:
    """create_backend_sessionメソッドのテスト"""

    def test_create_session_success(self, db: firestore.Client) -> None:
        """正常系: バックエンドセッションを作成し、session_idを返す"""
        repo = AuthRepository(db)

        # テスト実行
        session_id = repo.create_backend_session(
            user_id="test-user-id",
            refresh_token_hash="test-hash",
            expires_at=datetime.now(UTC) + timedelta(days=TEST_SESSION_EXPIRE_DAYS),
        )

        # 検証
        assert session_id is not None
        assert isinstance(session_id, str)

    def test_create_session_document_fields(self, db: firestore.Client) -> None:
        """正常系: 作成されたbackend_sessionsドキュメントに正しいフィールドが設定されている"""
        repo = AuthRepository(db)

        expires_at = datetime.now(UTC) + timedelta(days=TEST_SESSION_EXPIRE_DAYS)
        session_id = repo.create_backend_session(
            user_id="test-user-id",
            refresh_token_hash="test-hash",
            expires_at=expires_at,
        )

        # 検証
        session_doc = db.collection("backend_sessions").document(session_id).get()
        assert session_doc.exists
        session_data = session_doc.to_dict()
        assert session_data is not None
        assert session_data["userId"] == "test-user-id"
        assert session_data["refreshTokenHash"] == "test-hash"
        assert "expiresAt" in session_data
        assert "createdAt" in session_data
        assert "updatedAt" in session_data

    def test_create_session_is_revoked_false(self, db: firestore.Client) -> None:
        """正常系: isRevokedがFalseで初期化される"""
        repo = AuthRepository(db)

        session_id = repo.create_backend_session(
            user_id="test-user-id",
            refresh_token_hash="test-hash",
            expires_at=datetime.now(UTC) + timedelta(days=TEST_SESSION_EXPIRE_DAYS),
        )

        # 検証
        session_doc = db.collection("backend_sessions").document(session_id).get()
        session_data = session_doc.to_dict()
        assert session_data is not None
        assert session_data["isRevoked"] is False

    def test_empty_user_id(self, db: firestore.Client) -> None:
        """異常系: user_idが空文字の場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError, match=AuthErrorMessages.USER_ID_REQUIRED
        ):
            repo.create_backend_session(
                user_id="",
                refresh_token_hash="test-hash",
                expires_at=datetime.now(UTC) + timedelta(days=TEST_SESSION_EXPIRE_DAYS),
            )

    def test_empty_refresh_token_hash(self, db: firestore.Client) -> None:
        """異常系: refresh_token_hashが空文字の場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError, match=AuthErrorMessages.REFRESH_TOKEN_HASH_REQUIRED
        ):
            repo.create_backend_session(
                user_id="test-user-id",
                refresh_token_hash="",
                expires_at=datetime.now(UTC) + timedelta(days=TEST_SESSION_EXPIRE_DAYS),
            )

    def test_firestore_connection_error(self, db: firestore.Client) -> None:
        """異常系: Firestore接続エラー時にAuthRepositoryErrorを発生"""
        # Arrange (準備)
        repo = AuthRepository(db)

        # Act & Assert (実行・検証)
        with (
            patch.object(db, "collection", side_effect=Exception("Connection error")),
            pytest.raises(
                AuthRepositoryError,
                match=AuthErrorMessages.FAILED_TO_CREATE_BACKEND_SESSION,
            ) as exc_info,
        ):
            repo.create_backend_session(
                user_id="test-user-id",
                refresh_token_hash="test-hash",
                expires_at=datetime.now(UTC) + timedelta(days=TEST_SESSION_EXPIRE_DAYS),
            )

        # 元の例外がConnectionエラーであることを確認
        assert exc_info.value.__cause__ is not None
        assert "Connection error" in str(exc_info.value.__cause__)

    def test_create_session_invalid_expires_at_type(self, db: firestore.Client) -> None:
        """異常系: expires_atがdatetime以外の型の場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError,
            match=AuthErrorMessages.EXPIRES_AT_MUST_BE_UTC_DATETIME,
        ):
            repo.create_backend_session(
                user_id="test-user-id",
                refresh_token_hash="test-hash",
                expires_at=int(datetime.now(UTC).timestamp()),  # type: ignore[arg-type]
            )

    def test_create_session_naive_datetime(self, db: firestore.Client) -> None:
        """異常系: expires_atがnaive datetimeの場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)
        naive_expires_at = datetime.now()  # noqa: DTZ005 - タイムゾーンなし(意図的)

        with pytest.raises(
            AuthRepositoryError,
            match=AuthErrorMessages.EXPIRES_AT_MUST_BE_UTC_DATETIME,
        ):
            repo.create_backend_session(
                user_id="test-user-id",
                refresh_token_hash="test-hash",
                expires_at=naive_expires_at,  # type: ignore[arg-type]
            )

    def test_create_session_non_utc_timezone(self, db: firestore.Client) -> None:
        """異常系: expires_atがUTC以外のタイムゾーンの場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)
        # UTC以外のタイムゾーンを使用
        jst = timezone(timedelta(hours=9))
        non_utc_expires_at = datetime.now(jst)

        with pytest.raises(
            AuthRepositoryError,
            match=AuthErrorMessages.EXPIRES_AT_MUST_BE_UTC_DATETIME,
        ):
            repo.create_backend_session(
                user_id="test-user-id",
                refresh_token_hash="test-hash",
                expires_at=non_utc_expires_at,  # type: ignore[arg-type]
            )


class TestFindBackendSessionByTokenHash:
    """find_backend_session_by_token_hashメソッドのテスト"""

    def test_find_existing_session(self, db: firestore.Client) -> None:
        """正常系: 存在するトークンハッシュでセッションを検索してBackendSessionを返す"""
        # テストデータ作成
        expires_at = datetime.now(UTC) + timedelta(days=TEST_SESSION_EXPIRE_DAYS)
        session_ref = db.collection("backend_sessions").document()
        session_id = session_ref.id
        session_ref.set(
            {
                "userId": "test-user-id",
                "refreshTokenHash": "test-hash",
                "expiresAt": expires_at,
                "isRevoked": False,
                "createdAt": datetime.now(UTC),
            }
        )

        # テスト実行
        repo = AuthRepository(db)
        result = repo.find_backend_session_by_token_hash("test-hash")

        # 検証
        assert result is not None
        assert isinstance(result, BackendSession)
        assert result.session_id == session_id
        assert result.user_id == "test-user-id"
        assert result.refresh_token_hash == "test-hash"
        assert result.is_revoked is False

    def test_firestore_timestamp_conversion(self, db: firestore.Client) -> None:
        """正常系: backend_sessionsのexpiresAtに保存したdatetimeがそのまま取得できる"""
        # テストデータ作成(datetimeを使用)
        expires_at = datetime.now(UTC) + timedelta(days=TEST_SESSION_EXPIRE_DAYS)
        session_ref = db.collection("backend_sessions").document()
        session_ref.set(
            {
                "userId": "test-user-id",
                "refreshTokenHash": "test-hash",
                "expiresAt": expires_at,
                "isRevoked": False,
                "createdAt": datetime.now(UTC),
            }
        )

        # テスト実行
        repo = AuthRepository(db)
        result = repo.find_backend_session_by_token_hash("test-hash")

        # 検証
        assert result is not None
        assert isinstance(result.expires_at, datetime)
        assert abs(result.expires_at.timestamp() - expires_at.timestamp()) < 1

    def test_find_nonexistent_session(self, db: firestore.Client) -> None:
        """正常系: 存在しないトークンハッシュでNoneを返す"""
        repo = AuthRepository(db)
        result = repo.find_backend_session_by_token_hash("nonexistent-hash")

        assert result is None

    def test_empty_refresh_token_hash(self, db: firestore.Client) -> None:
        """異常系: refresh_token_hashが空文字の場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError, match=AuthErrorMessages.REFRESH_TOKEN_HASH_REQUIRED
        ):
            repo.find_backend_session_by_token_hash("")

    def test_firestore_connection_error(self, db: firestore.Client) -> None:
        """異常系: Firestore接続エラー時にAuthRepositoryErrorを発生"""
        # Arrange (準備)
        repo = AuthRepository(db)

        # Act & Assert (実行・検証)
        with (
            patch.object(db, "collection", side_effect=Exception("Connection error")),
            pytest.raises(
                AuthRepositoryError,
                match=AuthErrorMessages.FAILED_TO_FIND_BACKEND_SESSION,
            ) as exc_info,
        ):
            repo.find_backend_session_by_token_hash("test-hash")

        # 元の例外がConnectionエラーであることを確認
        assert exc_info.value.__cause__ is not None
        assert "Connection error" in str(exc_info.value.__cause__)

    def test_find_session_invalid_expires_at_type(self, db: firestore.Client) -> None:
        """異常系: expiresAtがdatetime以外の型で保存されている場合、AuthRepositoryErrorを発生"""
        session_ref = db.collection("backend_sessions").document()
        session_ref.set(
            {
                "userId": "test-user-id",
                "refreshTokenHash": "test-hash",
                "expiresAt": int(datetime.now(UTC).timestamp()),
                "isRevoked": False,
                "createdAt": datetime.now(UTC),
            }
        )

        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError,
            match=AuthErrorMessages.FAILED_TO_FIND_BACKEND_SESSION,
        ):
            repo.find_backend_session_by_token_hash("test-hash")

    def test_find_session_naive_datetime(self, db: firestore.Client) -> None:
        """メモ: Firestoreはnaive datetimeを自動的にタイムゾーン付きに正規化するため、このケースは実際には発生しない"""

    def test_find_session_non_utc_timezone(self, db: firestore.Client) -> None:
        """メモ: Firestoreはタイムゾーン情報をUTCに正規化するため、UTC以外のタイムゾーンがそのまま保存されるケースは想定しない"""


class TestRevokeBackendSession:
    """revoke_backend_sessionメソッドのテスト"""

    def test_revoke_existing_session(self, db: firestore.Client) -> None:
        """正常系: 存在するセッションを無効化してTrueを返す"""
        # テストデータ作成
        session_ref = db.collection("backend_sessions").document()
        session_ref.set(
            {
                "userId": "test-user-id",
                "refreshTokenHash": "test-hash",
                "expiresAt": datetime.now(UTC)
                + timedelta(days=TEST_SESSION_EXPIRE_DAYS),
                "isRevoked": False,
                "createdAt": datetime.now(UTC),
            }
        )

        # テスト実行
        repo = AuthRepository(db)
        result = repo.revoke_backend_session("test-hash")

        # 検証
        assert result is True

    def test_revoke_session_is_revoked_true(self, db: firestore.Client) -> None:
        """正常系: 無効化されたセッションのisRevokedがTrueになる"""
        # テストデータ作成
        session_ref = db.collection("backend_sessions").document()
        session_id = session_ref.id
        session_ref.set(
            {
                "userId": "test-user-id",
                "refreshTokenHash": "test-hash",
                "expiresAt": datetime.now(UTC)
                + timedelta(days=TEST_SESSION_EXPIRE_DAYS),
                "isRevoked": False,
                "createdAt": datetime.now(UTC),
            }
        )

        # テスト実行
        repo = AuthRepository(db)
        repo.revoke_backend_session("test-hash")

        # 検証
        session_doc = db.collection("backend_sessions").document(session_id).get()
        session_data = session_doc.to_dict()
        assert session_data is not None
        assert session_data["isRevoked"] is True
        assert "updatedAt" in session_data

    def test_revoke_nonexistent_session(self, db: firestore.Client) -> None:
        """正常系: 存在しないセッションでFalseを返す"""
        repo = AuthRepository(db)
        result = repo.revoke_backend_session("nonexistent-hash")

        assert result is False

    def test_empty_refresh_token_hash(self, db: firestore.Client) -> None:
        """異常系: refresh_token_hashが空文字の場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError, match=AuthErrorMessages.REFRESH_TOKEN_HASH_REQUIRED
        ):
            repo.revoke_backend_session("")

    def test_firestore_connection_error(self, db: firestore.Client) -> None:
        """異常系: Firestore接続エラー時にAuthRepositoryErrorを発生"""
        # Arrange (準備)
        repo = AuthRepository(db)

        # Act & Assert (実行・検証)
        with (
            patch.object(db, "collection", side_effect=Exception("Connection error")),
            pytest.raises(
                AuthRepositoryError,
                match=AuthErrorMessages.FAILED_TO_REVOKE_BACKEND_SESSION,
            ) as exc_info,
        ):
            repo.revoke_backend_session("test-hash")

        # 元の例外がConnectionエラーであることを確認
        assert exc_info.value.__cause__ is not None
        assert "Connection error" in str(exc_info.value.__cause__)


class TestRevokeAllUserSessions:
    """revoke_all_user_sessionsメソッドのテスト"""

    def test_revoke_multiple_active_sessions(self, db: firestore.Client) -> None:
        """正常系: 複数のアクティブセッションを全て無効化してcountを返す"""
        # テストデータ作成: 2件のアクティブセッション
        for i in range(2):
            db.collection("backend_sessions").add(
                {
                    "userId": "test-user-id",
                    "refreshTokenHash": f"hash-{i}",
                    "expiresAt": datetime.now(UTC)
                    + timedelta(days=TEST_SESSION_EXPIRE_DAYS),
                    "isRevoked": False,
                    "createdAt": datetime.now(UTC),
                }
            )

        # テスト実行
        repo = AuthRepository(db)
        count = repo.revoke_all_user_sessions("test-user-id")

        # 検証
        assert count == 2

        # Firestoreの状態を確認: 全セッションがisRevoked=Trueになっている
        sessions = (
            db.collection("backend_sessions")
            .where(filter=FieldFilter("userId", "==", "test-user-id"))
            .get()
        )
        for session_doc in sessions:
            session_data = session_doc.to_dict()
            assert session_data is not None
            assert session_data["isRevoked"] is True
            assert "updatedAt" in session_data

    def test_revoke_skips_already_revoked_sessions(self, db: firestore.Client) -> None:
        """正常系: 既に無効化されたセッションはスキップし、アクティブなもののみ無効化"""
        # アクティブセッション1件
        db.collection("backend_sessions").add(
            {
                "userId": "test-user-id",
                "refreshTokenHash": "hash-active",
                "expiresAt": datetime.now(UTC)
                + timedelta(days=TEST_SESSION_EXPIRE_DAYS),
                "isRevoked": False,
                "createdAt": datetime.now(UTC),
            }
        )
        # 既に無効化されたセッション1件
        db.collection("backend_sessions").add(
            {
                "userId": "test-user-id",
                "refreshTokenHash": "hash-revoked",
                "expiresAt": datetime.now(UTC)
                + timedelta(days=TEST_SESSION_EXPIRE_DAYS),
                "isRevoked": True,
                "createdAt": datetime.now(UTC),
            }
        )

        # テスト実行
        repo = AuthRepository(db)
        count = repo.revoke_all_user_sessions("test-user-id")

        # 検証: アクティブな1件のみ無効化
        assert count == 1

    def test_revoke_no_active_sessions(self, db: firestore.Client) -> None:
        """正常系: アクティブセッションが0件の場合、count=0を返す"""
        # 既に無効化されたセッションのみ
        db.collection("backend_sessions").add(
            {
                "userId": "test-user-id",
                "refreshTokenHash": "hash-revoked",
                "expiresAt": datetime.now(UTC)
                + timedelta(days=TEST_SESSION_EXPIRE_DAYS),
                "isRevoked": True,
                "createdAt": datetime.now(UTC),
            }
        )

        repo = AuthRepository(db)
        count = repo.revoke_all_user_sessions("test-user-id")

        assert count == 0

    def test_revoke_nonexistent_user_sessions(self, db: firestore.Client) -> None:
        """正常系: セッションが存在しないユーザーの場合、count=0を返す"""
        repo = AuthRepository(db)
        count = repo.revoke_all_user_sessions("nonexistent-user-id")

        assert count == 0

    def test_empty_user_id(self, db: firestore.Client) -> None:
        """異常系: user_idが空文字の場合、AuthRepositoryErrorを発生"""
        repo = AuthRepository(db)

        with pytest.raises(
            AuthRepositoryError, match=AuthErrorMessages.USER_ID_REQUIRED
        ):
            repo.revoke_all_user_sessions("")

    def test_firestore_connection_error(self, db: firestore.Client) -> None:
        """異常系: Firestore接続エラー時にAuthRepositoryErrorを発生"""
        repo = AuthRepository(db)

        with (
            patch.object(db, "collection", side_effect=Exception("Connection error")),
            pytest.raises(
                AuthRepositoryError,
                match=AuthErrorMessages.FAILED_TO_REVOKE_ALL_USER_SESSIONS,
            ) as exc_info,
        ):
            repo.revoke_all_user_sessions("test-user-id")

        assert exc_info.value.__cause__ is not None
        assert "Connection error" in str(exc_info.value.__cause__)

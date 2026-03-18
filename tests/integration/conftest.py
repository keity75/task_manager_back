"""統合テスト共通フィクスチャとヘルパー関数

統合テストファイル間で共通して使用されるフィクスチャとヘルパー関数を提供する。
"""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from google.cloud import firestore

from app.core.dependencies import get_db
from app.core.schemas import SuccessResponse
from app.core.settings import settings
from app.main import app

# テスト用定数
API_V1_PREFIX = f"{settings.API_PREFIX}{settings.API_VERSION}"


# =============================================================================
# フィクスチャ
# =============================================================================


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


# =============================================================================
# ヘルパー関数
# =============================================================================


def _build_auth_sync_payload(
    provider_account_id: str,
    *,
    email: str = "user@example.com",
    name: str = "Test User",
    provider: str = "google",
) -> dict[str, Any]:
    """認証同期リクエスト用のペイロードを生成する"""
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
    provider_account_id: str,
) -> tuple[str, str, str]:
    """`/auth/sync` を呼び出して userId / accessToken / refreshToken を取得するヘルパー。

    Args:
        client: FastAPI TestClient
        provider_account_id: プロバイダーアカウントID(必須)

    Returns:
        (user_id, access_token, refresh_token)のタプル

    """
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


def _create_user(db: firestore.Client) -> str:
    """テスト用ユーザーを作成してuserIdを返す"""
    user_ref = db.collection("users").document()
    user_ref.set({"name": "Test User", "createdAt": datetime.now(UTC)})
    return user_ref.id

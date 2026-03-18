"""タスクAPIの結合テスト

テストコードでの例外使用(TRY002)は、Firestoreエラーをシミュレートするために必要。
"""
# ruff: noqa: TRY002

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from google.cloud import firestore

from app.core.dependencies import get_current_user_id
from app.core.schemas import ErrorResponse, SuccessResponse
from app.main import app
from app.tasks.constants import (
    TASK_PRIORITY_MEDIUM,
    TASK_STATUS_DONE,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_TODO,
)
from tests.integration.conftest import (
    API_V1_PREFIX,
    _auth_sync_and_get_tokens,
)

# テスト用定数
TEST_CONNECTION_ERROR_MESSAGE = "Connection error"

# テスト用マジックナンバー定数(PLR2004対策)
MIN_TOTAL_FOR_SUMMARY_TEST = 3


# =============================================================================
# フィクスチャ
# =============================================================================


@pytest.fixture
def authenticated_client(
    client: TestClient,
    request: pytest.FixtureRequest,
) -> Generator[tuple[TestClient, str]]:
    """認証済み TestClient とテスト専用 user_id を提供するフィクスチャ。

    各テストごとに一意な providerAccountId で /auth/sync を実行し、
    テスト間で users/{userId}/tasks のデータが干渉しないようにする。
    また、get_current_user_id をこの user_id にオーバーライドする。
    """
    provider_account_id = f"tasks-{request.node.nodeid}"
    # /auth/sync でユーザー作成とトークンを取得する(テストごとに異なるユーザー)
    user_id, _access_token, _refresh_token = _auth_sync_and_get_tokens(
        client, provider_account_id=provider_account_id
    )

    # CurrentUserId 依存関係をこのテスト専用の user_id にオーバーライド
    def _get_test_user_id() -> str:
        return user_id

    app.dependency_overrides[get_current_user_id] = _get_test_user_id

    try:
        yield client, user_id
    finally:
        # クリーンアップ: テストごとに CurrentUserId 依存関係を元に戻す
        app.dependency_overrides.pop(get_current_user_id, None)


# =============================================================================
# ヘルパー関数
# =============================================================================


def _build_base_task_data(
    user_id: str,
    title: str = "Test Task",
    status: int = TASK_STATUS_TODO,
    priority: int = TASK_PRIORITY_MEDIUM,
    due_at: datetime | None = None,
    description: str | None = None,
    created_at: datetime | None = None,
    deleted_at: datetime | None = None,
    **overrides: object,
) -> dict[str, object]:
    """タスク作成用の共通データを生成する

    Args:
        user_id: ユーザーID
        title: タスクタイトル(デフォルト: "Test Task")
        status: タスクステータス(デフォルト: TASK_STATUS_TODO)
        priority: タスク優先度(デフォルト: TASK_PRIORITY_MEDIUM)
        due_at: タスク期限(datetime、デフォルト: None)
        description: タスク説明(デフォルト: None)
        created_at: 作成日時(datetime、テストで特定の時刻を設定する場合に使用、デフォルト: None)
        deleted_at: 削除日時(datetime、デフォルト: None)
        **overrides: その他のフィールドのオーバーライド(将来の拡張用)

    Returns:
        タスクデータの辞書

    Note:
        - Firestoreに直接書き込む場合(テスト用)、created_atを指定してcreatedAtを設定できます

    """
    now_utc = datetime.now(UTC)
    if created_at is None:
        created_at = now_utc

    data: dict[str, object] = {
        "title": title,
        "status": status,
        "priority": priority,
        "dueAt": due_at,
        "description": description,
        "userId": user_id,
        "createdAt": created_at,
        "updatedAt": created_at,
        "deletedAt": deleted_at,
    }

    data.update(overrides)
    return data


def _create_task_in_firestore(
    db: firestore.Client,
    user_id: str,
    **task_data: object,
) -> str:
    """Firestoreに直接タスクを作成してtask_idを返す"""
    # ユーザードキュメントが存在することを確認(サブコレクションを作成するため)
    user_ref = db.collection("users").document(user_id)
    if not user_ref.get().exists:
        user_ref.set({"name": "Test User", "createdAt": datetime.now(UTC)})

    # users/{userId}/tasks サブコレクションに保存
    tasks_collection = user_ref.collection("tasks")
    task_ref = tasks_collection.document()
    task_id = task_ref.id
    task_data_dict = _build_base_task_data(user_id, **task_data)  # type: ignore[arg-type]
    task_data_dict["id"] = task_id
    task_ref.set(task_data_dict)
    return task_id


# =============================================================================
# GET /tasks/summary の結合テスト
# =============================================================================


class TestGetTaskSummary:
    """`/api/v1/tasks/summary` の結合テスト。"""

    def test_get_task_summary_success(
        self,
        authenticated_client: tuple[TestClient, str],
        db: firestore.Client,
    ) -> None:
        """正常系: 統計情報取得(Total/Todo/InProgress/Done)"""
        client, user_id = authenticated_client

        # Arrange: 各ステータスのタスクを作成
        _create_task_in_firestore(
            db,
            user_id,
            title="Todo Task",
            status=TASK_STATUS_TODO,
        )
        _create_task_in_firestore(
            db,
            user_id,
            title="InProgress Task",
            status=TASK_STATUS_IN_PROGRESS,
        )
        _create_task_in_firestore(
            db,
            user_id,
            title="Done Task",
            status=TASK_STATUS_DONE,
        )

        # Act
        url = f"{API_V1_PREFIX}/tasks/summary"
        response = client.get(url)

        # Assert
        assert response.status_code == status.HTTP_200_OK
        body: SuccessResponse[dict[str, Any]] = SuccessResponse.model_validate(
            response.json()
        )
        assert body.status == "success"

        summary = body.data  # type: ignore[assignment]
        assert isinstance(summary, dict)
        assert summary["total"] == MIN_TOTAL_FOR_SUMMARY_TEST
        assert summary["todo"] == 1
        assert summary["inProgress"] == 1
        assert summary["done"] == 1

    def test_get_task_summary_with_composite_filters(
        self,
        authenticated_client: tuple[TestClient, str],
        db: firestore.Client,
    ) -> None:
        """正常系: フィルター条件適用(全パラメータを含む複合条件)"""
        client, user_id = authenticated_client

        # Arrange: フィルター条件に合致するタスクを作成
        due_at = datetime.now(UTC) + timedelta(days=7)
        _create_task_in_firestore(
            db,
            user_id,
            title="Test Task",
            status=TASK_STATUS_TODO,
            priority=TASK_PRIORITY_MEDIUM,
            due_at=due_at,
        )

        # Act: 複合フィルター条件を適用
        url = f"{API_V1_PREFIX}/tasks/summary"
        params: dict[str, Any] = {
            "title": "Test",
            "priority": [TASK_PRIORITY_MEDIUM],
            "status": [TASK_STATUS_TODO],
            "dueAtFrom": due_at.date().isoformat(),
            "dueAtTo": (due_at + timedelta(days=1)).date().isoformat(),
        }
        response = client.get(url, params=params)

        # Assert
        assert response.status_code == status.HTTP_200_OK
        body: SuccessResponse[dict[str, Any]] = SuccessResponse.model_validate(
            response.json()
        )
        assert body.status == "success"

        summary = body.data  # type: ignore[assignment]
        assert isinstance(summary, dict)
        assert summary["total"] == 1
        assert summary["todo"] == 1

    def test_get_task_summary_unauthorized_missing_token(
        self,
        client: TestClient,
    ) -> None:
        """異常系: 認証トークンがない場合は 401 Unauthorized。"""
        url = f"{API_V1_PREFIX}/tasks/summary"
        response = client.get(url)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.status == "error"
        assert body.error.code == "INVALID_ACCESS_TOKEN"

    def test_get_task_summary_firestore_error_returns_500(
        self,
        authenticated_client: tuple[TestClient, str],
        monkeypatch: pytest.MonkeyPatch,
        db: firestore.Client,
    ) -> None:
        """異常系: Firestore 障害により TaskRepositoryError が発生した場合は 500 を返す。"""
        client, _user_id = authenticated_client

        def _broken_collection(*_args: Any, **_kwargs: Any) -> Any:
            raise Exception(TEST_CONNECTION_ERROR_MESSAGE)

        monkeypatch.setattr(db, "collection", _broken_collection)

        url = f"{API_V1_PREFIX}/tasks/summary"
        response = client.get(url)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.status == "error"
        assert body.error.code == "TASK_REPOSITORY_ERROR"

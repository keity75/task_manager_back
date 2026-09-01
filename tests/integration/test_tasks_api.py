"""タスクAPIの結合テスト

テストコードでの例外使用(TRY002)は、Firestoreエラーをシミュレートするために必要。
"""
# ruff: noqa: TRY002, PLR2004

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
    TASK_PRIORITY_HIGH,
    TASK_PRIORITY_LOW,
    TASK_PRIORITY_MEDIUM,
    TASK_PRIORITY_URGENT,
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


# =============================================================================
# GET /tasks の結合テスト
# =============================================================================


class TestListTasks:
    """`/api/v1/tasks` (一覧取得) の結合テスト。"""

    def test_list_tasks_success_basic(
        self,
        authenticated_client: tuple[TestClient, str],
        db: firestore.Client,
    ) -> None:
        """正常系: タスク一覧を取得し、各アイテムにcalendarLinkが含まれる"""
        client, user_id = authenticated_client

        _create_task_in_firestore(db, user_id, title="Task A")
        _create_task_in_firestore(db, user_id, title="Task B")

        url = f"{API_V1_PREFIX}/tasks"
        response = client.get(url)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "success"
        assert len(body["data"]) == 2
        for item in body["data"]:
            assert item["calendarLink"]
            assert item["userId"] == user_id
            assert item["deletedAt"] is None

        assert body["pagination"] == {
            "totalCount": 2,
            "limit": 20,
            "offset": 0,
        }

    def test_list_tasks_excludes_soft_deleted(
        self,
        authenticated_client: tuple[TestClient, str],
        db: firestore.Client,
    ) -> None:
        """正常系: 削除済み(deletedAtが設定された)タスクは一覧に含まれない"""
        client, user_id = authenticated_client

        _create_task_in_firestore(db, user_id, title="Active Task")
        _create_task_in_firestore(
            db,
            user_id,
            title="Deleted Task",
            deleted_at=datetime.now(UTC),
        )

        url = f"{API_V1_PREFIX}/tasks"
        response = client.get(url)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["title"] == "Active Task"

    def test_list_tasks_filter_by_title_prefix(
        self,
        authenticated_client: tuple[TestClient, str],
        db: firestore.Client,
    ) -> None:
        """正常系: titleクエリパラメータで前方一致フィルタリングされる"""
        client, user_id = authenticated_client

        _create_task_in_firestore(db, user_id, title="Report Q1")
        _create_task_in_firestore(db, user_id, title="Report Q2")
        _create_task_in_firestore(db, user_id, title="Meeting Notes")

        url = f"{API_V1_PREFIX}/tasks"
        response = client.get(url, params={"title": "Report"})

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body["data"]) == 2
        assert {item["title"] for item in body["data"]} == {"Report Q1", "Report Q2"}

    def test_list_tasks_filter_by_status_and_priority(
        self,
        authenticated_client: tuple[TestClient, str],
        db: firestore.Client,
    ) -> None:
        """正常系: status/priorityクエリパラメータ(複数指定)で絞り込まれる"""
        client, user_id = authenticated_client

        _create_task_in_firestore(
            db,
            user_id,
            title="match-todo-high",
            status=TASK_STATUS_TODO,
            priority=TASK_PRIORITY_HIGH,
        )
        _create_task_in_firestore(
            db,
            user_id,
            title="match-in-progress-urgent",
            status=TASK_STATUS_IN_PROGRESS,
            priority=TASK_PRIORITY_URGENT,
        )
        _create_task_in_firestore(
            db,
            user_id,
            title="excluded-done",
            status=TASK_STATUS_DONE,
            priority=TASK_PRIORITY_HIGH,
        )
        _create_task_in_firestore(
            db,
            user_id,
            title="excluded-low-priority",
            status=TASK_STATUS_TODO,
            priority=TASK_PRIORITY_LOW,
        )

        url = f"{API_V1_PREFIX}/tasks"
        response = client.get(
            url,
            params={
                "status": [TASK_STATUS_TODO, TASK_STATUS_IN_PROGRESS],
                "priority": [TASK_PRIORITY_HIGH, TASK_PRIORITY_URGENT],
            },
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        titles = {item["title"] for item in body["data"]}
        assert titles == {"match-todo-high", "match-in-progress-urgent"}

    def test_list_tasks_filter_by_due_at_range(
        self,
        authenticated_client: tuple[TestClient, str],
        db: firestore.Client,
    ) -> None:
        """正常系: dueAtFrom/dueAtToで期限の範囲フィルタリングされる"""
        client, user_id = authenticated_client

        due_at = datetime.now(UTC) + timedelta(days=7)
        _create_task_in_firestore(
            db, user_id, title="in-range", due_at=due_at
        )
        _create_task_in_firestore(
            db, user_id, title="out-of-range", due_at=due_at + timedelta(days=30)
        )

        url = f"{API_V1_PREFIX}/tasks"
        params: dict[str, Any] = {
            "dueAtFrom": due_at.date().isoformat(),
            "dueAtTo": (due_at + timedelta(days=1)).date().isoformat(),
        }
        response = client.get(url, params=params)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["title"] == "in-range"

    def test_list_tasks_sort_by_title_ascending(
        self,
        authenticated_client: tuple[TestClient, str],
        db: firestore.Client,
    ) -> None:
        """正常系: sortBy=title&order=ascでタイトル昇順に並び替えられる"""
        client, user_id = authenticated_client

        _create_task_in_firestore(db, user_id, title="Charlie")
        _create_task_in_firestore(db, user_id, title="Alpha")
        _create_task_in_firestore(db, user_id, title="Bravo")

        url = f"{API_V1_PREFIX}/tasks"
        response = client.get(url, params={"sortBy": "title", "order": "asc"})

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [item["title"] for item in body["data"]] == [
            "Alpha",
            "Bravo",
            "Charlie",
        ]

    def test_list_tasks_default_sort_is_created_at_descending(
        self,
        authenticated_client: tuple[TestClient, str],
        db: firestore.Client,
    ) -> None:
        """正常系: ソート未指定の場合は作成日時の降順で返される"""
        client, user_id = authenticated_client

        base_time = datetime.now(UTC)
        _create_task_in_firestore(
            db, user_id, title="oldest", created_at=base_time
        )
        _create_task_in_firestore(
            db, user_id, title="newest", created_at=base_time + timedelta(minutes=5)
        )
        _create_task_in_firestore(
            db, user_id, title="middle", created_at=base_time + timedelta(minutes=2)
        )

        url = f"{API_V1_PREFIX}/tasks"
        response = client.get(url)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [item["title"] for item in body["data"]] == [
            "newest",
            "middle",
            "oldest",
        ]

    def test_list_tasks_pagination(
        self,
        authenticated_client: tuple[TestClient, str],
        db: firestore.Client,
    ) -> None:
        """正常系: limit/offsetでページネーションされ、totalCountは全件数を返す"""
        client, user_id = authenticated_client

        for i in range(5):
            _create_task_in_firestore(db, user_id, title=f"task-{i}")

        url = f"{API_V1_PREFIX}/tasks"
        response = client.get(
            url, params={"sortBy": "title", "order": "asc", "limit": 2, "offset": 2}
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [item["title"] for item in body["data"]] == ["task-2", "task-3"]
        assert body["pagination"] == {"totalCount": 5, "limit": 2, "offset": 2}

    def test_list_tasks_empty_result(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """正常系: タスクが存在しない場合は空配列とtotalCount=0を返す"""
        client, _user_id = authenticated_client

        url = f"{API_V1_PREFIX}/tasks"
        response = client.get(url)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["data"] == []
        assert body["pagination"]["totalCount"] == 0

    def test_list_tasks_unauthorized_missing_token(
        self,
        client: TestClient,
    ) -> None:
        """異常系: 認証トークンがない場合は401 Unauthorized"""
        url = f"{API_V1_PREFIX}/tasks"
        response = client.get(url)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.status == "error"
        assert body.error.code == "INVALID_ACCESS_TOKEN"

    def test_list_tasks_invalid_sort_by_returns_422(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """異常系: sortByに許可されていない値を指定した場合は422"""
        client, _user_id = authenticated_client

        url = f"{API_V1_PREFIX}/tasks"
        response = client.get(url, params={"sortBy": "invalid-field"})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_list_tasks_invalid_order_returns_422(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """異常系: orderに許可されていない値を指定した場合は422"""
        client, _user_id = authenticated_client

        url = f"{API_V1_PREFIX}/tasks"
        response = client.get(url, params={"order": "invalid"})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_list_tasks_limit_exceeding_max_returns_422(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """異常系: limitが許容範囲(1-100)を超える場合は422"""
        client, _user_id = authenticated_client

        url = f"{API_V1_PREFIX}/tasks"
        response = client.get(url, params={"limit": 101})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_list_tasks_firestore_error_returns_500(
        self,
        authenticated_client: tuple[TestClient, str],
        monkeypatch: pytest.MonkeyPatch,
        db: firestore.Client,
    ) -> None:
        """異常系: Firestore障害によりTaskRepositoryErrorが発生した場合は500を返す"""
        client, _user_id = authenticated_client

        def _broken_collection(*_args: Any, **_kwargs: Any) -> Any:
            raise Exception(TEST_CONNECTION_ERROR_MESSAGE)

        monkeypatch.setattr(db, "collection", _broken_collection)

        url = f"{API_V1_PREFIX}/tasks"
        response = client.get(url)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.status == "error"
        assert body.error.code == "TASK_REPOSITORY_ERROR"


# =============================================================================
# GET /tasks/{id} の結合テスト
# =============================================================================


class TestGetTask:
    """`/api/v1/tasks/{id}` (詳細取得) の結合テスト。"""

    def test_get_task_success(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """正常系: タスク詳細を取得し、calendarLinkを含むフル情報が返る"""
        client, user_id = authenticated_client

        create_response = client.post(
            f"{API_V1_PREFIX}/tasks",
            json={"title": "Detail Task", "priority": TASK_PRIORITY_HIGH},
        )
        task_id = create_response.json()["data"]["id"]

        response = client.get(f"{API_V1_PREFIX}/tasks/{task_id}")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "success"
        data = body["data"]
        assert data["id"] == task_id
        assert data["title"] == "Detail Task"
        assert data["priority"] == TASK_PRIORITY_HIGH
        assert data["userId"] == user_id
        assert data["deletedAt"] is None
        assert data["calendarLink"]

    def test_get_task_not_found_returns_404(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """異常系: 存在しないタスクIDの場合は404"""
        client, _user_id = authenticated_client

        response = client.get(f"{API_V1_PREFIX}/tasks/nonexistent-id")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.status == "error"
        assert body.error.code == "TASK_NOT_FOUND"

    def test_get_task_soft_deleted_returns_404(
        self,
        authenticated_client: tuple[TestClient, str],
        db: firestore.Client,
    ) -> None:
        """異常系: 削除済みタスクの場合は404"""
        client, user_id = authenticated_client

        task_id = _create_task_in_firestore(
            db, user_id, title="Deleted Task", deleted_at=datetime.now(UTC)
        )

        response = client.get(f"{API_V1_PREFIX}/tasks/{task_id}")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_task_other_users_task_returns_404(
        self,
        authenticated_client: tuple[TestClient, str],
        db: firestore.Client,
    ) -> None:
        """異常系: 他ユーザーのタスクの場合は404(所有者チェック)"""
        client, _user_id = authenticated_client

        other_user_id = "other-user-get"
        task_id = _create_task_in_firestore(
            db, other_user_id, title="Someone Else's Task"
        )

        response = client.get(f"{API_V1_PREFIX}/tasks/{task_id}")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_task_unauthorized_missing_token(
        self,
        client: TestClient,
    ) -> None:
        """異常系: 認証トークンがない場合は401"""
        response = client.get(f"{API_V1_PREFIX}/tasks/some-id")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.error.code == "INVALID_ACCESS_TOKEN"


# =============================================================================
# PATCH /tasks/{id} の結合テスト
# =============================================================================


class TestUpdateTask:
    """`/api/v1/tasks/{id}` (部分更新) の結合テスト。"""

    def test_update_task_title_only_leaves_other_fields_unchanged(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """正常系: titleのみ指定した場合、他のフィールドは変更されない"""
        client, _user_id = authenticated_client

        create_response = client.post(
            f"{API_V1_PREFIX}/tasks",
            json={
                "title": "Original Title",
                "description": "Original description",
                "priority": TASK_PRIORITY_LOW,
            },
        )
        task_id = create_response.json()["data"]["id"]

        patch_response = client.patch(
            f"{API_V1_PREFIX}/tasks/{task_id}", json={"title": "Updated Title"}
        )

        assert patch_response.status_code == status.HTTP_200_OK
        patch_body = patch_response.json()
        assert patch_body["status"] == "success"
        assert patch_body["data"] == {"id": task_id}

        get_response = client.get(f"{API_V1_PREFIX}/tasks/{task_id}")
        data = get_response.json()["data"]
        assert data["title"] == "Updated Title"
        assert data["description"] == "Original description"
        assert data["priority"] == TASK_PRIORITY_LOW

    def test_update_task_can_clear_description_with_explicit_null(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """正常系: descriptionをnullで明示的に指定するとクリアされる"""
        client, _user_id = authenticated_client

        create_response = client.post(
            f"{API_V1_PREFIX}/tasks",
            json={"title": "Task", "description": "to be cleared"},
        )
        task_id = create_response.json()["data"]["id"]

        patch_response = client.patch(
            f"{API_V1_PREFIX}/tasks/{task_id}", json={"description": None}
        )

        assert patch_response.status_code == status.HTTP_200_OK

        get_response = client.get(f"{API_V1_PREFIX}/tasks/{task_id}")
        assert get_response.json()["data"]["description"] is None

    def test_update_task_multiple_fields_at_once(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """正常系: title/description/priority/status/dueAtを同時に更新できる"""
        client, _user_id = authenticated_client

        create_response = client.post(
            f"{API_V1_PREFIX}/tasks", json={"title": "Task"}
        )
        task_id = create_response.json()["data"]["id"]

        due_at = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        patch_response = client.patch(
            f"{API_V1_PREFIX}/tasks/{task_id}",
            json={
                "title": "Multi Updated",
                "description": "new description",
                "priority": TASK_PRIORITY_URGENT,
                "status": TASK_STATUS_DONE,
                "dueAt": due_at,
            },
        )

        assert patch_response.status_code == status.HTTP_200_OK

        get_response = client.get(f"{API_V1_PREFIX}/tasks/{task_id}")
        data = get_response.json()["data"]
        assert data["title"] == "Multi Updated"
        assert data["description"] == "new description"
        assert data["priority"] == TASK_PRIORITY_URGENT
        assert data["status"] == TASK_STATUS_DONE
        assert data["dueAt"] is not None

    def test_update_task_bumps_updated_at(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """正常系: 更新するとupdatedAtが更新される"""
        client, _user_id = authenticated_client

        create_response = client.post(
            f"{API_V1_PREFIX}/tasks", json={"title": "Task"}
        )
        task_id = create_response.json()["data"]["id"]
        original_updated_at = client.get(
            f"{API_V1_PREFIX}/tasks/{task_id}"
        ).json()["data"]["updatedAt"]

        client.patch(f"{API_V1_PREFIX}/tasks/{task_id}", json={"title": "Changed"})

        new_updated_at = client.get(f"{API_V1_PREFIX}/tasks/{task_id}").json()[
            "data"
        ]["updatedAt"]
        assert new_updated_at >= original_updated_at

    def test_update_task_not_found_returns_404(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """異常系: 存在しないタスクIDの場合は404"""
        client, _user_id = authenticated_client

        response = client.patch(
            f"{API_V1_PREFIX}/tasks/nonexistent-id", json={"title": "x"}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.error.code == "TASK_NOT_FOUND"

    def test_update_task_other_users_task_returns_404(
        self,
        authenticated_client: tuple[TestClient, str],
        db: firestore.Client,
    ) -> None:
        """異常系: 他ユーザーのタスクの場合は404(所有者チェック)"""
        client, _user_id = authenticated_client

        other_user_id = "other-user-patch"
        task_id = _create_task_in_firestore(db, other_user_id, title="Not Yours")

        response = client.patch(
            f"{API_V1_PREFIX}/tasks/{task_id}", json={"title": "hacked"}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_task_empty_title_returns_422(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """異常系: title="" (空文字) は422"""
        client, _user_id = authenticated_client

        create_response = client.post(
            f"{API_V1_PREFIX}/tasks", json={"title": "Task"}
        )
        task_id = create_response.json()["data"]["id"]

        response = client.patch(
            f"{API_V1_PREFIX}/tasks/{task_id}", json={"title": ""}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_update_task_explicit_null_title_returns_422(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """異常系: title=nullを明示的に指定した場合は422(titleはNOT NULL)"""
        client, _user_id = authenticated_client

        create_response = client.post(
            f"{API_V1_PREFIX}/tasks", json={"title": "Task"}
        )
        task_id = create_response.json()["data"]["id"]

        response = client.patch(
            f"{API_V1_PREFIX}/tasks/{task_id}", json={"title": None}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_update_task_invalid_priority_returns_422(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """異常系: priorityが許容値(1-4)以外の場合は422"""
        client, _user_id = authenticated_client

        create_response = client.post(
            f"{API_V1_PREFIX}/tasks", json={"title": "Task"}
        )
        task_id = create_response.json()["data"]["id"]

        response = client.patch(
            f"{API_V1_PREFIX}/tasks/{task_id}", json={"priority": 99}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_update_task_readonly_field_is_rejected(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """異常系: userId等の読み取り専用フィールドを送ると拒否される"""
        client, user_id = authenticated_client

        create_response = client.post(
            f"{API_V1_PREFIX}/tasks", json={"title": "Task"}
        )
        task_id = create_response.json()["data"]["id"]

        response = client.patch(
            f"{API_V1_PREFIX}/tasks/{task_id}",
            json={"title": "Task", "userId": "someone-else"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

        # 実際にuserIdが変更されていないことも確認
        get_response = client.get(f"{API_V1_PREFIX}/tasks/{task_id}")
        assert get_response.json()["data"]["userId"] == user_id

    def test_update_task_unauthorized_missing_token(
        self,
        client: TestClient,
    ) -> None:
        """異常系: 認証トークンがない場合は401"""
        response = client.patch(
            f"{API_V1_PREFIX}/tasks/some-id", json={"title": "x"}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_update_task_firestore_error_returns_500(
        self,
        authenticated_client: tuple[TestClient, str],
        monkeypatch: pytest.MonkeyPatch,
        db: firestore.Client,
    ) -> None:
        """異常系: Firestore障害によりTaskRepositoryErrorが発生した場合は500を返す"""
        client, _user_id = authenticated_client

        create_response = client.post(
            f"{API_V1_PREFIX}/tasks", json={"title": "Task"}
        )
        task_id = create_response.json()["data"]["id"]

        def _broken_collection(*_args: Any, **_kwargs: Any) -> Any:
            raise Exception(TEST_CONNECTION_ERROR_MESSAGE)

        monkeypatch.setattr(db, "collection", _broken_collection)

        response = client.patch(
            f"{API_V1_PREFIX}/tasks/{task_id}", json={"title": "x"}
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.error.code == "TASK_REPOSITORY_ERROR"


# =============================================================================
# DELETE /tasks/{id} の結合テスト
# =============================================================================


class TestDeleteTask:
    """`/api/v1/tasks/{id}` (論理削除) の結合テスト。"""

    def test_delete_task_success_returns_id(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """正常系: 削除成功時はidを返す"""
        client, _user_id = authenticated_client

        create_response = client.post(
            f"{API_V1_PREFIX}/tasks", json={"title": "Task"}
        )
        task_id = create_response.json()["data"]["id"]

        response = client.delete(f"{API_V1_PREFIX}/tasks/{task_id}")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "success"
        assert body["data"] == {"id": task_id}

    def test_delete_task_is_soft_delete_not_physical(
        self,
        authenticated_client: tuple[TestClient, str],
        db: firestore.Client,
    ) -> None:
        """正常系: 論理削除であり、Firestore上のドキュメント自体は残る"""
        client, user_id = authenticated_client

        create_response = client.post(
            f"{API_V1_PREFIX}/tasks", json={"title": "Task"}
        )
        task_id = create_response.json()["data"]["id"]

        client.delete(f"{API_V1_PREFIX}/tasks/{task_id}")

        doc = (
            db.collection("users")
            .document(user_id)
            .collection("tasks")
            .document(task_id)
            .get()
        )
        assert doc.exists
        assert doc.to_dict()["deletedAt"] is not None

    def test_delete_task_excludes_from_list_and_detail(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """正常系: 削除後は一覧取得・詳細取得の両方から除外される"""
        client, _user_id = authenticated_client

        create_response = client.post(
            f"{API_V1_PREFIX}/tasks", json={"title": "Task"}
        )
        task_id = create_response.json()["data"]["id"]

        client.delete(f"{API_V1_PREFIX}/tasks/{task_id}")

        detail_response = client.get(f"{API_V1_PREFIX}/tasks/{task_id}")
        assert detail_response.status_code == status.HTTP_404_NOT_FOUND

        list_response = client.get(f"{API_V1_PREFIX}/tasks")
        task_ids = {item["id"] for item in list_response.json()["data"]}
        assert task_id not in task_ids

    def test_delete_task_already_deleted_returns_404(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """異常系: 既に削除済みのタスクを再度削除しようとすると404"""
        client, _user_id = authenticated_client

        create_response = client.post(
            f"{API_V1_PREFIX}/tasks", json={"title": "Task"}
        )
        task_id = create_response.json()["data"]["id"]

        first_delete = client.delete(f"{API_V1_PREFIX}/tasks/{task_id}")
        assert first_delete.status_code == status.HTTP_200_OK

        second_delete = client.delete(f"{API_V1_PREFIX}/tasks/{task_id}")

        assert second_delete.status_code == status.HTTP_404_NOT_FOUND
        body: ErrorResponse = ErrorResponse.model_validate(second_delete.json())
        assert body.error.code == "TASK_NOT_FOUND"

    def test_delete_task_not_found_returns_404(
        self,
        authenticated_client: tuple[TestClient, str],
    ) -> None:
        """異常系: 存在しないタスクIDの場合は404"""
        client, _user_id = authenticated_client

        response = client.delete(f"{API_V1_PREFIX}/tasks/nonexistent-id")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_task_other_users_task_returns_404(
        self,
        authenticated_client: tuple[TestClient, str],
        db: firestore.Client,
    ) -> None:
        """異常系: 他ユーザーのタスクの場合は404(所有者チェック)"""
        client, _user_id = authenticated_client

        other_user_id = "other-user-delete"
        task_id = _create_task_in_firestore(db, other_user_id, title="Not Yours")

        response = client.delete(f"{API_V1_PREFIX}/tasks/{task_id}")

        assert response.status_code == status.HTTP_404_NOT_FOUND

        # 他ユーザーのタスクは削除されていないことも確認
        doc = (
            db.collection("users")
            .document(other_user_id)
            .collection("tasks")
            .document(task_id)
            .get()
        )
        assert doc.to_dict()["deletedAt"] is None

    def test_delete_task_unauthorized_missing_token(
        self,
        client: TestClient,
    ) -> None:
        """異常系: 認証トークンがない場合は401"""
        response = client.delete(f"{API_V1_PREFIX}/tasks/some-id")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_delete_task_firestore_error_returns_500(
        self,
        authenticated_client: tuple[TestClient, str],
        monkeypatch: pytest.MonkeyPatch,
        db: firestore.Client,
    ) -> None:
        """異常系: Firestore障害によりTaskRepositoryErrorが発生した場合は500を返す"""
        client, _user_id = authenticated_client

        create_response = client.post(
            f"{API_V1_PREFIX}/tasks", json={"title": "Task"}
        )
        task_id = create_response.json()["data"]["id"]

        def _broken_collection(*_args: Any, **_kwargs: Any) -> Any:
            raise Exception(TEST_CONNECTION_ERROR_MESSAGE)

        monkeypatch.setattr(db, "collection", _broken_collection)

        response = client.delete(f"{API_V1_PREFIX}/tasks/{task_id}")

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        body: ErrorResponse = ErrorResponse.model_validate(response.json())
        assert body.error.code == "TASK_REPOSITORY_ERROR"

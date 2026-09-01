"""FirestoreTaskRepository単体テスト

Firestore Emulatorを使用してFirestoreTaskRepositoryの主要メソッドをテストする。
"""

# ruff: noqa: PLR2004

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from google.cloud import firestore

from app.tasks import schemas
from app.tasks.constants import (
    TASK_PRIORITY_HIGH,
    TASK_PRIORITY_LOW,
    TASK_PRIORITY_MEDIUM,
    TASK_STATUS_DONE,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_TODO,
)
from app.tasks.error_messages import TaskErrorMessages
from app.tasks.exceptions import TaskRepositoryError
from app.tasks.firestore_repository import FirestoreTaskRepository
from tests.unit.conftest import _create_user


def _build_base_task_data(
    user_id: str,
    title: str = "Test Task",
    status: int = TASK_STATUS_TODO,
    priority: int = TASK_PRIORITY_MEDIUM,
    due_at: datetime | None = None,
    description: str | None = None,
    created_at: datetime | None = None,
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
        **overrides: その他のフィールドのオーバーライド(将来の拡張用)

    Returns:
        タスクデータの辞書

    Note:
        - Repository層を経由する場合、createdAt/updatedAt/deletedAtは自動設定されます
        - Firestoreに直接書き込む場合(テスト用)、created_atを指定してcreatedAtを設定できます

    """
    data: dict[str, object] = {
        "title": title,
        "status": status,
        "priority": priority,
        "dueAt": due_at,
        "description": description,
        "userId": user_id,
        "deletedAt": None,
    }

    # テスト用に特定の時刻を設定する場合(Firestore直接書き込み用)
    if created_at is not None:
        data["createdAt"] = created_at
        data["updatedAt"] = created_at

    data.update(overrides)
    return data


class TestCountTasks:
    """count_tasksメソッドのテスト"""

    def test_count_tasks_basic(self, db: firestore.Client) -> None:
        """正常系: 基本的な件数取得(フィルターなし)"""
        user_id = _create_user(db)
        repo = FirestoreTaskRepository(db)

        # 3件のタスクを作成
        repo.create(_build_base_task_data(user_id, title="task-1"))
        repo.create(_build_base_task_data(user_id, title="task-2"))
        repo.create(_build_base_task_data(user_id, title="task-3"))

        filters = schemas.TaskFilterParams()

        count = repo.count_tasks(
            user_id=user_id,
            filters=filters,
            due_at_from_utc=None,
            due_at_to_utc=None,
        )

        assert count == 3

    def test_count_tasks_with_priority_filter(self, db: firestore.Client) -> None:
        """正常系: priorityフィルター適用後の件数を取得"""
        user_id = _create_user(db)
        repo = FirestoreTaskRepository(db)

        # priority=1が2件, priority=2が1件
        repo.create(_build_base_task_data(user_id, priority=TASK_PRIORITY_LOW))
        repo.create(_build_base_task_data(user_id, priority=TASK_PRIORITY_LOW))
        repo.create(_build_base_task_data(user_id, priority=TASK_PRIORITY_MEDIUM))

        filters = schemas.TaskFilterParams(priority=[TASK_PRIORITY_LOW])

        count = repo.count_tasks(
            user_id=user_id,
            filters=filters,
            due_at_from_utc=None,
            due_at_to_utc=None,
        )

        assert count == 2

    def test_count_tasks_empty_result_set(self, db: firestore.Client) -> None:
        """正常系: 空の結果セットで0を返す"""
        user_id = _create_user(db)
        repo = FirestoreTaskRepository(db)

        filters = schemas.TaskFilterParams()

        count = repo.count_tasks(
            user_id=user_id,
            filters=filters,
            due_at_from_utc=None,
            due_at_to_utc=None,
        )

        assert count == 0

    def test_count_tasks_empty_user_id_raises(self, db: firestore.Client) -> None:
        """異常系: user_idが空の場合はTaskRepositoryError"""
        repo = FirestoreTaskRepository(db)

        filters = schemas.TaskFilterParams()

        with pytest.raises(
            TaskRepositoryError, match=TaskErrorMessages.FAILED_TO_COUNT_TASKS
        ) as exc_info:
            repo.count_tasks(
                user_id="",
                filters=filters,
                due_at_from_utc=None,
                due_at_to_utc=None,
            )
        # 元のエラーがUSER_ID_REQUIREDであることを確認
        assert exc_info.value.__cause__ is not None
        assert TaskErrorMessages.USER_ID_REQUIRED in str(exc_info.value.__cause__)

    def test_count_tasks_firestore_connection_error(self, db: firestore.Client) -> None:
        """異常系: Firestore接続エラー時にTaskRepositoryErrorを発生"""
        # Arrange (準備)
        repo = FirestoreTaskRepository(db)
        filters = schemas.TaskFilterParams()

        # Act & Assert (実行・検証)
        with (
            patch.object(db, "collection", side_effect=Exception("Connection error")),
            pytest.raises(
                TaskRepositoryError, match=TaskErrorMessages.FAILED_TO_COUNT_TASKS
            ) as exc_info,
        ):
            repo.count_tasks(
                user_id="user-1",
                filters=filters,
                due_at_from_utc=None,
                due_at_to_utc=None,
            )

        # 元の例外がConnectionエラーであることを確認
        assert exc_info.value.__cause__ is not None
        assert "Connection error" in str(exc_info.value.__cause__)


def _create_deleted_task(db: firestore.Client, user_id: str, title: str = "Deleted Task") -> str:
    """ソフトデリート済みタスクをFirestoreへ直接書き込むヘルパー(repo.createはdeletedAt=Noneを強制するため直接書き込む)"""
    user_ref = db.collection("users").document(user_id)
    if not user_ref.get().exists:
        user_ref.set({"name": "Test User", "createdAt": datetime.now(UTC)})

    tasks_collection = user_ref.collection("tasks")
    task_ref = tasks_collection.document()
    now = datetime.now(UTC)
    task_ref.set(
        {
            "id": task_ref.id,
            "title": title,
            "status": TASK_STATUS_TODO,
            "priority": TASK_PRIORITY_MEDIUM,
            "dueAt": None,
            "description": None,
            "userId": user_id,
            "createdAt": now,
            "updatedAt": now,
            "deletedAt": now,
        }
    )
    return task_ref.id


class TestListTasks:
    """listメソッドのテスト"""

    def test_list_tasks_basic_returns_all_with_id(self, db: firestore.Client) -> None:
        """正常系: フィルターなしで作成した全タスクをid付きで返す"""
        user_id = _create_user(db)
        repo = FirestoreTaskRepository(db)

        repo.create(_build_base_task_data(user_id, title="task-1"))
        repo.create(_build_base_task_data(user_id, title="task-2"))

        results = repo.list(
            user_id=user_id,
            filters=schemas.TaskFilterParams(),
            due_at_from_utc=None,
            due_at_to_utc=None,
            sort_by="createdAt",
            order="desc",
            limit=20,
            offset=0,
        )

        assert len(results) == 2
        titles = {r["title"] for r in results}
        assert titles == {"task-1", "task-2"}
        assert all("id" in r for r in results)

    def test_list_tasks_excludes_soft_deleted(self, db: firestore.Client) -> None:
        """正常系: deletedAtが設定されたタスクは一覧に含まれない"""
        user_id = _create_user(db)
        repo = FirestoreTaskRepository(db)

        repo.create(_build_base_task_data(user_id, title="active-task"))
        _create_deleted_task(db, user_id, title="deleted-task")

        results = repo.list(
            user_id=user_id,
            filters=schemas.TaskFilterParams(),
            due_at_from_utc=None,
            due_at_to_utc=None,
            sort_by="createdAt",
            order="desc",
            limit=20,
            offset=0,
        )

        assert len(results) == 1
        assert results[0]["title"] == "active-task"

    def test_list_tasks_filters_by_priority_and_status(
        self, db: firestore.Client
    ) -> None:
        """正常系: priority/statusフィルターの組み合わせで絞り込む"""
        user_id = _create_user(db)
        repo = FirestoreTaskRepository(db)

        repo.create(
            _build_base_task_data(
                user_id,
                title="match",
                priority=TASK_PRIORITY_HIGH,
                status=TASK_STATUS_IN_PROGRESS,
            )
        )
        repo.create(
            _build_base_task_data(
                user_id,
                title="wrong-priority",
                priority=TASK_PRIORITY_LOW,
                status=TASK_STATUS_IN_PROGRESS,
            )
        )
        repo.create(
            _build_base_task_data(
                user_id,
                title="wrong-status",
                priority=TASK_PRIORITY_HIGH,
                status=TASK_STATUS_DONE,
            )
        )

        results = repo.list(
            user_id=user_id,
            filters=schemas.TaskFilterParams(
                priority=[TASK_PRIORITY_HIGH],
                status=[TASK_STATUS_IN_PROGRESS],
            ),
            due_at_from_utc=None,
            due_at_to_utc=None,
            sort_by="createdAt",
            order="desc",
            limit=20,
            offset=0,
        )

        assert len(results) == 1
        assert results[0]["title"] == "match"

    def test_list_tasks_filters_by_title_prefix(self, db: firestore.Client) -> None:
        """正常系: タイトルの前方一致で絞り込む"""
        user_id = _create_user(db)
        repo = FirestoreTaskRepository(db)

        repo.create(_build_base_task_data(user_id, title="Report Q1"))
        repo.create(_build_base_task_data(user_id, title="Report Q2"))
        repo.create(_build_base_task_data(user_id, title="Meeting Notes"))

        results = repo.list(
            user_id=user_id,
            filters=schemas.TaskFilterParams(title="Report"),
            due_at_from_utc=None,
            due_at_to_utc=None,
            sort_by="createdAt",
            order="desc",
            limit=20,
            offset=0,
        )

        assert len(results) == 2
        assert {r["title"] for r in results} == {"Report Q1", "Report Q2"}

    def test_list_tasks_filters_by_due_at_range(self, db: firestore.Client) -> None:
        """正常系: 期限の範囲(from/to)で絞り込む"""
        user_id = _create_user(db)
        repo = FirestoreTaskRepository(db)

        now = datetime.now(UTC)
        repo.create(
            _build_base_task_data(user_id, title="in-range", due_at=now)
        )
        repo.create(
            _build_base_task_data(
                user_id, title="out-of-range", due_at=now + timedelta(days=30)
            )
        )

        results = repo.list(
            user_id=user_id,
            filters=schemas.TaskFilterParams(),
            due_at_from_utc=now - timedelta(days=1),
            due_at_to_utc=now + timedelta(days=1),
            sort_by="createdAt",
            order="desc",
            limit=20,
            offset=0,
        )

        assert len(results) == 1
        assert results[0]["title"] == "in-range"

    def test_list_tasks_sort_by_title_ascending(self, db: firestore.Client) -> None:
        """正常系: title昇順でソートされる"""
        user_id = _create_user(db)
        repo = FirestoreTaskRepository(db)

        repo.create(_build_base_task_data(user_id, title="Charlie"))
        repo.create(_build_base_task_data(user_id, title="Alpha"))
        repo.create(_build_base_task_data(user_id, title="Bravo"))

        results = repo.list(
            user_id=user_id,
            filters=schemas.TaskFilterParams(),
            due_at_from_utc=None,
            due_at_to_utc=None,
            sort_by="title",
            order="asc",
            limit=20,
            offset=0,
        )

        assert [r["title"] for r in results] == ["Alpha", "Bravo", "Charlie"]

    def test_list_tasks_sort_by_priority_descending(self, db: firestore.Client) -> None:
        """正常系: priority降順でソートされる"""
        user_id = _create_user(db)
        repo = FirestoreTaskRepository(db)

        repo.create(_build_base_task_data(user_id, title="low", priority=1))
        repo.create(_build_base_task_data(user_id, title="urgent", priority=4))
        repo.create(_build_base_task_data(user_id, title="medium", priority=2))

        results = repo.list(
            user_id=user_id,
            filters=schemas.TaskFilterParams(),
            due_at_from_utc=None,
            due_at_to_utc=None,
            sort_by="priority",
            order="desc",
            limit=20,
            offset=0,
        )

        assert [r["priority"] for r in results] == [4, 2, 1]

    def test_list_tasks_pagination_limit_and_offset(self, db: firestore.Client) -> None:
        """正常系: limit/offsetでページネーションされる"""
        user_id = _create_user(db)
        repo = FirestoreTaskRepository(db)

        for i in range(5):
            repo.create(_build_base_task_data(user_id, title=f"task-{i}"))

        first_page = repo.list(
            user_id=user_id,
            filters=schemas.TaskFilterParams(),
            due_at_from_utc=None,
            due_at_to_utc=None,
            sort_by="title",
            order="asc",
            limit=2,
            offset=0,
        )
        second_page = repo.list(
            user_id=user_id,
            filters=schemas.TaskFilterParams(),
            due_at_from_utc=None,
            due_at_to_utc=None,
            sort_by="title",
            order="asc",
            limit=2,
            offset=2,
        )

        assert [r["title"] for r in first_page] == ["task-0", "task-1"]
        assert [r["title"] for r in second_page] == ["task-2", "task-3"]

    def test_list_tasks_empty_result_returns_empty_list(
        self, db: firestore.Client
    ) -> None:
        """正常系: 該当タスクがない場合は空リストを返す"""
        user_id = _create_user(db)
        repo = FirestoreTaskRepository(db)

        results = repo.list(
            user_id=user_id,
            filters=schemas.TaskFilterParams(),
            due_at_from_utc=None,
            due_at_to_utc=None,
            sort_by="createdAt",
            order="desc",
            limit=20,
            offset=0,
        )

        assert results == []

    def test_list_tasks_empty_user_id_raises(self, db: firestore.Client) -> None:
        """異常系: user_idが空の場合はTaskRepositoryError"""
        repo = FirestoreTaskRepository(db)

        with pytest.raises(
            TaskRepositoryError, match=TaskErrorMessages.FAILED_TO_LIST_TASKS
        ) as exc_info:
            repo.list(
                user_id="",
                filters=schemas.TaskFilterParams(),
                due_at_from_utc=None,
                due_at_to_utc=None,
                sort_by="createdAt",
                order="desc",
                limit=20,
                offset=0,
            )

        assert exc_info.value.__cause__ is not None
        assert TaskErrorMessages.USER_ID_REQUIRED in str(exc_info.value.__cause__)

    def test_list_tasks_firestore_connection_error(self, db: firestore.Client) -> None:
        """異常系: Firestore接続エラー時にTaskRepositoryErrorを発生"""
        repo = FirestoreTaskRepository(db)

        with (
            patch.object(db, "collection", side_effect=Exception("Connection error")),
            pytest.raises(
                TaskRepositoryError, match=TaskErrorMessages.FAILED_TO_LIST_TASKS
            ) as exc_info,
        ):
            repo.list(
                user_id="user-1",
                filters=schemas.TaskFilterParams(),
                due_at_from_utc=None,
                due_at_to_utc=None,
                sort_by="createdAt",
                order="desc",
                limit=20,
                offset=0,
            )

        assert exc_info.value.__cause__ is not None
        assert "Connection error" in str(exc_info.value.__cause__)


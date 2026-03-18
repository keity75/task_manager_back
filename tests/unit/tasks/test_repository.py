"""FirestoreTaskRepository単体テスト

Firestore Emulatorを使用してFirestoreTaskRepositoryの主要メソッドをテストする。
"""

# ruff: noqa: PLR2004

from datetime import datetime
from unittest.mock import patch

import pytest
from google.cloud import firestore

from app.tasks import schemas
from app.tasks.constants import (
    TASK_PRIORITY_LOW,
    TASK_PRIORITY_MEDIUM,
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



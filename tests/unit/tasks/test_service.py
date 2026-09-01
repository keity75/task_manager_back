"""TaskService単体テスト

Repository層や外部依存をモック化してTaskServiceのビジネスロジックをテストする。
"""

# ruff: noqa: S105, S106, SLF001, PLR2004

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from app.tasks import schemas
from app.tasks.constants import (
    TASK_PRIORITY_HIGH,
    TASK_PRIORITY_MEDIUM,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_TODO,
)
from app.tasks.exceptions import TaskRepositoryError
from app.tasks.repository import TaskRepository
from app.tasks.service import TaskService


@pytest.fixture
def mock_repo() -> Mock:
    """TaskRepositoryのモックを作成"""
    return Mock(spec=TaskRepository)


@pytest.fixture
def mock_calendar_gen() -> Mock:
    """CalendarLinkGeneratorのモックを作成"""
    # Protocolベースなので単純なMockで十分
    calendar = Mock()
    calendar.generate.return_value = "https://example.com/calendar"
    return calendar


@pytest.fixture
def task_service(
    mock_repo: Mock,
    mock_calendar_gen: Mock,
) -> TaskService:
    """TaskServiceインスタンスを作成"""
    return TaskService(
        task_repo=mock_repo,
        calendar_link_generator=mock_calendar_gen,
    )


class TestGetTaskSummary:
    """get_task_summaryメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_get_task_summary_basic(
        self, task_service: TaskService, mock_repo: Mock
    ) -> None:
        """正常系: 4つの集計クエリ結果をまとめて返す"""
        filters = schemas.TaskFilterParams()

        # ThreadPoolExecutor + run_in_executor だが、count_tasks自体を同期でモック
        # 並列実行のため、呼び出し順序は保証されないが、各クエリは正しく呼ばれる
        mock_repo.count_tasks.return_value = 5  # すべて同じ値を返す

        summary = await task_service.get_task_summary(
            user_id="user-1",
            filters=filters,
        )

        assert isinstance(summary, schemas.TaskSummaryResponse)

        # 4つのカウントクエリが呼ばれることを確認
        assert summary.total == 5
        assert summary.todo == 5
        assert summary.in_progress == 5
        assert summary.done == 5

        # 依存関係の呼び出し回数を検証(4回呼ばれる)
        assert mock_repo.count_tasks.call_count == 4

    @pytest.mark.asyncio
    async def test_get_task_summary_repository_error_raises(
        self, task_service: TaskService, mock_repo: Mock
    ) -> None:
        """異常系: Repositoryのcount_tasksがTaskRepositoryErrorを発生した場合"""
        filters = schemas.TaskFilterParams()
        mock_repo.count_tasks.side_effect = TaskRepositoryError("Repository error")

        with pytest.raises(TaskRepositoryError):
            await task_service.get_task_summary(
                user_id="user-1",
                filters=filters,
            )


class TestCreateTask:
    """create_taskメソッドのテスト"""

    def test_create_task_with_all_fields_success(
        self, task_service: TaskService, mock_repo: Mock
    ) -> None:
        """正常系: 全フィールドを指定した場合、そのままRepositoryへ渡してIDを返す"""
        due_at = datetime(2026, 12, 31, 15, 0, tzinfo=UTC)
        req = schemas.TaskCreateRequest(
            title="Test Task",
            due_at=due_at,
            description="detail",
            priority=TASK_PRIORITY_HIGH,
            status=TASK_STATUS_IN_PROGRESS,
        )
        mock_repo.create.return_value = {"id": "task-123"}

        task_id = task_service.create_task(req, user_id="user-1")

        assert task_id == "task-123"
        mock_repo.create.assert_called_once_with(
            {
                "title": "Test Task",
                "status": TASK_STATUS_IN_PROGRESS,
                "priority": TASK_PRIORITY_HIGH,
                "dueAt": due_at,
                "description": "detail",
                "userId": "user-1",
            }
        )

    def test_create_task_defaults_status_and_priority_when_omitted(
        self, task_service: TaskService, mock_repo: Mock
    ) -> None:
        """正常系: status/priority未指定時はデフォルト値(TODO/MEDIUM)が使われる"""
        req = schemas.TaskCreateRequest(title="Minimal Task")
        mock_repo.create.return_value = {"id": "task-456"}

        task_service.create_task(req, user_id="user-1")

        called_data = mock_repo.create.call_args.args[0]
        assert called_data["status"] == TASK_STATUS_TODO
        assert called_data["priority"] == TASK_PRIORITY_MEDIUM

    def test_create_task_optional_fields_default_to_none(
        self, task_service: TaskService, mock_repo: Mock
    ) -> None:
        """正常系: due_at/description未指定時はNoneのままRepositoryへ渡される"""
        req = schemas.TaskCreateRequest(title="Minimal Task")
        mock_repo.create.return_value = {"id": "task-789"}

        task_service.create_task(req, user_id="user-1")

        called_data = mock_repo.create.call_args.args[0]
        assert called_data["dueAt"] is None
        assert called_data["description"] is None

    def test_create_task_status_zero_is_not_overridden_by_default(
        self, task_service: TaskService, mock_repo: Mock
    ) -> None:
        """エッジケース: status=0はfalsyだがNoneではないため、デフォルト値に上書きされない

        create_task は `req.status is not None` で判定しており、
        単純な truthy チェック(`if req.status`)であれば 0 が誤ってデフォルト値に
        置き換えられてしまうリグレッションを検知する。
        """
        req = schemas.TaskCreateRequest(title="Edge Task", status=0)
        mock_repo.create.return_value = {"id": "task-000"}

        task_service.create_task(req, user_id="user-1")

        called_data = mock_repo.create.call_args.args[0]
        assert called_data["status"] == 0

    def test_create_task_uses_user_id_argument(
        self, task_service: TaskService, mock_repo: Mock
    ) -> None:
        """正常系: userIdには引数で渡されたuser_idがそのまま使われる"""
        req = schemas.TaskCreateRequest(title="Task")
        mock_repo.create.return_value = {"id": "task-1"}

        task_service.create_task(req, user_id="user-abc")

        called_data = mock_repo.create.call_args.args[0]
        assert called_data["userId"] == "user-abc"

    def test_create_task_returns_id_from_repository_response(
        self, task_service: TaskService, mock_repo: Mock
    ) -> None:
        """正常系: Repositoryが返す辞書の"id"キーの値をそのまま返す(他のキーは無視する)"""
        req = schemas.TaskCreateRequest(title="Task")
        mock_repo.create.return_value = {
            "id": "generated-id",
            "title": "Task",
            "createdAt": datetime.now(UTC),
        }

        task_id = task_service.create_task(req, user_id="user-1")

        assert task_id == "generated-id"

    def test_create_task_repository_error_propagates(
        self, task_service: TaskService, mock_repo: Mock
    ) -> None:
        """異常系: RepositoryがTaskRepositoryErrorを送出した場合、そのまま呼び出し元へ伝播する"""
        req = schemas.TaskCreateRequest(title="Task")
        mock_repo.create.side_effect = TaskRepositoryError("Repository error")

        with pytest.raises(TaskRepositoryError):
            task_service.create_task(req, user_id="user-1")

    def test_create_task_does_not_use_calendar_link_generator(
        self,
        task_service: TaskService,
        mock_repo: Mock,
        mock_calendar_gen: Mock,
    ) -> None:
        """回帰防止: create_taskはCalendarLinkGeneratorを呼び出さない"""
        req = schemas.TaskCreateRequest(title="Task")
        mock_repo.create.return_value = {"id": "task-1"}

        task_service.create_task(req, user_id="user-1")

        mock_calendar_gen.generate.assert_not_called()

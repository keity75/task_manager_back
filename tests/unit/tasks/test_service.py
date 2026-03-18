"""TaskService単体テスト

Repository層や外部依存をモック化してTaskServiceのビジネスロジックをテストする。
"""

# ruff: noqa: S105, S106, SLF001, PLR2004

from unittest.mock import Mock

import pytest

from app.tasks import schemas
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

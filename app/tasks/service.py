import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time
from typing import Any, cast
from zoneinfo import ZoneInfo

from app.core.logging import get_logger
from app.core.schemas import PaginationParams
from app.core.settings import settings
from app.tasks import schemas
from app.tasks.calendar_links import CalendarLinkGenerator
from app.tasks.constants import (
    DEFAULT_SORT_BY,
    DEFAULT_SORT_ORDER,
    SORT_ORDER_ASC,
    TASK_PRIORITY_MEDIUM,
    TASK_STATUS_DONE,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_TODO,
)
from app.tasks.error_messages import TaskErrorMessages
from app.tasks.exceptions import TaskNotFoundError
from app.tasks.repository import TaskRepository

DEFAULT_TZ = ZoneInfo(settings.DEFAULT_TIMEZONE)
log = get_logger(__name__)

# TaskUpdateRequestのフィールド名(snake_case) -> Firestoreドキュメントのキー(camelCase)
_UPDATABLE_FIELD_TO_FIRESTORE_KEY = {
    "title": "title",
    "description": "description",
    "due_at": "dueAt",
    "priority": "priority",
    "status": "status",
}


class TaskService:
    """タスク関連のビジネスロジックを担当するサービスクラス"""

    def __init__(
        self,
        task_repo: TaskRepository,
        calendar_link_generator: CalendarLinkGenerator,
    ) -> None:
        """依存性を注入 (DI)。

        - task_repo: データアクセス層 (Repository)
        - calendar_link_generator: カレンダーリンク生成 (Strategy)
        """
        self.repo = task_repo
        self.calendar_link_generator = calendar_link_generator

    def create_task(self, req: schemas.TaskCreateRequest, user_id: str) -> str:
        """手動作成タスクを登録してIDを返す"""
        status = req.status if req.status is not None else TASK_STATUS_TODO
        priority = req.priority if req.priority is not None else TASK_PRIORITY_MEDIUM

        data = {
            "title": req.title,
            "status": status,
            "priority": priority,
            "dueAt": req.due_at,
            "description": req.description,
            "userId": user_id,
        }

        created = self.repo.create(data)
        return created["id"]

    async def get_task_summary(
        self,
        user_id: str,
        filters: schemas.TaskFilterParams,
    ) -> schemas.TaskSummaryResponse:
        """タスクの統計情報(Total, Todo, InProgress, Done)を取得する。

        ThreadPoolExecutorを使用して並列にクエリを実行し、レイテンシを最小化します。
        """
        # --- 共通のフィルタリング条件 (dueAt) の準備 ---
        due_at_from_utc, due_at_to_utc = self._resolve_due_at_range_utc(filters)

        # --- 並列クエリの実行準備 ---
        loop = asyncio.get_running_loop()

        # クエリ定義
        # Total (ステータス指定なし)
        total_filter_params = self._create_status_filter(filters, None)
        # Status: Todo
        todo_filter_params = self._create_status_filter(filters, TASK_STATUS_TODO)
        # InProgress
        in_progress_filter_params = self._create_status_filter(
            filters, TASK_STATUS_IN_PROGRESS
        )
        # Done
        done_filter_params = self._create_status_filter(filters, TASK_STATUS_DONE)

        # 並列実行 executor
        with ThreadPoolExecutor(max_workers=4) as executor:
            total_count_future = loop.run_in_executor(
                executor,
                self.repo.count_tasks,
                user_id,
                total_filter_params,
                due_at_from_utc,
                due_at_to_utc,
            )
            todo_count_future = loop.run_in_executor(
                executor,
                self.repo.count_tasks,
                user_id,
                todo_filter_params,
                due_at_from_utc,
                due_at_to_utc,
            )
            in_progress_count_future = loop.run_in_executor(
                executor,
                self.repo.count_tasks,
                user_id,
                in_progress_filter_params,
                due_at_from_utc,
                due_at_to_utc,
            )
            done_count_future = loop.run_in_executor(
                executor,
                self.repo.count_tasks,
                user_id,
                done_filter_params,
                due_at_from_utc,
                due_at_to_utc,
            )

            # return_exceptions=Trueで全Futureの結果(例外含む)を回収し、
            # 未回収例外ログを防ぎつつ最初の例外を再送出する。
            results = await asyncio.gather(
                total_count_future,
                todo_count_future,
                in_progress_count_future,
                done_count_future,
                return_exceptions=True,
            )

            for result in results:
                if isinstance(result, Exception):
                    raise result

            total, todo, in_progress, done = cast(
                "tuple[int, int, int, int]", results
            )

        return schemas.TaskSummaryResponse(
            total=total,
            todo=todo,
            in_progress=in_progress,
            done=done,
        )

    async def list_tasks(
        self,
        user_id: str,
        filters: schemas.TaskFilterParams,
        pagination: PaginationParams,
    ) -> tuple[list[schemas.TaskListItem], int]:
        """フィルター・ソート・ページネーション適用済みのタスク一覧とその総件数を取得する。

        一覧取得と総件数取得(カウント)をThreadPoolExecutorで並列実行する。
        """
        due_at_from_utc, due_at_to_utc = self._resolve_due_at_range_utc(filters)
        sort_by, order = self._resolve_sort(filters)

        loop = asyncio.get_running_loop()

        with ThreadPoolExecutor(max_workers=2) as executor:
            list_future = loop.run_in_executor(
                executor,
                self.repo.list,
                user_id,
                filters,
                due_at_from_utc,
                due_at_to_utc,
                sort_by,
                order,
                pagination.limit,
                pagination.offset,
            )
            count_future = loop.run_in_executor(
                executor,
                self.repo.count_tasks,
                user_id,
                filters,
                due_at_from_utc,
                due_at_to_utc,
            )

            results = await asyncio.gather(list_future, count_future, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    raise result

            raw_tasks, total_count = results

        items = [self._to_list_item(raw_task) for raw_task in raw_tasks]

        return items, total_count

    def get_task(self, task_id: str, user_id: str) -> schemas.TaskListItem:
        """タスク詳細を1件取得する

        存在しない、他ユーザーのタスク、削除済みタスクの場合はTaskNotFoundErrorを送出する。
        """
        raw_task = self.repo.get_by_id(user_id=user_id, task_id=task_id)
        if raw_task is None:
            raise TaskNotFoundError(TaskErrorMessages.TASK_NOT_FOUND)

        return self._to_list_item(raw_task)

    def update_task(
        self, task_id: str, req: schemas.TaskUpdateRequest, user_id: str
    ) -> str:
        """タスクを部分更新してIDを返す

        リクエストに含まれたフィールドのみ更新する(未指定フィールドは変更しない)。
        存在しない、他ユーザーのタスク、削除済みタスクの場合はTaskNotFoundErrorを送出する。
        """
        update_data = {
            _UPDATABLE_FIELD_TO_FIRESTORE_KEY[field_name]: getattr(req, field_name)
            for field_name in req.model_fields_set
        }

        updated = self.repo.update(user_id=user_id, task_id=task_id, data=update_data)
        if updated is None:
            raise TaskNotFoundError(TaskErrorMessages.TASK_NOT_FOUND)

        return updated["id"]

    def delete_task(self, task_id: str, user_id: str) -> str:
        """タスクを論理削除してIDを返す

        存在しない、他ユーザーのタスク、既に削除済みのタスクの場合はTaskNotFoundErrorを送出する。
        """
        deleted = self.repo.soft_delete(user_id=user_id, task_id=task_id)
        if deleted is None:
            raise TaskNotFoundError(TaskErrorMessages.TASK_NOT_FOUND)

        return deleted["id"]

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _to_list_item(self, raw_task: dict[str, Any]) -> schemas.TaskListItem:
        """Firestoreの生データをカレンダーリンク付きのレスポンスモデルに変換する"""
        task = schemas.Task(**raw_task)
        calendar_link = self.calendar_link_generator.generate(task)
        return schemas.TaskListItem(**task.model_dump(), calendar_link=calendar_link)

    def _resolve_due_at_range_utc(
        self, filters: schemas.TaskFilterParams
    ) -> tuple[datetime | None, datetime | None]:
        """フィルターの期限(日付)条件をUTCの範囲(from/to)に変換する

        due_at_fromは指定日のJST 00:00:00、due_at_toは指定日のJST 23:59:59.999999を
        それぞれUTCに変換して返す。
        """
        due_at_from_utc: datetime | None = None
        if filters.due_at_from:
            dt = datetime.combine(filters.due_at_from, time.min).replace(
                tzinfo=DEFAULT_TZ
            )
            due_at_from_utc = dt.astimezone(UTC)

        due_at_to_utc: datetime | None = None
        if filters.due_at_to:
            dt = datetime.combine(filters.due_at_to, time.max).replace(
                tzinfo=DEFAULT_TZ
            )
            due_at_to_utc = dt.astimezone(UTC)

        return due_at_from_utc, due_at_to_utc

    def _resolve_sort(self, filters: schemas.TaskFilterParams) -> tuple[str, str]:
        """ソート条件を解決する

        sort_by未指定時は作成日時の降順をデフォルトとする。
        sort_byが指定されorderが未指定の場合は昇順をデフォルトとする。
        """
        if filters.sort_by is None:
            return DEFAULT_SORT_BY, DEFAULT_SORT_ORDER

        return filters.sort_by, filters.order or SORT_ORDER_ASC

    def _create_status_filter(
        self, base_filters: schemas.TaskFilterParams, status: int | None
    ) -> schemas.TaskFilterParams:
        """指定されたStatus条件を適用した新しいフィルターパラメータを作成するヘルパー"""
        new_filters = schemas.TaskFilterParams()
        new_filters.title = base_filters.title
        new_filters.due_at_from = base_filters.due_at_from
        new_filters.due_at_to = base_filters.due_at_to
        new_filters.priority = base_filters.priority

        if status is not None:
            new_filters.status = [status]
        else:
            new_filters.status = None

        return new_filters

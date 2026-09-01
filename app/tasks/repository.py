from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from app.tasks import schemas


@runtime_checkable
class TaskRepository(Protocol):
    """タスクデータアクセス層のインターフェース"""

    def count_tasks(
        self,
        user_id: str,
        filters: schemas.TaskFilterParams,
        due_at_from_utc: datetime | None,
        due_at_to_utc: datetime | None,
    ) -> int:
        """全てのタスクの総件数を取得する (フィルター適用後)"""
        ...

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        """タスクを作成して返す (ID付与済み辞書)"""
        ...

    def list(
        self,
        user_id: str,
        filters: schemas.TaskFilterParams,
        due_at_from_utc: datetime | None,
        due_at_to_utc: datetime | None,
        sort_by: str,
        order: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        """フィルター・ソート・ページネーションを適用したタスク一覧を取得する"""
        ...

    def get_by_id(self, user_id: str, task_id: str) -> dict[str, Any] | None:
        """IDでタスクを1件取得する。存在しない、または削除済みの場合はNoneを返す"""
        ...

    def update(
        self, user_id: str, task_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """タスクを部分更新して返す。存在しない、または削除済みの場合はNoneを返す

        dataには更新対象フィールドのみを含める。
        """
        ...

    def soft_delete(self, user_id: str, task_id: str) -> dict[str, Any] | None:
        """タスクを論理削除する。存在しない、または既に削除済みの場合はNoneを返す"""
        ...

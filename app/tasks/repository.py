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

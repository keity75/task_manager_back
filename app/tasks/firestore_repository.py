from datetime import UTC, datetime
from functools import cache
from typing import Annotated, Any

from fastapi import Depends
from google.cloud.firestore import Client as FirestoreClient
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.collection import CollectionReference
from google.cloud.firestore_v1.document import DocumentReference
from google.cloud.firestore_v1.query import Query

from app.core.dependencies import get_db
from app.core.logging import get_logger
from app.tasks import schemas
from app.tasks.error_messages import TaskErrorMessages
from app.tasks.exceptions import TaskRepositoryError
from app.tasks.repository import TaskRepository

log = get_logger(__name__)


class FirestoreTaskRepository(TaskRepository):
    """Firestoreを使用したタスクリポジトリの実装"""

    def __init__(self, client: FirestoreClient) -> None:
        self.client = client

    def _get_user_doc_ref(self, user_id: str) -> DocumentReference:
        """(ヘルパー) ユーザードキュメントへの参照を取得"""
        if not user_id:
            raise TaskRepositoryError(TaskErrorMessages.USER_ID_REQUIRED)
        return self.client.collection("users").document(user_id)

    def _get_tasks_collection(self, user_id: str) -> CollectionReference:
        """(ヘルパー) tasksサブコレクションへの参照を取得"""
        user_doc_ref = self._get_user_doc_ref(user_id)
        return user_doc_ref.collection("tasks")

    def _build_filtered_query(
        self,
        collection_ref: CollectionReference,
        filters: schemas.TaskFilterParams,
        due_at_from_utc: datetime | None,
        due_at_to_utc: datetime | None,
    ) -> Query:
        """フィルター条件に基づいてFirestoreクエリを構築する共通メソッド"""
        # クエリを構築(deletedAt == Noneの条件を必ず含める)
        query = collection_ref.where(filter=FieldFilter("deletedAt", "==", None))

        # フィルター条件を適用
        # 1. 優先度 (priority) - where_inを使用
        if filters.priority:
            query = query.where(filter=FieldFilter("priority", "in", filters.priority))

        # 2. ステータス (status) - where_inを使用
        if filters.status:
            query = query.where(filter=FieldFilter("status", "in", filters.status))

        # 3. タスク期限 (dueAtFrom / dueAtTo)
        if due_at_from_utc:
            query = query.where(filter=FieldFilter("dueAt", ">=", due_at_from_utc))

        if due_at_to_utc:
            query = query.where(filter=FieldFilter("dueAt", "<=", due_at_to_utc))

        # 4. タイトル前方一致
        title_keyword = (filters.title or "").strip()
        if title_keyword:
            query = query.where(filter=FieldFilter("title", ">=", title_keyword)).where(
                filter=FieldFilter("title", "<", title_keyword + "\uf8ff")
            )

        return query

    def count_tasks(
        self,
        user_id: str,
        filters: schemas.TaskFilterParams,
        due_at_from_utc: datetime | None,
        due_at_to_utc: datetime | None,
    ) -> int:
        """Firestoreからフィルター適用後のタスク総件数を取得"""
        try:
            tasks_collection = self._get_tasks_collection(user_id)

            # 共通のフィルタークエリを構築
            query = self._build_filtered_query(
                tasks_collection,
                filters,
                due_at_from_utc,
                due_at_to_utc,
            )

            # 集約クエリを使用して件数を取得(ドキュメント本体を転送しない)
            count_result = query.count().get()  # type: ignore[call-arg]
            return int(count_result[0][0].value)  # type: ignore[index]
        except Exception as err:
            log.warning(
                "Failed to count tasks from Firestore.",
                user_id=user_id,
                error_type=type(err).__name__,
                original_error=str(err),
            )
            raise TaskRepositoryError(TaskErrorMessages.FAILED_TO_COUNT_TASKS) from err

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        """Firestoreにタスクを作成し、自動採番IDで返す。"""
        user_id = data.get("userId")
        if not user_id:
            raise TaskRepositoryError(TaskErrorMessages.USER_ID_REQUIRED)
        try:
            tasks_collection = self._get_tasks_collection(user_id)
            doc_ref = tasks_collection.document()  # Auto-ID

            # タイムスタンプはRepository層で設定(DB非依存)
            now_utc = datetime.now(UTC)
            # 新規作成時はdeletedAtをnullに設定、createdAt/updatedAtを設定
            new_task = {
                **data,
                "id": doc_ref.id,
                "createdAt": now_utc,
                "updatedAt": now_utc,
                "deletedAt": None,
            }
            doc_ref.set(new_task)
        except Exception as err:
            log.warning(
                "Failed to create task in Firestore.",
                user_id=user_id,
                original_error=str(err),
            )
            raise TaskRepositoryError(TaskErrorMessages.FAILED_TO_CREATE_TASK) from err
        else:
            return new_task


@cache
def get_task_repository(
    db: Annotated[FirestoreClient, Depends(get_db)],
) -> TaskRepository:
    """Dependency provider.

    この関数は FastAPI によって最初に呼び出された時に一度だけ実行されます。
    """
    return FirestoreTaskRepository(client=db)

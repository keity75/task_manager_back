from typing import Annotated

from fastapi import Depends, Response, status

from app.core import schemas as core_schemas
from app.core.dependencies import CurrentUserId
from app.core.logging import get_logger
from app.core.router import BaseAPIRouter
from app.core.settings import settings
from app.tasks import schemas
from app.tasks.dependencies import get_task_service
from app.tasks.service import TaskService

log = get_logger()

router = BaseAPIRouter(
    prefix="/tasks",
    tags=["Tasks"],
)


@router.get(
    "",
    response_model=core_schemas.SuccessResponse[list[schemas.TaskListItem]],
    summary="タスク一覧の取得",
    description=(
        "認証済みユーザーのタスク一覧を取得します(削除済みタスクを除く)。"
        "タイトル前方一致・ステータス・優先度・期限範囲によるフィルタリング、"
        "ソート、ページネーションに対応します。"
    ),
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": core_schemas.ErrorResponse},
    },
)
async def list_tasks(
    service: Annotated[TaskService, Depends(get_task_service)],
    filters: Annotated[schemas.TaskFilterParams, Depends()],
    pagination: Annotated[core_schemas.PaginationParams, Depends()],
    current_user_id: CurrentUserId,
) -> core_schemas.SuccessResponse[list[schemas.TaskListItem]]:
    """認証済みユーザーのタスク一覧を取得する"""
    tasks, total_count = await service.list_tasks(
        user_id=current_user_id,
        filters=filters,
        pagination=pagination,
    )
    return core_schemas.SuccessResponse(
        data=tasks,
        pagination=core_schemas.PaginationInfo(
            total_count=total_count,
            limit=pagination.limit,
            offset=pagination.offset,
        ),
    )


@router.get(
    "/summary",
    response_model=core_schemas.SuccessResponse[schemas.TaskSummaryResponse],
    summary="タスク統計情報の取得",
    description="タスクのステータス別集計結果(Total/Todo/InProgress/Done)を取得します。期限(dueAt)によるフィルタリングが可能です。",
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": core_schemas.ErrorResponse},
    },
)
async def get_task_summary(
    service: Annotated[TaskService, Depends(get_task_service)],
    filters: Annotated[schemas.TaskFilterParams, Depends()],
    current_user_id: CurrentUserId,
) -> core_schemas.SuccessResponse[schemas.TaskSummaryResponse]:
    """タスク集計情報を取得する"""
    summary = await service.get_task_summary(user_id=current_user_id, filters=filters)
    return core_schemas.SuccessResponse(data=summary)


@router.post(
    "",
    response_model=core_schemas.SuccessResponse[schemas.TaskIdResponse],
    summary="タスクの手動作成",
    description=("ユーザーが手動でタスクを作成します。"),
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_201_CREATED: {
            "description": "タスクが正常に作成されました。",
            "headers": {
                "Location": {
                    "description": "作成されたタスクリソースへのURLパスです。",
                    "schema": {"type": "string"},
                    "example": f"{settings.API_PREFIX}{settings.API_VERSION}/tasks/task_abc_123",
                }
            },
        },
        status.HTTP_400_BAD_REQUEST: {"model": core_schemas.ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": core_schemas.ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": core_schemas.ErrorResponse},
    },
)
def create_task(
    req: schemas.TaskCreateRequest,
    service: Annotated[TaskService, Depends(get_task_service)],
    response: Response,
    current_user_id: CurrentUserId,
) -> core_schemas.SuccessResponse[schemas.TaskIdResponse]:
    """手動でタスクを作成する"""
    task_id = service.create_task(req, user_id=current_user_id)
    response.headers["Location"] = (
        f"{settings.API_PREFIX}{settings.API_VERSION}/tasks/{task_id}"
    )
    return core_schemas.SuccessResponse(data=schemas.TaskIdResponse(id=task_id))

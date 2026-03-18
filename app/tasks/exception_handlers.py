from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.core.schemas import ErrorDetail, ErrorResponse
from app.tasks.exceptions import TaskRepositoryError

log = get_logger(__name__)


def handle_task_repository_error(
    _request: Request, exc: TaskRepositoryError
) -> JSONResponse:
    """タスクリポジトリエラーの例外ハンドラ (500 Internal Server Error)"""
    log.error(
        "Task repository error",
        error_message=exc.message,
        exc_info=exc,
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            status="error",
            error=ErrorDetail(
                code="TASK_REPOSITORY_ERROR", message="Failed to access task data"
            ),
        ).model_dump(),
    )

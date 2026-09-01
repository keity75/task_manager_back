from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.core.schemas import ErrorDetail, ErrorResponse
from app.tasks.exceptions import TaskNotFoundError, TaskRepositoryError

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


def handle_task_not_found_error(
    _request: Request, exc: TaskNotFoundError
) -> JSONResponse:
    """タスクが見つからない場合の例外ハンドラ (404 Not Found)

    所有者不一致・削除済みタスクへのアクセスもこのエラーとして扱う。
    """
    log.warning(
        "Task not found.",
        error_message=exc.message,
    )

    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=ErrorResponse(
            status="error",
            error=ErrorDetail(code="TASK_NOT_FOUND", message=exc.message),
        ).model_dump(),
    )

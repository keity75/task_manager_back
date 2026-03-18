from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status

from app.core.logging import get_logger
from app.core.schemas import ErrorDetail, ErrorResponse

log = get_logger()


async def handle_validation_error(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """リクエストのバリデーションエラーを捕捉し、指定されたJSON形式で422エラーを返す。"""
    # 複数のバリデーションエラーを一つのメッセージにまとめる
    # 例: "body->email: value is not a valid email address; body->age: Input should be greater than 18"
    error_messages = [
        f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in exc.errors()
    ]
    message = "; ".join(error_messages)
    error_detail = ErrorDetail(
        code="VALIDATION_ERROR",
        message=message,
    )
    log.warning(
        "Validation error occurred.",
        error_code=error_detail.code,
        original_error=message,
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse(error=error_detail).model_dump(),
    )


async def handle_generic_exception(
    _request: Request,
    exc: Exception,
) -> JSONResponse:
    """その他の予期せぬ例外を捕捉し、指定されたJSON形式で500エラーを返す。"""
    error_detail = ErrorDetail(
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected internal server error occurred.",
    )
    log.error(
        "An unexpected error occurred.",
        error_code=error_detail.code,
        original_error=str(exc),
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(error=error_detail).model_dump(),
    )

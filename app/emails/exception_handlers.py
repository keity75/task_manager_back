from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.core.schemas import ErrorDetail, ErrorResponse
from app.emails.exceptions import (
    EmailNotFoundError,
    GmailPermissionDeniedError,
    GmailRepositoryError,
)

log = get_logger(__name__)


def handle_gmail_permission_denied_error(
    _request: Request, exc: GmailPermissionDeniedError
) -> JSONResponse:
    """Gmail APIから権限不足(403)が返された場合の例外ハンドラ (403 Forbidden)

    OAuth同意スコープにGmail読み取り権限が含まれていない等が原因のため、
    フロントエンドが再認証を促せるよう他のGmail APIエラーとは別のコードを返す。
    """
    log.warning(
        "Gmail permission denied.",
        error_message=exc.message,
    )

    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content=ErrorResponse(
            status="error",
            error=ErrorDetail(code="GMAIL_PERMISSION_DENIED", message=exc.message),
        ).model_dump(),
    )


def handle_gmail_repository_error(
    _request: Request, exc: GmailRepositoryError
) -> JSONResponse:
    """Gmail APIアクセスエラーの例外ハンドラ (502 Bad Gateway)

    外部サービス(Gmail API)への接続・応答不正が原因のため、内部エラー(500)ではなく
    アップストリーム起因を示す502を返す。
    """
    log.error(
        "Gmail repository error",
        error_message=exc.message,
        exc_info=exc,
    )

    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content=ErrorResponse(
            status="error",
            error=ErrorDetail(
                code="GMAIL_API_ERROR", message="Failed to access Gmail data"
            ),
        ).model_dump(),
    )


def handle_email_not_found_error(
    _request: Request, exc: EmailNotFoundError
) -> JSONResponse:
    """メールが見つからない場合の例外ハンドラ (404 Not Found)

    所有者不一致のメールへのアクセスもこのエラーとして扱う。
    """
    log.warning(
        "Email not found.",
        error_message=exc.message,
    )

    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=ErrorResponse(
            status="error",
            error=ErrorDetail(code="EMAIL_NOT_FOUND", message=exc.message),
        ).model_dump(),
    )

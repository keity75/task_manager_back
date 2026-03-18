from fastapi import Request
from fastapi.responses import JSONResponse
from starlette import status

from app.auth.exceptions import (
    AuthRepositoryError,
    AuthSyncError,
    EmailDomainNotAllowedError,
    InvalidAccessTokenError,
    InvalidRefreshTokenError,
    ProviderNotFoundError,
    TokenRefreshError,
    TokenUpdateError,
)
from app.core.logging import get_logger
from app.core.schemas import ErrorDetail, ErrorResponse

log = get_logger()


async def handle_email_domain_not_allowed_error(
    _request: Request,
    exc: EmailDomainNotAllowedError,
) -> JSONResponse:
    """許可されていないメールドメインでのログイン試行をハンドリングする (403 Forbidden)。"""
    error_detail = ErrorDetail(
        code="EMAIL_DOMAIN_NOT_ALLOWED",
        message=str(exc),
    )
    log.warning(
        "Email domain not allowed.",
        error_code=error_detail.code,
        original_error=error_detail.message,
    )
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content=ErrorResponse(error=error_detail).model_dump(),
    )


async def handle_auth_sync_error(
    _request: Request,
    exc: AuthSyncError,
) -> JSONResponse:
    """認証同期処理全体の失敗をハンドリングする (500 Internal Server Error)。"""
    error_detail = ErrorDetail(
        code="AUTH_SYNC_ERROR",
        message="Authentication synchronization failed.",
    )
    log.error(
        "Authentication sync failed.",
        error_code=error_detail.code,
        original_error=str(exc),
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(error=error_detail).model_dump(),
    )


async def handle_token_update_error(
    _request: Request,
    exc: TokenUpdateError,
) -> JSONResponse:
    """トークン更新に失敗した場合の例外ハンドラ (500 Internal Server Error)。"""
    error_detail = ErrorDetail(
        code="TOKEN_UPDATE_ERROR",
        message="Failed to update authentication tokens.",
    )
    log.error(
        "Token update error during authentication.",
        error_code=error_detail.code,
        original_error=str(exc),
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(error=error_detail).model_dump(),
    )


async def handle_auth_repository_error(
    _request: Request,
    exc: AuthRepositoryError,
) -> JSONResponse:
    """認証リポジトリエラーの例外ハンドラ (500 Internal Server Error)。"""
    error_detail = ErrorDetail(
        code="AUTH_REPOSITORY_ERROR",
        message="Failed to access authentication data store.",
    )
    log.error(
        "Auth repository error.",
        error_code=error_detail.code,
        original_error=str(exc),
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(error=error_detail).model_dump(),
    )


async def handle_invalid_refresh_token_error(
    _request: Request,
    exc: InvalidRefreshTokenError,
) -> JSONResponse:
    """リフレッシュトークンが無効または期限切れの場合の例外ハンドラ (401 Unauthorized)。"""
    error_detail = ErrorDetail(
        code="INVALID_REFRESH_TOKEN",
        message=str(exc) or "Invalid or expired refresh token.",
    )
    log.warning(
        "Invalid refresh token.",
        error_code=error_detail.code,
        original_error=error_detail.message,
    )
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content=ErrorResponse(error=error_detail).model_dump(),
        headers={"WWW-Authenticate": "Bearer"},
    )


async def handle_invalid_access_token_error(
    _request: Request,
    exc: InvalidAccessTokenError,
) -> JSONResponse:
    """アクセストークンが無効または期限切れの場合の例外ハンドラ (401 Unauthorized)。"""
    error_detail = ErrorDetail(
        code="INVALID_ACCESS_TOKEN",
        message=str(exc) or "Invalid or expired access token.",
    )
    log.warning(
        "Invalid access token.",
        error_code=error_detail.code,
        original_error=error_detail.message,
    )
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content=ErrorResponse(error=error_detail).model_dump(),
        headers={"WWW-Authenticate": "Bearer"},
    )


async def handle_provider_not_found_error(
    _request: Request,
    exc: ProviderNotFoundError,
) -> JSONResponse:
    """プロバイダー情報が見つからない場合の例外ハンドラ (500 Internal Server Error)。"""
    error_detail = ErrorDetail(
        code="PROVIDER_NOT_FOUND",
        message="Provider authentication information not found.",
    )
    log.error(
        "Provider not found error.",
        error_code=error_detail.code,
        original_error=str(exc),
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(error=error_detail).model_dump(),
    )


async def handle_token_refresh_error(
    _request: Request,
    exc: TokenRefreshError,
) -> JSONResponse:
    """プロバイダートークンのリフレッシュに失敗した場合の例外ハンドラ (500 Internal Server Error)。"""
    error_detail = ErrorDetail(
        code="TOKEN_REFRESH_ERROR",
        message="Failed to refresh provider token.",
    )
    log.error(
        "Provider token refresh failed.",
        error_code=error_detail.code,
        original_error=str(exc),
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(error=error_detail).model_dump(),
    )

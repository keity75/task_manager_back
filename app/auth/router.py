from typing import Annotated

from fastapi import Depends, status

from app.auth import schemas
from app.auth.dependencies import get_auth_service
from app.auth.service import AuthService
from app.core import schemas as core_schemas
from app.core.logging import get_logger
from app.core.router import BaseAPIRouter

log = get_logger()

router = BaseAPIRouter(
    prefix="/auth",
    tags=["Auth"],
)


# =============================================================================
# 認証情報同期 (/auth/sync)
# =============================================================================


@router.post(
    "/sync",
    response_model=core_schemas.SuccessResponse[schemas.AuthSyncResponse],
    summary="認証情報同期",
    description=(
        "OAuth2認証後にNextAuthから呼び出され、"
        "プロバイダー認証情報をバックエンドと同期し、APIトークンを発行する。"
        "初回呼び出し時は新規ユーザーとして登録される。"
    ),
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": core_schemas.ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": core_schemas.ErrorResponse},
    },
)
async def sync_auth(
    req: schemas.AuthSyncRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> core_schemas.SuccessResponse[schemas.AuthSyncResponse]:
    """認証情報同期API。"""
    result = service.sync_auth(req)
    return core_schemas.SuccessResponse(data=result)


# =============================================================================
# トークンリフレッシュ (/auth/token/refresh)
# =============================================================================


@router.post(
    "/token/refresh",
    response_model=core_schemas.SuccessResponse[schemas.AuthTokenRefreshResponse],
    summary="バックエンドAPIトークンリフレッシュ",
    description=(
        "アクセストークン期限切れ時にリフレッシュトークンを使用して"
        "新しいアクセストークンを発行する。"
    ),
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": core_schemas.ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": core_schemas.ErrorResponse},
    },
)
async def refresh_token(
    req: schemas.AuthTokenRefreshRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> core_schemas.SuccessResponse[schemas.AuthTokenRefreshResponse]:
    """バックエンドAPIトークンリフレッシュAPI。"""
    result = service.refresh_token(req)
    return core_schemas.SuccessResponse(data=result)


# =============================================================================
# ログアウト (/auth/logout)
# =============================================================================


@router.post(
    "/logout",
    response_model=core_schemas.SuccessResponse[dict],
    summary="ログアウト",
    description="リフレッシュトークンを無効化(revoke)する。",
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": core_schemas.ErrorResponse},
    },
)
async def logout(
    req: schemas.LogoutRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> core_schemas.SuccessResponse[dict]:
    """ログアウトAPI。リフレッシュトークンを無効化する。

    このエンドポイントは冪等です。
    既に無効化されたトークンや存在しないトークンに対するリクエストも200 OKを返します。
    """
    service.revoke_refresh_token(req.refresh_token)
    return core_schemas.SuccessResponse(data={"message": "Logged out successfully"})

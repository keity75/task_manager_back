from typing import Annotated

from fastapi import Depends, status

from app.core import schemas as core_schemas
from app.core.dependencies import CurrentUserId
from app.core.logging import get_logger
from app.core.router import BaseAPIRouter
from app.emails import schemas
from app.emails.dependencies import get_email_service
from app.emails.service import EmailService

log = get_logger()

router = BaseAPIRouter(
    prefix="/emails",
    tags=["Emails"],
)


@router.get(
    "",
    response_model=core_schemas.SuccessResponse[list[schemas.EmailListItem]],
    summary="メール一覧の取得",
    description=(
        "認証済みユーザーのGmailからメール一覧を取得します。"
        "件名・送信者・受信日範囲によるフィルタリング、ページネーションに対応します。"
        "並び順は受信日時の降順(新しい順)固定です。"
    ),
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": core_schemas.ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": core_schemas.ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": core_schemas.ErrorResponse},
    },
)
async def list_emails(
    service: Annotated[EmailService, Depends(get_email_service)],
    filters: Annotated[schemas.EmailFilterParams, Depends()],
    pagination: Annotated[core_schemas.PaginationParams, Depends()],
    current_user_id: CurrentUserId,
) -> core_schemas.SuccessResponse[list[schemas.EmailListItem]]:
    """認証済みユーザーのGmailメール一覧を取得する"""
    emails, total_count = await service.list_emails(
        user_id=current_user_id,
        filters=filters,
        pagination=pagination,
    )
    return core_schemas.SuccessResponse(
        data=emails,
        pagination=core_schemas.PaginationInfo(
            total_count=total_count,
            limit=pagination.limit,
            offset=pagination.offset,
        ),
    )


@router.get(
    "/{email_id}",
    response_model=core_schemas.SuccessResponse[schemas.EmailDetailResponse],
    summary="メール詳細の取得",
    description="指定されたIDのメール詳細(本文含む)を取得します。存在しないメールは404を返します。",
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": core_schemas.ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": core_schemas.ErrorResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": core_schemas.ErrorResponse},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": core_schemas.ErrorResponse},
    },
)
async def get_email(
    email_id: str,
    service: Annotated[EmailService, Depends(get_email_service)],
    current_user_id: CurrentUserId,
) -> core_schemas.SuccessResponse[schemas.EmailDetailResponse]:
    """指定されたIDのメール詳細を取得する"""
    email = await service.get_email(user_id=current_user_id, message_id=email_id)
    return core_schemas.SuccessResponse(data=email)

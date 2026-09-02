from typing import Annotated

from fastapi import Depends

from app.auth.dependencies import get_provider_token_service
from app.auth.provider_token_service import ProviderTokenService
from app.emails.gmail_repository import get_gmail_repository
from app.emails.repository import GmailRepository
from app.emails.service import EmailService


def get_email_service(
    gmail_repo: Annotated[GmailRepository, Depends(get_gmail_repository)],
    provider_token_service: Annotated[
        ProviderTokenService, Depends(get_provider_token_service)
    ],
) -> EmailService:
    """GmailRepositoryとProviderTokenServiceを注入してEmailServiceのインスタンスを生成する

    Args:
        gmail_repo: Gmailリポジトリ
        provider_token_service: Googleプロバイダートークン管理サービス

    Returns:
        EmailService

    """
    return EmailService(
        gmail_repo=gmail_repo,
        provider_token_service=provider_token_service,
    )

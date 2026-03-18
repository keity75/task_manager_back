from typing import Annotated

from fastapi import Depends
from google.cloud import firestore

from app.auth.provider_token_service import ProviderTokenService
from app.auth.repository import AuthRepository
from app.auth.service import AuthService
from app.clients.http import HttpClient, get_http_client
from app.core.dependencies import get_db


def get_auth_repository(
    db: Annotated[firestore.Client, Depends(get_db)],
) -> AuthRepository:
    """AuthRepositoryインスタンスを取得する

    FastAPIのDependsで使用するための関数。
    """
    return AuthRepository(db)


def get_auth_service(
    repo: Annotated[AuthRepository, Depends(get_auth_repository)],
) -> AuthService:
    """AuthRepository を注入して AuthService を生成する"""
    return AuthService(auth_repository=repo)


def get_provider_token_service(
    auth_repo: Annotated[AuthRepository, Depends(get_auth_repository)],
    http_client: Annotated[HttpClient, Depends(get_http_client)],
) -> ProviderTokenService:
    """ProviderTokenServiceインスタンスを取得する

    FastAPIのDependsで使用するための関数。
    将来のGmail/Calendar API統合時に使用。
    """
    return ProviderTokenService(auth_repository=auth_repo, http_client=http_client)

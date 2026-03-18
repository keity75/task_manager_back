from typing import Annotated, Any

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.cloud import firestore

from app.auth.exceptions import InvalidAccessTokenError
from app.core.settings import settings

# HTTPBearer スキームを使用してトークンを取得
security = HTTPBearer(auto_error=False)


def get_db(request: Request) -> firestore.Client:
    """アプリケーションステートからFirestoreクライアントを取得する(main.pyのlifespanで初期化されたもの)

    リクエストオブジェクト (app.state.db) を経由して、
    lifespanで初期化された単一のクライアントインスタンスを取得します。
    """
    return request.app.state.db


def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> str:
    """バックエンドAPIトークン(JWT)を検証し、ユーザーIDを返す

    全ての保護されたエンドポイントで使用する依存関係。
    """
    if credentials is None:
        message = "Authorization header is missing"
        raise InvalidAccessTokenError(message)

    token = credentials.credentials

    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.BACKEND_JWT_SECRET,
            algorithms=["HS256"],
        )

        if payload.get("type") != "access":
            message = "Invalid token type"
            raise InvalidAccessTokenError(message)

        user_id = payload.get("sub")
        if not user_id:
            message = "Invalid token payload"
            raise InvalidAccessTokenError(message)

    except InvalidAccessTokenError:
        raise
    except jwt.ExpiredSignatureError as err:
        message = "Token has expired"
        raise InvalidAccessTokenError(message) from err
    except jwt.InvalidTokenError as err:
        message = "Invalid token"
        raise InvalidAccessTokenError(message) from err

    return user_id


# 認証済みユーザーIDを取得するための型エイリアス
CurrentUserId = Annotated[str, Depends(get_current_user_id)]

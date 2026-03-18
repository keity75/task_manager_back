from typing import Any

from fastapi import APIRouter
from starlette import status

from .schemas import ErrorResponse


class BaseAPIRouter(APIRouter):
    """プロジェクト標準のAPIRouter。

    共通のエラーレスポンス定義など、全APIで統一すべき設定を管理します。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # 422バリデーションエラーのレスポンス形式を、SwaggerUIに明記する
        default_responses = {
            status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse},
        }
        # 既存のresponsesがあればマージする
        if "responses" in kwargs:
            kwargs["responses"].update(default_responses)
        else:
            kwargs["responses"] = default_responses
        # APIRouterを初期化
        super().__init__(*args, **kwargs)

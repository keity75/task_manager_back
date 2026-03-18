from typing import Annotated, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class CamelModel(BaseModel):
    """JSONのキーをcamelCase、Pythonの属性をsnake_caseで扱うための基底モデル"""

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )


class PaginationInfo(CamelModel):
    """ページネーション情報モデル"""

    total_count: int = Field(..., description="総件数")
    limit: int = Field(..., description="1ページあたりの件数")
    offset: int = Field(..., description="オフセット")


class SuccessResponse(BaseModel, Generic[T]):
    """API成功時の共通レスポンス形式"""

    status: str = Field(default="success", description="レスポンスのステータス")
    data: T
    pagination: PaginationInfo | None = Field(
        default=None, description="ページネーション情報 (一覧取得時)"
    )


class ErrorDetail(BaseModel):
    """エラー詳細の構造を定義するPydanticモデル。"""

    code: str = Field(..., description="独自のエラーコード")
    message: str = Field(..., description="エラーメッセージ")


class ErrorResponse(BaseModel):
    """APIの失敗時に返却される共通のエラーレスポンス構造。"""

    status: str = Field("error", description="レスポンスのステータス")
    error: ErrorDetail


class PaginationParams:
    """ページネーション (limit / offset) のためのDI用クラス"""

    def __init__(
        self,
        limit: Annotated[
            int,
            Query(ge=1, le=100, description="1ページあたりの取得件数"),
        ] = 20,
        offset: Annotated[int, Query(ge=0, description="取得開始位置")] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset

from datetime import date, datetime
from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, Field, field_validator

from app.core.schemas import CamelModel
from app.core.validation import (
    validate_datetime_with_default_tz,
    validate_in_choices,
    validate_max_length,
    validate_required,
)

ALLOWED_PRIORITIES = {1, 2, 3, 4}


class Task(CamelModel):
    """タスクの基本情報モデル (DBやMockデータに対応)

    PydanticがJSONのISO文字列(str)を自動でdatetimeにパースします。
    """

    id: str
    title: str
    status: int
    priority: int
    due_at: datetime | None = None
    description: str | None = None
    user_id: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class TaskSummaryResponse(CamelModel):
    """タスク集計APIのレスポンス"""

    total: int
    todo: int
    in_progress: int
    done: int


class TaskCreateRequest(CamelModel):
    """手動タスク作成用のリクエストモデル"""

    title: str = Field(..., max_length=255, description="255文字以下")
    due_at: datetime | None = Field(
        default=None,
        description="ISO 8601形式の日時。タイムゾーン情報がない場合はJSTとして解釈される",
    )
    description: str | None = Field(default=None, max_length=100000)
    priority: int | None = Field(default=None, description="1/2/3/4。4=緊急。未指定は2")
    status: int | None = Field(default=None, description="10/20/30。未指定は10")

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        """titleフィールドの必須・最大長を検証する。"""
        # Pydanticモデルがバリデーション関数を呼び出す
        validate_required(v, field_name="title")
        validate_max_length(v, max_len=255, field_name="title")
        return v

    @field_validator("due_at")
    @classmethod
    def validate_due_at(cls, v: datetime | None) -> datetime | None:
        """dueAtフィールドを柔軟に受け入れ、UTCに正規化する。"""
        if v is not None:
            v = validate_datetime_with_default_tz(v, field_name="dueAt")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: int | None) -> int | None:
        """priorityを許容範囲(1-4)に限定する。"""
        validate_in_choices(
            v,
            choices=ALLOWED_PRIORITIES,
            field_name="priority",
            allow_none=True,
        )
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str | None) -> str | None:
        """descriptionフィールドの最大長を検証する。"""
        if v is not None:
            validate_max_length(v, max_len=100000, field_name="description")
        return v


class TaskIdResponse(BaseModel):
    """作成直後のIDのみ返すレスポンスモデル"""

    id: str


class TaskFilterParams:
    """タスク一覧のフィルタリング条件 (DI用クラス)

    FastAPIの Depends() によって、__init__ の引数が解決されます
    """

    def __init__(
        self,
        title: Annotated[str | None, Query(description="タスク名(前方一致)")] = None,
        priority: Annotated[
            list[int] | None, Query(description="優先度(複数指定可)")
        ] = None,
        status: Annotated[
            list[int] | None, Query(description="ステータス(複数指定可)")
        ] = None,
        due_at_from: Annotated[
            date | None, Query(alias="dueAtFrom", description="タスク期限 (From)")
        ] = None,
        due_at_to: Annotated[
            date | None, Query(alias="dueAtTo", description="タスク期限 (To)")
        ] = None,
    ) -> None:
        self.title = title or None
        self.priority = priority
        self.status = status
        self.due_at_from = due_at_from
        self.due_at_to = due_at_to

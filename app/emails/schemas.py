from datetime import date, datetime
from typing import Annotated

from fastapi import Query
from pydantic import Field

from app.core.schemas import CamelModel


class EmailListItem(CamelModel):
    """メール一覧APIのレスポンスアイテム"""

    id: str = Field(..., description="GmailのメッセージID")
    subject: str = Field(..., description="件名")
    from_: str = Field(
        ..., alias="from", description='送信者(例: "田中太郎 <tanaka@example.com>")'
    )
    received_at: datetime = Field(..., description="受信日時(UTC)")


class EmailDetailResponse(EmailListItem):
    """メール詳細APIのレスポンス(本文付き)"""

    body: str = Field(..., description="本文(プレーンテキスト、改行は\\n)")


class EmailFilterParams:
    """メール一覧のフィルタリング条件 (DI用クラス)

    FastAPIの Depends() によって、__init__ の引数が解決されます
    """

    def __init__(
        self,
        subject: Annotated[
            str | None, Query(description="件名(部分一致、大文字小文字を区別しない)")
        ] = None,
        from_: Annotated[
            str | None,
            Query(
                alias="from",
                description="送信者(部分一致、大文字小文字を区別しない)",
            ),
        ] = None,
        received_at_from: Annotated[
            date | None,
            Query(alias="receivedAtFrom", description="受信日(From、当日00:00を含む)"),
        ] = None,
        received_at_to: Annotated[
            date | None,
            Query(alias="receivedAtTo", description="受信日(To、当日23:59:59を含む)"),
        ] = None,
    ) -> None:
        self.subject = subject or None
        self.from_ = from_ or None
        self.received_at_from = received_at_from
        self.received_at_to = received_at_to

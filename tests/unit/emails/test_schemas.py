"""emails.schemas単体テスト"""

from datetime import UTC, datetime

from app.emails import schemas


class TestEmailListItem:
    """EmailListItemモデルのテスト"""

    def test_serializes_from_field_with_from_alias(self) -> None:
        """正常系: from_属性がJSONでは'from'キーとしてシリアライズされる"""
        item = schemas.EmailListItem(
            id="msg-1",
            subject="件名",
            from_="田中太郎 <tanaka@example.com>",
            received_at=datetime(2026, 3, 10, 1, 20, tzinfo=UTC),
        )

        dumped = item.model_dump(by_alias=True)

        assert dumped["from"] == "田中太郎 <tanaka@example.com>"
        assert "from_" not in dumped
        assert dumped["receivedAt"] == datetime(2026, 3, 10, 1, 20, tzinfo=UTC)

    def test_deserializes_from_camel_case_payload(self) -> None:
        """正常系: camelCase JSON('from'キー含む)からモデルを復元できる"""
        item = schemas.EmailListItem.model_validate(
            {
                "id": "msg-1",
                "subject": "件名",
                "from": "田中太郎 <tanaka@example.com>",
                "receivedAt": "2026-03-10T01:20:00Z",
            }
        )

        assert item.from_ == "田中太郎 <tanaka@example.com>"


class TestEmailDetailResponse:
    """EmailDetailResponseモデルのテスト"""

    def test_includes_body_field(self) -> None:
        """正常系: bodyフィールドを含むレスポンスを生成できる"""
        detail = schemas.EmailDetailResponse(
            id="msg-1",
            subject="件名",
            from_="田中太郎 <tanaka@example.com>",
            received_at=datetime(2026, 3, 10, 1, 20, tzinfo=UTC),
            body="本文\n改行あり",
        )

        dumped = detail.model_dump(by_alias=True)

        assert dumped["body"] == "本文\n改行あり"
        assert dumped["from"] == "田中太郎 <tanaka@example.com>"


class TestEmailFilterParams:
    """EmailFilterParamsのテスト"""

    def test_blank_strings_normalized_to_none(self) -> None:
        """正常系: 空文字のsubject/fromはNoneとして扱われる"""
        filters = schemas.EmailFilterParams(subject="", from_="")

        assert filters.subject is None
        assert filters.from_ is None

    def test_holds_provided_values(self) -> None:
        """正常系: 指定された値をそのまま保持する"""
        from datetime import date

        filters = schemas.EmailFilterParams(
            subject="見積書",
            from_="tanaka@example.com",
            received_at_from=date(2026, 3, 1),
            received_at_to=date(2026, 3, 31),
        )

        assert filters.subject == "見積書"
        assert filters.from_ == "tanaka@example.com"
        assert filters.received_at_from == date(2026, 3, 1)
        assert filters.received_at_to == date(2026, 3, 31)

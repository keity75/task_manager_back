"""EmailService単体テスト

Repository層・ProviderTokenServiceをモック化してEmailServiceのビジネスロジックをテストする。
"""

# ruff: noqa: PLR2004

from datetime import UTC, date, datetime
from unittest.mock import Mock

import pytest

from app.auth.provider_token_service import ProviderTokenService
from app.core.schemas import PaginationParams
from app.emails import schemas
from app.emails.exceptions import EmailNotFoundError
from app.emails.repository import GmailRepository
from app.emails.service import EmailService

ACCESS_TOKEN = "test-access-token"  # noqa: S105


def _metadata_response(
    message_id: str,
    subject: str = "Test Subject",
    from_: str = "田中太郎 <tanaka@example.com>",
    internal_date_ms: int = 1_700_000_000_000,
) -> dict:
    return {
        "id": message_id,
        "internalDate": str(internal_date_ms),
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": from_},
            ]
        },
    }


def _full_response(
    message_id: str,
    subject: str = "Test Subject",
    from_: str = "田中太郎 <tanaka@example.com>",
    body_text: str = "本文テキスト",
    internal_date_ms: int = 1_700_000_000_000,
) -> dict:
    import base64

    encoded = base64.urlsafe_b64encode(body_text.encode("utf-8")).decode("ascii")
    return {
        "id": message_id,
        "internalDate": str(internal_date_ms),
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": from_},
            ],
            "body": {"data": encoded},
        },
    }


@pytest.fixture
def mock_repo() -> Mock:
    """GmailRepositoryのモックを作成"""
    return Mock(spec=GmailRepository)


@pytest.fixture
def mock_provider_token_service() -> Mock:
    """ProviderTokenServiceのモックを作成"""
    mock = Mock(spec=ProviderTokenService)
    mock.get_valid_access_token.return_value = ACCESS_TOKEN
    return mock


@pytest.fixture
def email_service(mock_repo: Mock, mock_provider_token_service: Mock) -> EmailService:
    """EmailServiceインスタンスを作成"""
    return EmailService(
        gmail_repo=mock_repo,
        provider_token_service=mock_provider_token_service,
    )


class TestListEmails:
    """list_emailsメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_list_emails_basic(
        self, email_service: EmailService, mock_repo: Mock
    ) -> None:
        """正常系: フィルタなしの場合、全件のうちページ分のメタデータのみ取得する"""
        mock_repo.list_message_ids.return_value = ["msg-1", "msg-2", "msg-3"]
        mock_repo.get_message_metadata.side_effect = (
            lambda _access_token, message_id: _metadata_response(message_id)
        )

        filters = schemas.EmailFilterParams()
        pagination = PaginationParams(limit=2, offset=0)

        items, total_count = await email_service.list_emails(
            user_id="user-1", filters=filters, pagination=pagination
        )

        assert total_count == 3
        assert len(items) == 2
        assert [item.id for item in items] == ["msg-1", "msg-2"]
        assert mock_repo.get_message_metadata.call_count == 2

    @pytest.mark.asyncio
    async def test_list_emails_offset_beyond_total_returns_empty(
        self, email_service: EmailService, mock_repo: Mock
    ) -> None:
        """正常系: offsetが総件数を超える場合、空リストを返す(totalCountは維持)"""
        mock_repo.list_message_ids.return_value = ["msg-1"]

        filters = schemas.EmailFilterParams()
        pagination = PaginationParams(limit=10, offset=100)

        items, total_count = await email_service.list_emails(
            user_id="user-1", filters=filters, pagination=pagination
        )

        assert total_count == 1
        assert items == []
        mock_repo.get_message_metadata.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_emails_uses_valid_access_token(
        self,
        email_service: EmailService,
        mock_repo: Mock,
        mock_provider_token_service: Mock,
    ) -> None:
        """正常系: ProviderTokenServiceから取得したアクセストークンをRepositoryに渡す"""
        mock_repo.list_message_ids.return_value = []

        filters = schemas.EmailFilterParams()
        pagination = PaginationParams()

        await email_service.list_emails(
            user_id="user-1", filters=filters, pagination=pagination
        )

        mock_provider_token_service.get_valid_access_token.assert_called_once_with(
            "user-1", "google"
        )
        mock_repo.list_message_ids.assert_called_once()
        called_token = mock_repo.list_message_ids.call_args.args[0]
        assert called_token == ACCESS_TOKEN

    @pytest.mark.asyncio
    async def test_list_emails_builds_query_with_subject_and_from(
        self, email_service: EmailService, mock_repo: Mock
    ) -> None:
        """正常系: subject/fromフィルタがGmail検索クエリに変換される"""
        mock_repo.list_message_ids.return_value = []

        filters = schemas.EmailFilterParams(subject="見積書", from_="tanaka@example.com")
        pagination = PaginationParams()

        await email_service.list_emails(
            user_id="user-1", filters=filters, pagination=pagination
        )

        query = mock_repo.list_message_ids.call_args.args[1]
        assert 'subject:"見積書"' in query
        assert 'from:"tanaka@example.com"' in query

    @pytest.mark.asyncio
    async def test_list_emails_builds_query_with_date_range(
        self, email_service: EmailService, mock_repo: Mock
    ) -> None:
        """正常系: 受信日範囲フィルタがafter:/before:に変換される"""
        mock_repo.list_message_ids.return_value = []

        filters = schemas.EmailFilterParams(
            received_at_from=date(2026, 3, 1),
            received_at_to=date(2026, 3, 1),
        )
        pagination = PaginationParams()

        await email_service.list_emails(
            user_id="user-1", filters=filters, pagination=pagination
        )

        query = mock_repo.list_message_ids.call_args.args[1]
        assert "after:" in query
        assert "before:" in query

    @pytest.mark.asyncio
    async def test_list_emails_escapes_double_quotes_in_filters(
        self, email_service: EmailService, mock_repo: Mock
    ) -> None:
        """異常系: 件名/送信者に二重引用符が含まれてもクエリ構文を壊さない"""
        mock_repo.list_message_ids.return_value = []

        filters = schemas.EmailFilterParams(subject='"OR 1=1 subject:"')
        pagination = PaginationParams()

        await email_service.list_emails(
            user_id="user-1", filters=filters, pagination=pagination
        )

        query = mock_repo.list_message_ids.call_args.args[1]
        assert query.count('"') == 2


    @pytest.mark.asyncio
    async def test_list_emails_query_is_restricted_to_inbox(
        self, email_service: EmailService, mock_repo: Mock
    ) -> None:
        """正常系: フィルタの有無に関わらず常にin:inboxで受信箱のみに絞り込む

        送信済み/下書き/迷惑メール等まで対象にすると「受信メール一覧」の意味が崩れ、
        件数確定のための全件列挙(list_message_ids)も無用に肥大化するため。
        """
        mock_repo.list_message_ids.return_value = []

        await email_service.list_emails(
            user_id="user-1",
            filters=schemas.EmailFilterParams(),
            pagination=PaginationParams(),
        )

        query = mock_repo.list_message_ids.call_args.args[1]
        assert "in:inbox" in query.split(" ")


class TestGetEmail:
    """get_emailメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_get_email_success(
        self, email_service: EmailService, mock_repo: Mock
    ) -> None:
        """正常系: 本文を含む詳細情報を返す"""
        mock_repo.get_message_full.return_value = _full_response(
            "msg-1", body_text="こんにちは\n本文です"
        )

        result = await email_service.get_email(user_id="user-1", message_id="msg-1")

        assert isinstance(result, schemas.EmailDetailResponse)
        assert result.id == "msg-1"
        assert result.subject == "Test Subject"
        assert result.from_ == "田中太郎 <tanaka@example.com>"
        assert result.body == "こんにちは\n本文です"
        assert result.received_at == datetime.fromtimestamp(1_700_000_000, tz=UTC)

    @pytest.mark.asyncio
    async def test_get_email_not_found_propagates(
        self, email_service: EmailService, mock_repo: Mock
    ) -> None:
        """異常系: RepositoryがEmailNotFoundErrorを送出した場合、そのまま伝播する"""
        mock_repo.get_message_full.side_effect = EmailNotFoundError("Email not found")

        with pytest.raises(EmailNotFoundError):
            await email_service.get_email(user_id="user-1", message_id="missing")

    @pytest.mark.asyncio
    async def test_get_email_uses_valid_access_token(
        self,
        email_service: EmailService,
        mock_repo: Mock,
        mock_provider_token_service: Mock,
    ) -> None:
        """正常系: ProviderTokenServiceから取得したアクセストークンをRepositoryに渡す"""
        mock_repo.get_message_full.return_value = _full_response("msg-1")

        await email_service.get_email(user_id="user-1", message_id="msg-1")

        mock_provider_token_service.get_valid_access_token.assert_called_once_with(
            "user-1", "google"
        )
        mock_repo.get_message_full.assert_called_once_with(ACCESS_TOKEN, "msg-1")

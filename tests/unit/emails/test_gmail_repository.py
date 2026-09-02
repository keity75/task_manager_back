"""GmailHttpRepository単体テスト

HttpClientをモック化してGmail REST API呼び出しのリクエスト構築・
レスポンス処理・エラーハンドリングをテストする。
"""

# ruff: noqa: PLR2004

from unittest.mock import AsyncMock

import pytest

from app.clients.http import HttpClient, HttpNetworkError, HttpRequestError
from app.emails.constants import GMAIL_API_BASE_URL, GMAIL_LIST_MAX_RESULTS
from app.emails.exceptions import (
    EmailNotFoundError,
    GmailPermissionDeniedError,
    GmailRepositoryError,
)
from app.emails.gmail_repository import GmailHttpRepository

ACCESS_TOKEN = "test-access-token"  # noqa: S105


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """HttpClientのモックを作成"""
    return AsyncMock(spec=HttpClient)


@pytest.fixture
def repo(mock_http_client: AsyncMock) -> GmailHttpRepository:
    """GmailHttpRepositoryインスタンスを作成"""
    return GmailHttpRepository(http_client=mock_http_client)


class TestListMessageIds:
    """list_message_idsメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_single_page(
        self, repo: GmailHttpRepository, mock_http_client: AsyncMock
    ) -> None:
        """正常系: 1ページで全件取得できる場合、そのままIDリストを返す"""
        mock_http_client.get_json.return_value = {
            "messages": [{"id": "msg-1"}, {"id": "msg-2"}],
        }

        ids = await repo.list_message_ids(ACCESS_TOKEN, "subject:test")

        assert ids == ["msg-1", "msg-2"]
        mock_http_client.get_json.assert_called_once()
        call = mock_http_client.get_json.call_args
        assert call.args[0] == f"{GMAIL_API_BASE_URL}/messages"
        assert call.kwargs["params"]["q"] == "subject:test"
        assert call.kwargs["params"]["maxResults"] == GMAIL_LIST_MAX_RESULTS
        assert call.kwargs["headers"] == {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    @pytest.mark.asyncio
    async def test_no_query_omits_q_param(
        self, repo: GmailHttpRepository, mock_http_client: AsyncMock
    ) -> None:
        """正常系: クエリが空文字の場合、qパラメータを付与しない"""
        mock_http_client.get_json.return_value = {"messages": []}

        await repo.list_message_ids(ACCESS_TOKEN, "")

        call = mock_http_client.get_json.call_args
        assert "q" not in call.kwargs["params"]

    @pytest.mark.asyncio
    async def test_no_messages_returns_empty_list(
        self, repo: GmailHttpRepository, mock_http_client: AsyncMock
    ) -> None:
        """正常系: 該当メッセージがない場合、空リストを返す(messagesキー自体が欠落)"""
        mock_http_client.get_json.return_value = {"resultSizeEstimate": 0}

        ids = await repo.list_message_ids(ACCESS_TOKEN, "subject:none")

        assert ids == []

    @pytest.mark.asyncio
    async def test_follows_next_page_token(
        self, repo: GmailHttpRepository, mock_http_client: AsyncMock
    ) -> None:
        """正常系: nextPageTokenがある限りページをたどって全件を結合する"""
        mock_http_client.get_json.side_effect = [
            {"messages": [{"id": "msg-1"}], "nextPageToken": "token-2"},
            {"messages": [{"id": "msg-2"}], "nextPageToken": "token-3"},
            {"messages": [{"id": "msg-3"}]},
        ]

        ids = await repo.list_message_ids(ACCESS_TOKEN, "")

        assert ids == ["msg-1", "msg-2", "msg-3"]
        assert mock_http_client.get_json.call_count == 3
        second_call_params = mock_http_client.get_json.call_args_list[1].kwargs["params"]
        assert second_call_params["pageToken"] == "token-2"

    @pytest.mark.asyncio
    async def test_http_error_raises_gmail_repository_error(
        self, repo: GmailHttpRepository, mock_http_client: AsyncMock
    ) -> None:
        """異常系: HttpClientがエラーを送出した場合、GmailRepositoryErrorに変換する"""
        mock_http_client.get_json.side_effect = HttpNetworkError.from_request(
            f"{GMAIL_API_BASE_URL}/messages"
        )

        with pytest.raises(GmailRepositoryError):
            await repo.list_message_ids(ACCESS_TOKEN, "")

    @pytest.mark.asyncio
    async def test_forbidden_raises_gmail_permission_denied_error(
        self, repo: GmailHttpRepository, mock_http_client: AsyncMock
    ) -> None:
        """異常系: Gmail APIが403(権限不足)を返した場合、GmailPermissionDeniedErrorに変換する"""
        mock_http_client.get_json.side_effect = HttpRequestError.from_response(
            url=f"{GMAIL_API_BASE_URL}/messages",
            status_code=403,
            response_body="Request had insufficient authentication scopes.",
        )

        with pytest.raises(GmailPermissionDeniedError):
            await repo.list_message_ids(ACCESS_TOKEN, "")


class TestGetMessageMetadata:
    """get_message_metadataメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_success(
        self, repo: GmailHttpRepository, mock_http_client: AsyncMock
    ) -> None:
        """正常系: format=metadataでメッセージを取得する"""
        expected = {"id": "msg-1", "payload": {"headers": []}}
        mock_http_client.get_json.return_value = expected

        result = await repo.get_message_metadata(ACCESS_TOKEN, "msg-1")

        assert result == expected
        call = mock_http_client.get_json.call_args
        assert call.args[0] == f"{GMAIL_API_BASE_URL}/messages/msg-1"
        assert call.kwargs["params"]["format"] == "metadata"
        assert call.kwargs["params"]["metadataHeaders"] == ["Subject", "From"]

    @pytest.mark.asyncio
    async def test_not_found_raises_email_not_found_error(
        self, repo: GmailHttpRepository, mock_http_client: AsyncMock
    ) -> None:
        """異常系: Gmail APIが404を返した場合、EmailNotFoundErrorに変換する"""
        mock_http_client.get_json.side_effect = HttpRequestError.from_response(
            url=f"{GMAIL_API_BASE_URL}/messages/missing",
            status_code=404,
            response_body="not found",
        )

        with pytest.raises(EmailNotFoundError):
            await repo.get_message_metadata(ACCESS_TOKEN, "missing")

    @pytest.mark.asyncio
    async def test_forbidden_raises_gmail_permission_denied_error(
        self, repo: GmailHttpRepository, mock_http_client: AsyncMock
    ) -> None:
        """異常系: Gmail APIが403(権限不足)を返した場合、GmailPermissionDeniedErrorに変換する"""
        mock_http_client.get_json.side_effect = HttpRequestError.from_response(
            url=f"{GMAIL_API_BASE_URL}/messages/msg-1",
            status_code=403,
            response_body="Request had insufficient authentication scopes.",
        )

        with pytest.raises(GmailPermissionDeniedError):
            await repo.get_message_metadata(ACCESS_TOKEN, "msg-1")

    @pytest.mark.asyncio
    async def test_other_http_error_raises_gmail_repository_error(
        self, repo: GmailHttpRepository, mock_http_client: AsyncMock
    ) -> None:
        """異常系: 404以外のHTTPエラーはGmailRepositoryErrorに変換する"""
        mock_http_client.get_json.side_effect = HttpRequestError.from_response(
            url=f"{GMAIL_API_BASE_URL}/messages/msg-1",
            status_code=500,
            response_body="server error",
        )

        with pytest.raises(GmailRepositoryError):
            await repo.get_message_metadata(ACCESS_TOKEN, "msg-1")


class TestGetMessageFull:
    """get_message_fullメソッドのテスト"""

    @pytest.mark.asyncio
    async def test_success(
        self, repo: GmailHttpRepository, mock_http_client: AsyncMock
    ) -> None:
        """正常系: format=fullでメッセージを取得する(metadataHeadersは付与しない)"""
        expected = {"id": "msg-1", "payload": {}}
        mock_http_client.get_json.return_value = expected

        result = await repo.get_message_full(ACCESS_TOKEN, "msg-1")

        assert result == expected
        call = mock_http_client.get_json.call_args
        assert call.kwargs["params"]["format"] == "full"
        assert "metadataHeaders" not in call.kwargs["params"]

    @pytest.mark.asyncio
    async def test_not_found_raises_email_not_found_error(
        self, repo: GmailHttpRepository, mock_http_client: AsyncMock
    ) -> None:
        """異常系: Gmail APIが404を返した場合、EmailNotFoundErrorに変換する"""
        mock_http_client.get_json.side_effect = HttpRequestError.from_response(
            url=f"{GMAIL_API_BASE_URL}/messages/missing",
            status_code=404,
            response_body="not found",
        )

        with pytest.raises(EmailNotFoundError):
            await repo.get_message_full(ACCESS_TOKEN, "missing")

"""メールAPI(/api/v1/emails)の結合テスト

Gmail自体はテスト対象外の外部サービスのため、GmailRepository/ProviderTokenServiceを
Fakeに差し替え、ルーティング・バリデーション・フィルタ/ページネーション・
エラーレスポンス形状を検証する。

Fake実装(D102/ARG002)や意図的な例外送出(TRY003/EM101)はテストの見通しを優先し許容する。
"""

# ruff: noqa: PLR2004, D102, ARG002, TRY003, EM101

import base64
import re
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.auth.provider_token_service import ProviderTokenService
from app.core.dependencies import get_current_user_id
from app.core.schemas import ErrorResponse, SuccessResponse
from app.emails.dependencies import get_email_service
from app.emails.exceptions import (
    EmailNotFoundError,
    GmailPermissionDeniedError,
    GmailRepositoryError,
)
from app.emails.repository import GmailRepository
from app.emails.service import EmailService
from app.main import app
from tests.integration.conftest import API_V1_PREFIX

TEST_USER_ID = "email-test-user"
FAKE_ACCESS_TOKEN = "fake-access-token"  # noqa: S105


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def _epoch_ms(dt: datetime) -> str:
    return str(int(dt.timestamp() * 1000))


def _build_message(
    message_id: str,
    subject: str,
    from_: str,
    received_at: datetime,
    body_text: str = "本文テキスト",
) -> dict[str, Any]:
    return {
        "id": message_id,
        "internalDate": _epoch_ms(received_at),
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": from_},
            ],
            "body": {"data": _b64url(body_text)},
        },
    }


class FakeGmailRepository(GmailRepository):
    """テスト用のインメモリGmailRepository

    EmailServiceが組み立てるGmail検索クエリ(subject:/from:/after:/before:)を
    簡易的に解釈してフィルタリングする。実際のGmail検索アルゴリズムの再現ではなく、
    アプリケーション層(ルーティング・ページネーション・エラーハンドリング)の
    結合テストを目的とする。
    """

    def __init__(self, messages: dict[str, dict[str, Any]]) -> None:
        self._messages = messages
        self.raise_list_error = False
        self.raise_permission_error = False
        self.raise_get_error_for: set[str] = set()

    async def list_message_ids(self, access_token: str, query: str) -> list[str]:
        if self.raise_permission_error:
            raise GmailPermissionDeniedError("simulated permission denied")
        if self.raise_list_error:
            raise GmailRepositoryError("simulated failure")

        subject_match = re.search(r'subject:"([^"]*)"', query)
        from_match = re.search(r'from:"([^"]*)"', query)
        after_match = re.search(r"after:(-?\d+)", query)
        before_match = re.search(r"before:(-?\d+)", query)

        matched: list[str] = []
        for message_id, raw in self._messages.items():
            headers = {h["name"]: h["value"] for h in raw["payload"]["headers"]}
            if subject_match and subject_match.group(1).lower() not in headers.get(
                "Subject", ""
            ).lower():
                continue
            if from_match and from_match.group(1).lower() not in headers.get(
                "From", ""
            ).lower():
                continue

            internal_date_sec = int(raw["internalDate"]) / 1000
            if after_match and internal_date_sec <= int(after_match.group(1)):
                continue
            if before_match and internal_date_sec >= int(before_match.group(1)):
                continue

            matched.append(message_id)

        matched.sort(key=lambda mid: int(self._messages[mid]["internalDate"]), reverse=True)
        return matched

    async def get_message_metadata(
        self, access_token: str, message_id: str
    ) -> dict[str, Any]:
        return await self._get(message_id)

    async def get_message_full(self, access_token: str, message_id: str) -> dict[str, Any]:
        return await self._get(message_id)

    async def _get(self, message_id: str) -> dict[str, Any]:
        if message_id in self.raise_get_error_for:
            raise GmailRepositoryError("simulated failure")
        if message_id not in self._messages:
            raise EmailNotFoundError("Email not found")
        return self._messages[message_id]


@pytest.fixture
def fake_gmail_repo() -> FakeGmailRepository:
    """テスト用メールデータを持つFakeGmailRepositoryを提供する"""
    messages = {
        "msg-1": _build_message(
            "msg-1",
            subject="請求書のご案内",
            from_="田中太郎 <tanaka@example.com>",
            received_at=datetime(2026, 3, 10, 1, 20, tzinfo=UTC),
            body_text="請求書を送付いたします。",
        ),
        "msg-2": _build_message(
            "msg-2",
            subject="会議のリマインダー",
            from_="鈴木花子 <suzuki@example.com>",
            received_at=datetime(2026, 3, 9, 8, 0, tzinfo=UTC),
            body_text="明日の会議についてです。",
        ),
        "msg-3": _build_message(
            "msg-3",
            subject="見積書送付のお願い",
            from_="田中太郎 <tanaka@example.com>",
            received_at=datetime(2026, 3, 5, 12, 0, tzinfo=UTC),
            body_text="見積書をお願いします。",
        ),
    }
    return FakeGmailRepository(messages)


@pytest.fixture
def authenticated_client(
    client: TestClient,
    fake_gmail_repo: FakeGmailRepository,
) -> Generator[TestClient]:
    """認証済みTestClientを提供し、Gmail/ProviderToken層をFakeに差し替えるフィクスチャ"""

    def _get_test_user_id() -> str:
        return TEST_USER_ID

    fake_provider_token_service = Mock(spec=ProviderTokenService)
    fake_provider_token_service.get_valid_access_token.return_value = FAKE_ACCESS_TOKEN

    def _get_test_email_service() -> EmailService:
        return EmailService(
            gmail_repo=fake_gmail_repo,
            provider_token_service=fake_provider_token_service,
        )

    app.dependency_overrides[get_current_user_id] = _get_test_user_id
    app.dependency_overrides[get_email_service] = _get_test_email_service

    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
        app.dependency_overrides.pop(get_email_service, None)


# =============================================================================
# GET /emails (一覧)
# =============================================================================


class TestListEmails:
    """メール一覧取得APIの結合テスト"""

    def test_list_emails_default_order_is_received_at_desc(
        self, authenticated_client: TestClient
    ) -> None:
        """正常系: フィルタなしの場合、受信日時の降順で全件返す"""
        response = authenticated_client.get(f"{API_V1_PREFIX}/emails")

        assert response.status_code == status.HTTP_200_OK
        body: SuccessResponse[list[dict]] = SuccessResponse.model_validate(response.json())
        assert body.status == "success"
        data = body.data
        assert isinstance(data, list)
        assert [item["id"] for item in data] == ["msg-1", "msg-2", "msg-3"]
        assert body.pagination is not None
        assert body.pagination.total_count == 3
        assert body.pagination.limit == 20
        assert body.pagination.offset == 0

    def test_list_emails_response_item_shape(
        self, authenticated_client: TestClient
    ) -> None:
        """正常系: 一覧アイテムがid/subject/from/receivedAtを含む(bodyは含まない)"""
        response = authenticated_client.get(f"{API_V1_PREFIX}/emails")

        item = response.json()["data"][0]
        assert item["id"] == "msg-1"
        assert item["subject"] == "請求書のご案内"
        assert item["from"] == "田中太郎 <tanaka@example.com>"
        assert item["receivedAt"] == "2026-03-10T01:20:00Z"
        assert "body" not in item

    def test_list_emails_pagination(self, authenticated_client: TestClient) -> None:
        """正常系: limit/offsetでページングできる"""
        response = authenticated_client.get(
            f"{API_V1_PREFIX}/emails", params={"limit": 1, "offset": 1}
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [item["id"] for item in body["data"]] == ["msg-2"]
        assert body["pagination"] == {"totalCount": 3, "limit": 1, "offset": 1}

    def test_list_emails_filter_by_subject(self, authenticated_client: TestClient) -> None:
        """正常系: subjectフィルタで部分一致検索できる"""
        response = authenticated_client.get(
            f"{API_V1_PREFIX}/emails", params={"subject": "見積書"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()["data"]
        assert [item["id"] for item in data] == ["msg-3"]

    def test_list_emails_filter_by_from(self, authenticated_client: TestClient) -> None:
        """正常系: fromフィルタで送信者を絞り込める"""
        response = authenticated_client.get(
            f"{API_V1_PREFIX}/emails", params={"from": "tanaka@example.com"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()["data"]
        assert {item["id"] for item in data} == {"msg-1", "msg-3"}

    def test_list_emails_filter_by_received_at_range(
        self, authenticated_client: TestClient
    ) -> None:
        """正常系: receivedAtFrom/receivedAtToで受信日範囲を絞り込める"""
        response = authenticated_client.get(
            f"{API_V1_PREFIX}/emails",
            params={"receivedAtFrom": "2026-03-09", "receivedAtTo": "2026-03-09"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()["data"]
        assert [item["id"] for item in data] == ["msg-2"]

    def test_list_emails_combined_filters_no_match(
        self, authenticated_client: TestClient
    ) -> None:
        """正常系: 複数フィルタを組み合わせて0件になる場合、空配列とtotalCount=0を返す"""
        response = authenticated_client.get(
            f"{API_V1_PREFIX}/emails",
            params={"subject": "会議", "from": "tanaka@example.com"},
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["data"] == []
        assert body["pagination"]["totalCount"] == 0

    def test_list_emails_without_auth_header_returns_401(self, client: TestClient) -> None:
        """異常系: 認証トークンがない場合は401 Unauthorized"""
        response = client.get(f"{API_V1_PREFIX}/emails")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        error = ErrorResponse.model_validate(response.json())
        assert error.status == "error"

    def test_list_emails_gmail_error_returns_502(
        self,
        authenticated_client: TestClient,
        fake_gmail_repo: FakeGmailRepository,
    ) -> None:
        """異常系: Gmail API呼び出しが失敗した場合は502 GMAIL_API_ERROR"""
        fake_gmail_repo.raise_list_error = True

        response = authenticated_client.get(f"{API_V1_PREFIX}/emails")

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        error = ErrorResponse.model_validate(response.json())
        assert error.status == "error"
        assert error.error.code == "GMAIL_API_ERROR"

    def test_list_emails_permission_denied_returns_403(
        self,
        authenticated_client: TestClient,
        fake_gmail_repo: FakeGmailRepository,
    ) -> None:
        """異常系: Gmailの権限不足(スコープ未許可等)の場合は403 GMAIL_PERMISSION_DENIED"""
        fake_gmail_repo.raise_permission_error = True

        response = authenticated_client.get(f"{API_V1_PREFIX}/emails")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        error = ErrorResponse.model_validate(response.json())
        assert error.error.code == "GMAIL_PERMISSION_DENIED"

    def test_list_emails_invalid_limit_returns_422(
        self, authenticated_client: TestClient
    ) -> None:
        """異常系: limitが範囲外(101以上)の場合422"""
        response = authenticated_client.get(
            f"{API_V1_PREFIX}/emails", params={"limit": 101}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# =============================================================================
# GET /emails/{id} (詳細)
# =============================================================================


class TestGetEmail:
    """メール詳細取得APIの結合テスト"""

    def test_get_email_success(self, authenticated_client: TestClient) -> None:
        """正常系: 件名・送信者・受信日時・本文を含む詳細を返す"""
        response = authenticated_client.get(f"{API_V1_PREFIX}/emails/msg-1")

        assert response.status_code == status.HTTP_200_OK
        body: SuccessResponse[dict] = SuccessResponse.model_validate(response.json())
        data = body.data
        assert isinstance(data, dict)
        assert data["id"] == "msg-1"
        assert data["subject"] == "請求書のご案内"
        assert data["from"] == "田中太郎 <tanaka@example.com>"
        assert data["receivedAt"] == "2026-03-10T01:20:00Z"
        assert data["body"] == "請求書を送付いたします。"

    def test_get_email_not_found_returns_404(
        self, authenticated_client: TestClient
    ) -> None:
        """異常系: 存在しないメールIDは404 EMAIL_NOT_FOUND"""
        response = authenticated_client.get(f"{API_V1_PREFIX}/emails/does-not-exist")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        error = ErrorResponse.model_validate(response.json())
        assert error.error.code == "EMAIL_NOT_FOUND"

    def test_get_email_gmail_error_returns_502(
        self,
        authenticated_client: TestClient,
        fake_gmail_repo: FakeGmailRepository,
    ) -> None:
        """異常系: Gmail API呼び出しが失敗した場合は502 GMAIL_API_ERROR"""
        fake_gmail_repo.raise_get_error_for.add("msg-1")

        response = authenticated_client.get(f"{API_V1_PREFIX}/emails/msg-1")

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        error = ErrorResponse.model_validate(response.json())
        assert error.error.code == "GMAIL_API_ERROR"

    def test_get_email_without_auth_header_returns_401(self, client: TestClient) -> None:
        """異常系: 認証トークンがない場合は401 Unauthorized"""
        response = client.get(f"{API_V1_PREFIX}/emails/msg-1")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

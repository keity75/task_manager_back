from functools import cache
from typing import Annotated, Any

from fastapi import Depends

from app.clients.http import (
    HttpClient,
    HttpClientError,
    HttpRequestError,
    get_http_client,
)
from app.core.logging import get_logger
from app.emails.constants import (
    GMAIL_API_BASE_URL,
    GMAIL_LIST_MAX_PAGES,
    GMAIL_LIST_MAX_RESULTS,
    GMAIL_LIST_METADATA_HEADERS,
)
from app.emails.error_messages import EmailErrorMessages
from app.emails.exceptions import (
    EmailNotFoundError,
    GmailPermissionDeniedError,
    GmailRepositoryError,
)
from app.emails.repository import GmailRepository

log = get_logger(__name__)

HTTP_STATUS_FORBIDDEN = 403
HTTP_STATUS_NOT_FOUND = 404


class GmailHttpRepository(GmailRepository):
    """Gmail REST APIを直接呼び出すリポジトリ実装

    google-api-python-client(同期・ブロッキング)は使わず、プロジェクト標準の
    非同期HttpClientでGmail REST APIを呼び出す。
    """

    def __init__(self, http_client: HttpClient) -> None:
        self.http_client = http_client

    async def list_message_ids(self, access_token: str, query: str) -> list[str]:
        """検索クエリに合致するメッセージIDを、ページをたどって全件取得する

        Note:
            Gmail APIはoffset方式のページネーションを提供しないため、
            offset/limitによるページング・正確な総件数を実現するには
            該当する全メッセージIDを一度取得する必要がある。
            暴走防止のため GMAIL_LIST_MAX_PAGES で上限を設ける。

        """
        headers = self._auth_headers(access_token)
        ids: list[str] = []
        page_token: str | None = None

        try:
            for _ in range(GMAIL_LIST_MAX_PAGES):
                params: dict[str, Any] = {"maxResults": GMAIL_LIST_MAX_RESULTS}
                if query:
                    params["q"] = query
                if page_token:
                    params["pageToken"] = page_token

                data = await self.http_client.get_json(
                    f"{GMAIL_API_BASE_URL}/messages",
                    params=params,
                    headers=headers,
                )
                ids.extend(message["id"] for message in data.get("messages") or [])

                page_token = data.get("nextPageToken")
                if not page_token:
                    break
        except HttpRequestError as err:
            if err.status_code == HTTP_STATUS_FORBIDDEN:
                log.warning(
                    "Gmail API denied permission while listing messages.",
                    status_code=err.status_code,
                    response_body=err.response_body,
                )
                raise GmailPermissionDeniedError(
                    EmailErrorMessages.GMAIL_PERMISSION_DENIED
                ) from err
            log.warning(
                "Failed to list messages from Gmail API.",
                status_code=err.status_code,
                response_body=err.response_body,
            )
            raise GmailRepositoryError(EmailErrorMessages.FAILED_TO_LIST_EMAILS) from err
        except HttpClientError as err:
            log.warning(
                "Failed to list messages from Gmail API.",
                error_type=type(err).__name__,
                original_error=str(err),
            )
            raise GmailRepositoryError(EmailErrorMessages.FAILED_TO_LIST_EMAILS) from err

        return ids

    async def get_message_metadata(
        self, access_token: str, message_id: str
    ) -> dict[str, Any]:
        """メッセージのメタデータ(件名/送信者/受信日時に必要な範囲)を取得する"""
        return await self._get_message(
            access_token,
            message_id,
            fmt="metadata",
            metadata_headers=GMAIL_LIST_METADATA_HEADERS,
        )

    async def get_message_full(
        self, access_token: str, message_id: str
    ) -> dict[str, Any]:
        """メッセージの全内容(本文を含む)を取得する"""
        return await self._get_message(access_token, message_id, fmt="full")

    async def _get_message(
        self,
        access_token: str,
        message_id: str,
        *,
        fmt: str,
        metadata_headers: list[str] | None = None,
    ) -> dict[str, Any]:
        headers = self._auth_headers(access_token)
        params: dict[str, Any] = {"format": fmt}
        if metadata_headers:
            params["metadataHeaders"] = metadata_headers

        try:
            return await self.http_client.get_json(
                f"{GMAIL_API_BASE_URL}/messages/{message_id}",
                params=params,
                headers=headers,
            )
        except HttpRequestError as err:
            if err.status_code == HTTP_STATUS_NOT_FOUND:
                raise EmailNotFoundError(EmailErrorMessages.EMAIL_NOT_FOUND) from err
            if err.status_code == HTTP_STATUS_FORBIDDEN:
                log.warning(
                    "Gmail API denied permission while getting message.",
                    message_id=message_id,
                    status_code=err.status_code,
                    response_body=err.response_body,
                )
                raise GmailPermissionDeniedError(
                    EmailErrorMessages.GMAIL_PERMISSION_DENIED
                ) from err
            log.warning(
                "Failed to get message from Gmail API.",
                message_id=message_id,
                status_code=err.status_code,
                response_body=err.response_body,
            )
            raise GmailRepositoryError(EmailErrorMessages.FAILED_TO_GET_EMAIL) from err
        except HttpClientError as err:
            log.warning(
                "Failed to get message from Gmail API.",
                message_id=message_id,
                error_type=type(err).__name__,
                original_error=str(err),
            )
            raise GmailRepositoryError(EmailErrorMessages.FAILED_TO_GET_EMAIL) from err

    def _auth_headers(self, access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}


@cache
def get_gmail_repository(
    http_client: Annotated[HttpClient, Depends(get_http_client)],
) -> GmailRepository:
    """Dependency provider.

    この関数は FastAPI によって最初に呼び出された時に一度だけ実行されます。
    """
    return GmailHttpRepository(http_client=http_client)

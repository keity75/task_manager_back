from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class GmailRepository(Protocol):
    """Gmailデータアクセス層のインターフェース"""

    async def list_message_ids(self, access_token: str, query: str) -> list[str]:
        """検索クエリに合致するメッセージIDの一覧を取得する

        Gmail APIのページネーション(pageToken)をすべてたどって全件を返す。
        """
        ...

    async def get_message_metadata(
        self, access_token: str, message_id: str
    ) -> dict[str, Any]:
        """メッセージのメタデータ(件名/送信者/受信日時)を取得する

        存在しない場合はEmailNotFoundErrorを送出する。
        """
        ...

    async def get_message_full(
        self, access_token: str, message_id: str
    ) -> dict[str, Any]:
        """メッセージの全内容(本文を含む)を取得する

        存在しない場合はEmailNotFoundErrorを送出する。
        """
        ...

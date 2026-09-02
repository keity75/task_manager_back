import asyncio
from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from app.auth.provider_token_service import ProviderTokenService
from app.core.logging import get_logger
from app.core.schemas import PaginationParams
from app.core.settings import settings
from app.emails import schemas
from app.emails.constants import GMAIL_PROVIDER
from app.emails.mime_utils import extract_plain_text_body
from app.emails.repository import GmailRepository

DEFAULT_TZ = ZoneInfo(settings.DEFAULT_TIMEZONE)
log = get_logger(__name__)


class EmailService:
    """メール関連のビジネスロジックを担当するサービスクラス"""

    def __init__(
        self,
        gmail_repo: GmailRepository,
        provider_token_service: ProviderTokenService,
    ) -> None:
        """依存性を注入 (DI)。

        - gmail_repo: データアクセス層 (Repository)
        - provider_token_service: Googleプロバイダートークンの取得・自動更新
        """
        self.repo = gmail_repo
        self.provider_token_service = provider_token_service

    async def list_emails(
        self,
        user_id: str,
        filters: schemas.EmailFilterParams,
        pagination: PaginationParams,
    ) -> tuple[list[schemas.EmailListItem], int]:
        """フィルター・ページネーション適用済みのメール一覧とその総件数を取得する

        Gmail APIはoffsetページネーションを提供しないため、条件に合致する
        メッセージID全件を取得して件数・ページを確定し、該当ページ分のみ
        メタデータを並列取得する。
        """
        access_token = await self.provider_token_service.get_valid_access_token(
            user_id, GMAIL_PROVIDER
        )
        query = self._build_query(filters)

        all_ids = await self.repo.list_message_ids(access_token, query)
        total_count = len(all_ids)

        page_ids = all_ids[pagination.offset : pagination.offset + pagination.limit]

        metadatas = await asyncio.gather(
            *(self.repo.get_message_metadata(access_token, mid) for mid in page_ids)
        )

        items = [self._to_list_item(raw) for raw in metadatas]
        return items, total_count

    async def get_email(self, user_id: str, message_id: str) -> schemas.EmailDetailResponse:
        """メール詳細(本文含む)を1件取得する

        存在しない、または他ユーザーのメールの場合はEmailNotFoundErrorを送出する。
        """
        access_token = await self.provider_token_service.get_valid_access_token(
            user_id, GMAIL_PROVIDER
        )
        raw = await self.repo.get_message_full(access_token, message_id)
        return self._to_detail(raw)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _build_query(self, filters: schemas.EmailFilterParams) -> str:
        """フィルター条件からGmail検索クエリ(qパラメータ)を構築する

        Note:
            Gmailのsubject:/from:検索は単語単位のトークン一致であり、
            SQLのLIKE '%...%'のような厳密な任意位置の部分一致とは完全には一致しない。
            件名・送信者に含まれる可能性のある二重引用符はクエリ構文を壊さないよう除去する。

            クエリなしのmessages.listは送信済み・下書き・迷惑メール・ゴミ箱まで含む
            全メールが対象になるため、「受信メール一覧」としての意味を保つことと、
            件数確定のための全件ID列挙(list_message_ids)の対象を絞り込むことを兼ねて
            常にin:inboxで受信箱のみに限定する。

        """
        parts: list[str] = ["in:inbox"]

        if filters.subject:
            parts.append(f'subject:"{self._escape_query_value(filters.subject)}"')

        if filters.from_:
            parts.append(f'from:"{self._escape_query_value(filters.from_)}"')

        received_at_from_utc, received_at_to_utc = self._resolve_received_at_range_utc(
            filters
        )
        if received_at_from_utc:
            # after:はGmail側の境界判定が厳密には未公開のため、1秒手前を指定して
            # 指定日00:00(UTC変換後)を確実に含める
            parts.append(f"after:{int(received_at_from_utc.timestamp()) - 1}")
        if received_at_to_utc:
            # before:も同様に、1秒後ろにずらして指定日23:59:59を確実に含める
            parts.append(f"before:{int(received_at_to_utc.timestamp()) + 1}")

        return " ".join(parts)

    def _escape_query_value(self, value: str) -> str:
        """Gmail検索クエリに埋め込む値から二重引用符を除去する"""
        return value.replace('"', "")

    def _resolve_received_at_range_utc(
        self, filters: schemas.EmailFilterParams
    ) -> tuple[datetime | None, datetime | None]:
        """フィルターの受信日(日付)条件をUTCの範囲(from/to)に変換する

        received_at_fromは指定日のJST 00:00:00、received_at_toは指定日のJST
        23:59:59.999999をそれぞれUTCに変換して返す。
        """
        received_at_from_utc: datetime | None = None
        if filters.received_at_from:
            dt = datetime.combine(filters.received_at_from, time.min).replace(
                tzinfo=DEFAULT_TZ
            )
            received_at_from_utc = dt.astimezone(UTC)

        received_at_to_utc: datetime | None = None
        if filters.received_at_to:
            dt = datetime.combine(filters.received_at_to, time.max).replace(
                tzinfo=DEFAULT_TZ
            )
            received_at_to_utc = dt.astimezone(UTC)

        return received_at_from_utc, received_at_to_utc

    def _to_list_item(self, raw: dict[str, Any]) -> schemas.EmailListItem:
        """Gmail APIの生データ(メタデータ)をレスポンスモデルに変換する"""
        headers = self._headers_dict(raw)
        return schemas.EmailListItem(
            id=raw["id"],
            subject=headers.get("Subject", ""),
            from_=headers.get("From", ""),
            received_at=self._parse_internal_date(raw.get("internalDate")),
        )

    def _to_detail(self, raw: dict[str, Any]) -> schemas.EmailDetailResponse:
        """Gmail APIの生データ(全内容)をレスポンスモデルに変換する"""
        headers = self._headers_dict(raw)
        body = extract_plain_text_body(raw.get("payload") or {})
        return schemas.EmailDetailResponse(
            id=raw["id"],
            subject=headers.get("Subject", ""),
            from_=headers.get("From", ""),
            received_at=self._parse_internal_date(raw.get("internalDate")),
            body=body,
        )

    def _headers_dict(self, raw: dict[str, Any]) -> dict[str, str]:
        """Gmail APIのpayload.headers配列を name -> value の辞書に変換する"""
        headers = (raw.get("payload") or {}).get("headers") or []
        return {h["name"]: h["value"] for h in headers if "name" in h and "value" in h}

    def _parse_internal_date(self, internal_date: str | None) -> datetime:
        """Gmail APIのinternalDate(エポックミリ秒の文字列)をUTC datetimeに変換する"""
        if not internal_date:
            return datetime.now(UTC)
        return datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC)

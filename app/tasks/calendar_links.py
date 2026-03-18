from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable
from urllib.parse import urlencode

from app.core.settings import settings
from app.tasks import schemas


@runtime_checkable
class CalendarLinkGenerator(Protocol):
    """カレンダーリンク生成のためのインターフェース (プロトコル)"""

    def generate(self, task: schemas.Task) -> str:
        """タスク情報からカレンダー登録用リンクを生成する"""
        ...


class GoogleCalendarLinkGenerator(CalendarLinkGenerator):
    """Googleカレンダー用のリンクジェネレータ"""

    def __init__(self, base_url: str = settings.GOOGLE_CALENDAR_BASE_URL) -> None:
        self.base_url = base_url

    def generate(self, task: schemas.Task) -> str:
        """タスク情報からGoogleカレンダー登録用リンクを生成する"""
        # 開始時刻を決定
        # due_atが存在する場合はその日時、nullの場合は現在時刻(UTC)を使用
        start_utc_dt = task.due_at or datetime.now(UTC)

        # 終了時刻は開始時刻から1時間後 (timedeltaを使い、日付またぎのバグを回避)
        end_utc_dt = start_utc_dt + timedelta(hours=1)

        # Googleカレンダーの日時フォーマットに変換 (YYYYMMDDTHHMMSSZ)
        date_format = "%Y%m%dT%H%M%SZ"
        start_str = start_utc_dt.strftime(date_format)
        end_str = end_utc_dt.strftime(date_format)
        dates = f"{start_str}/{end_str}"

        # URLパラメータを構築
        params = {"text": task.title, "dates": dates, "details": task.description or ""}

        param_string = urlencode(params)

        return f"{self.base_url}&{param_string}"


# --- DI (依存性注入) ---

# DI用のシングルトンインスタンス
_google_calendar_generator = GoogleCalendarLinkGenerator()


def get_calendar_link_generator() -> CalendarLinkGenerator:
    """DI用のProvider関数。"""
    # 今はGoogle固定で返す
    return _google_calendar_generator

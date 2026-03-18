from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.core.messages import t
from app.core.settings import settings


def _raise_value_error(message: str) -> None:
    """ValueErrorを生成して送出する小さなユーティリティ。"""
    err = ValueError(message)
    raise err


def validate_required(value: object, *, field_name: str) -> None:
    """必須チェック: Noneや空文字("")を不許可とする。"""
    if value is None or (isinstance(value, str) and value == ""):
        message = t("errors.REQUIRED", params={"field": field_name})
        raise ValueError(message)


def validate_max_length(value: str | None, *, max_len: int, field_name: str) -> None:
    """最大文字数チェック: Noneはスキップ、超過時にエラーメッセージを投げる。"""
    if value is None:
        return
    if len(value) > max_len:
        message = t(
            "errors.MAX_LENGTH_EXCEEDED",
            params={"field": field_name, "max": max_len},
        )
        raise ValueError(message)


def validate_iso8601_utc(value: str | datetime, *, field_name: str) -> datetime:
    """ISO 8601のUTC日時(Z表記対応)を検証し、UTCのaware datetimeに正規化して返す。

    引数は文字列またはdatetimeを受け付ける。無効な場合は人間可読なメッセージでValueErrorを送出する。
    """
    if isinstance(value, datetime):
        # すでにdatetime型の場合はUTCへ正規化
        return value.astimezone(UTC)

    try:
        # Pythonのfromisoformatは末尾Zを受け付けないため、Zは+00:00に置換してからパース
        iso_str = value.replace("Z", "+00:00") if value.endswith("Z") else value
        dt = datetime.fromisoformat(iso_str)
        # タイムゾーン未設定(naive)は不正
        if dt.tzinfo is None:
            _raise_value_error("naive datetime")
        return dt.astimezone(UTC)
    except Exception as err:
        message = t("errors.INVALID_DATETIME_UTC", params={"field": field_name})
        raise ValueError(message) from err


def validate_datetime_with_default_tz(
    value: str | datetime,
    *,
    field_name: str,
    default_tz: ZoneInfo | None = None,
) -> datetime:
    """任意のタイムゾーンのdatetimeを受け入れ、UTCに正規化する。

    Args:
        value: ISO 8601文字列またはdatetimeオブジェクト
        field_name: エラーメッセージ用のフィールド名
        default_tz: naive datetimeに適用するデフォルトタイムゾーン(デフォルト: JST)

    Returns:
        UTCに正規化されたaware datetimeオブジェクト

    Raises:
        ValueError: 無効な日時形式の場合

    """
    if default_tz is None:
        default_tz = ZoneInfo(settings.DEFAULT_TIMEZONE)

    if isinstance(value, datetime):
        # すでにdatetime型の場合
        if value.tzinfo is None:
            # naive datetimeの場合はdefault_tzを適用してUTCに変換
            value = value.replace(tzinfo=default_tz)
        return value.astimezone(UTC)

    try:
        # Pythonのfromisoformatは末尾Zを受け付けないため、Zは+00:00に置換してからパース
        iso_str = value.replace("Z", "+00:00") if value.endswith("Z") else value
        dt = datetime.fromisoformat(iso_str)

        if dt.tzinfo is None:
            # naive datetimeの場合はdefault_tzを適用
            dt = dt.replace(tzinfo=default_tz)

        return dt.astimezone(UTC)
    except Exception as err:
        message = t("errors.INVALID_DATETIME_UTC", params={"field": field_name})
        raise ValueError(message) from err


def validate_in_choices(
    value: int | None,
    *,
    choices: set[int],
    field_name: str,
    allow_none: bool = False,
) -> None:
    """数値が許容された選択肢に含まれるか検証する。"""
    if value is None:
        if allow_none:
            return
        message = t("errors.REQUIRED", params={"field": field_name})
        raise ValueError(message)

    if value not in choices:
        sorted_choices = sorted(choices)
        message = t(
            "errors.INVALID_CHOICE",
            params={"field": field_name, "choices": sorted_choices},
        )
        raise ValueError(message)

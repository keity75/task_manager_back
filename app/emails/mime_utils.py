"""Gmail APIのメッセージペイロード(MIME構造)から本文を抽出するユーティリティ"""

import base64
import html
import re
from typing import Any

_SCRIPT_OR_STYLE_RE = re.compile(
    r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE
)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BLOCK_END_RE = re.compile(r"</(p|div|tr|li)>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def extract_plain_text_body(payload: dict[str, Any]) -> str:
    """MIMEペイロードからプレーンテキスト本文を抽出する

    text/plainパートを優先し、存在しない場合はtext/htmlパートのタグを除去して返す。
    どちらも存在しない場合は空文字を返す。
    """
    plain = _find_body_by_mime_type(payload, "text/plain")
    if plain is not None:
        return plain

    raw_html = _find_body_by_mime_type(payload, "text/html")
    if raw_html is not None:
        return _strip_html_tags(raw_html)

    return ""


def _find_body_by_mime_type(payload: dict[str, Any], mime_type: str) -> str | None:
    """指定したMIMEタイプのパートを再帰的に探索し、デコード済み本文を返す"""
    if payload.get("mimeType") == mime_type:
        data = payload.get("body", {}).get("data")
        if data:
            return _decode_base64url(data)

    for part in payload.get("parts") or []:
        found = _find_body_by_mime_type(part, mime_type)
        if found is not None:
            return found

    return None


def _decode_base64url(data: str) -> str:
    """Gmail APIのbase64url(パディング省略)エンコード文字列をデコードする"""
    padded = data + "=" * (-len(data) % 4)
    decoded_bytes = base64.urlsafe_b64decode(padded)
    return decoded_bytes.decode("utf-8", errors="replace")


def _strip_html_tags(raw_html: str) -> str:
    """HTML本文からプレーンテキストを抽出する簡易コンバータ"""
    text = _SCRIPT_OR_STYLE_RE.sub("", raw_html)
    text = _BR_RE.sub("\n", text)
    text = _BLOCK_END_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    return text.strip()

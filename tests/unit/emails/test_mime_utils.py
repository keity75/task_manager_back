"""mime_utils単体テスト"""

import base64

from app.emails.mime_utils import extract_plain_text_body


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


class TestExtractPlainTextBody:
    """extract_plain_text_body関数のテスト"""

    def test_single_text_plain_part(self) -> None:
        """正常系: mimeTypeがtext/plainの単一パートから本文を抽出する"""
        payload = {
            "mimeType": "text/plain",
            "body": {"data": _b64url("こんにちは\n本文です")},
        }

        assert extract_plain_text_body(payload) == "こんにちは\n本文です"

    def test_multipart_prefers_text_plain(self) -> None:
        """正常系: multipart/alternativeの場合、text/plainパートを優先して抽出する"""
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": _b64url("<p>HTML本文</p>")},
                },
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64url("プレーンテキスト本文")},
                },
            ],
        }

        assert extract_plain_text_body(payload) == "プレーンテキスト本文"

    def test_nested_multipart(self) -> None:
        """正常系: ネストされたmultipart構造からもtext/plainを再帰的に探索する"""
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {"data": _b64url("ネストされた本文")},
                        },
                    ],
                },
                {
                    "mimeType": "application/pdf",
                    "body": {"data": _b64url("dummy-pdf-bytes")},
                },
            ],
        }

        assert extract_plain_text_body(payload) == "ネストされた本文"

    def test_falls_back_to_html_when_no_plain_text(self) -> None:
        """正常系: text/plainが存在しない場合、text/htmlのタグを除去して返す"""
        html_body = "<p>こんにちは</p><br><div>よろしくお願いします</div>"
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": _b64url(html_body)},
                },
            ],
        }

        result = extract_plain_text_body(payload)

        assert "<" not in result
        assert "こんにちは" in result
        assert "よろしくお願いします" in result

    def test_html_entities_are_unescaped(self) -> None:
        """正常系: HTML本文のエンティティ参照がデコードされる"""
        html_body = "<p>A &amp; B &lt;test&gt;</p>"
        payload = {"mimeType": "text/html", "body": {"data": _b64url(html_body)}}

        assert extract_plain_text_body(payload) == "A & B <test>"

    def test_script_and_style_tags_are_removed(self) -> None:
        """正常系: HTML本文のscript/styleタグは内容ごと除去される"""
        html_body = (
            "<style>.x{color:red}</style><script>alert(1)</script><p>本文</p>"
        )
        payload = {"mimeType": "text/html", "body": {"data": _b64url(html_body)}}

        result = extract_plain_text_body(payload)

        assert "alert" not in result
        assert "color:red" not in result
        assert "本文" in result

    def test_no_body_returns_empty_string(self) -> None:
        """正常系: text/plainもtext/htmlも存在しない場合、空文字を返す"""
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {"mimeType": "application/pdf", "body": {"data": _b64url("x")}},
            ],
        }

        assert extract_plain_text_body(payload) == ""

    def test_missing_body_data_returns_empty_string(self) -> None:
        """正常系: bodyにdataキーが存在しない(空メッセージ等)場合、空文字を返す"""
        payload = {"mimeType": "text/plain", "body": {}}

        assert extract_plain_text_body(payload) == ""

    def test_base64url_without_padding_is_decoded(self) -> None:
        """正常系: パディングが省略されたbase64url文字列も正しくデコードする"""
        text = "abc"  # base64urlエンコード時にパディングが必要になる長さ
        payload = {"mimeType": "text/plain", "body": {"data": _b64url(text)}}

        assert extract_plain_text_body(payload) == text

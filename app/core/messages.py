from __future__ import annotations

from typing import Any

# 階層構造のメッセージ辞書(カテゴリ別に整理)
# - errors: バリデーション/例外などのエラー文言
# - ui: 画面表示に使う一般文言(将来の多言語化を見据える)
# - labels: 汎用ラベル
MESSAGES: dict[str, dict[str, Any]] = {
    "ja": {
        "errors": {
            "VALIDATION_ERROR": "リクエストが不正です",
            "REQUIRED": "{field}: 必須です",
            "INVALID_DATETIME_UTC": "{field}: 不正な日時形式(ISO 8601 UTC想定)",
            "MAX_LENGTH_EXCEEDED": "{field}: 最大{max}文字まで",
            "INVALID_CHOICE": "{field}: {choices}のいずれかを指定してください",
        },
        "ui": {
            "tasks": {
                "createSuccess": "タスクを作成しました",
            }
        },
        "labels": {
            "ok": "OK",
            "cancel": "キャンセル",
        },
    },
}


def _get_by_path(dct: dict[str, Any], path: str) -> str | None:
    """ドット区切りのパスで辞書を辿り、文字列を取得する。見つからなければNone。"""
    cur: Any = dct
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:  # 型/キーの存在チェック
            return None
        cur = cur[part]
    return cur if isinstance(cur, str) else None


def t(key: str, *, locale: str = "ja", params: dict[str, Any] | None = None) -> str:
    """メッセージキー(カテゴリ対応)と言語に対応する文言を取得し、差し込みを行う。

    優先順:
    1) ドット区切り(例: "errors.REQUIRED")での厳密参照
    2) 見つからなければキー名をそのまま返す
    """
    bundle = MESSAGES.get(locale, {})

    # 1) ドット区切りでの探索
    text = _get_by_path(bundle, key) if "." in key else None

    # 2) フォールバック
    if text is None:
        text = key

    return text.format(**params) if params else text

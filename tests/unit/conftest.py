"""単体テスト共通ヘルパー関数

単体テストファイル間で共通して使用されるヘルパー関数を提供する。
"""

from datetime import UTC, datetime

from google.cloud import firestore

# =============================================================================
# ヘルパー関数
# =============================================================================


def _create_user(db: firestore.Client) -> str:
    """テスト用ユーザーを作成してuserIdを返す"""
    user_ref = db.collection("users").document()
    user_ref.set({"name": "Test User", "createdAt": datetime.now(UTC)})
    return user_ref.id

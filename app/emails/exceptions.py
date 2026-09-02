class GmailRepositoryError(Exception):
    """Gmail APIへのアクセスでエラーが発生した場合の例外"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"Gmail repository error: {message}")


class GmailPermissionDeniedError(Exception):
    """Gmail APIから権限不足(403)が返された場合の例外

    OAuth同意スコープにGmailの読み取り権限が含まれていない、または
    ユーザーが権限を取り消した場合に発生する。フロントエンドでの
    再認証誘導のため、他のGmail APIエラー(GmailRepositoryError)とは区別する。
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"Gmail permission denied: {message}")


class EmailNotFoundError(Exception):
    """指定されたメールが存在しない(所有者不一致を含む)場合の例外"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

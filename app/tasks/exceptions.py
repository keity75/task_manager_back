class TaskRepositoryError(Exception):
    """タスクリポジトリでエラーが発生した場合の例外"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"Task repository error: {message}")


class TaskNotFoundError(Exception):
    """指定されたタスクが存在しない(所有者不一致・削除済みを含む)場合の例外"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

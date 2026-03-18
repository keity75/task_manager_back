class TaskRepositoryError(Exception):
    """タスクリポジトリでエラーが発生した場合の例外"""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"Task repository error: {message}")

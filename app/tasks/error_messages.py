"""タスク機能のエラーメッセージ定数"""


class TaskErrorMessages:
    """タスクエラーメッセージ定数"""

    # ========== Validation Errors ==========
    USER_ID_REQUIRED = "userId is required"

    # ========== Not Found Errors ==========
    TASK_NOT_FOUND = "Task not found"

    # ========== Repository Errors ==========
    FAILED_TO_COUNT_TASKS = "Failed to count tasks"
    FAILED_TO_CREATE_TASK = "Failed to create task"
    FAILED_TO_LIST_TASKS = "Failed to list tasks"
    FAILED_TO_GET_TASK = "Failed to get task"
    FAILED_TO_UPDATE_TASK = "Failed to update task"
    FAILED_TO_DELETE_TASK = "Failed to delete task"

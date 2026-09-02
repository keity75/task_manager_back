"""メール機能のエラーメッセージ定数"""


class EmailErrorMessages:
    """メールエラーメッセージ定数"""

    # ========== Not Found Errors ==========
    EMAIL_NOT_FOUND = "Email not found"

    # ========== Gmail API Errors ==========
    FAILED_TO_LIST_EMAILS = "Failed to list emails from Gmail"
    FAILED_TO_GET_EMAIL = "Failed to get email from Gmail"
    GMAIL_PERMISSION_DENIED = (
        "Gmail access was denied. The user may need to reconnect their Google account"
        " with Gmail permission granted"
    )

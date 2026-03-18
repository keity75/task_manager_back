"""認証機能のエラーメッセージ定数"""


class AuthErrorMessages:
    """認証エラーメッセージ定数"""

    # ========== Validation Errors ==========
    PROVIDER_ACCOUNT_ID_REQUIRED = "providerAccountId is required"
    USER_ID_REQUIRED = "userId is required"
    PROVIDER_REQUIRED = "provider is required"
    REFRESH_TOKEN_HASH_REQUIRED = "refreshTokenHash is required"  # noqa: S105
    ENCRYPTED_ACCESS_TOKEN_REQUIRED = "encrypted_access_token is required"  # noqa: S105
    EXPIRES_AT_MUST_BE_UTC_DATETIME = (
        "expires_at must be a datetime object with UTC timezone"
    )

    # ========== Repository Errors ==========
    FAILED_TO_FIND_USER = "Failed to find user by provider ID"
    FAILED_TO_GET_USER_NAME = "Failed to get user name"
    FAILED_TO_CREATE_USER = "Failed to create user"
    FAILED_TO_UPDATE_TOKENS = "Failed to update tokens"
    FAILED_TO_GET_PROVIDER_TOKENS = "Failed to get provider tokens"
    FAILED_TO_UPDATE_PROVIDER_TOKENS = "Failed to update provider tokens"
    FAILED_TO_CREATE_BACKEND_SESSION = "Failed to create backend session"
    FAILED_TO_FIND_BACKEND_SESSION = "Failed to find backend session"
    FAILED_TO_REVOKE_BACKEND_SESSION = "Failed to revoke backend session"
    FAILED_TO_REVOKE_ALL_USER_SESSIONS = "Failed to revoke all user sessions"

    # ========== Token Update Errors ==========
    AUTH_PROVIDER_RECORD_NOT_FOUND = "Auth provider record not found for user"

    # ========== Provider Errors (Templates) ==========
    PROVIDER_NOT_FOUND_TEMPLATE = "Provider '{provider}' not found for user"

    # ========== Domain Restriction Errors ==========
    EMAIL_DOMAIN_NOT_ALLOWED = "This email domain is not allowed for login"

    # ========== Service Errors ==========
    AUTH_SYNC_FAILED = "Auth sync failed"
    INVALID_OR_EXPIRED_REFRESH_TOKEN = "Invalid or expired refresh token"  # noqa: S105
    REFRESH_TOKEN_REVOKED = "Refresh token has been revoked"  # noqa: S105
    REFRESH_TOKEN_EXPIRED = "Refresh token has expired"  # noqa: S105

    # ========== Provider Token Service Errors ==========
    ACCESS_TOKEN_NOT_FOUND_IN_RESPONSE = "access_token not found in refresh response"  # noqa: S105
    PROVIDER_TOKEN_REFRESH_FAILED = "Provider token refresh failed"  # noqa: S105
    UNKNOWN_PROVIDER_TEMPLATE = "Unknown provider: {provider}"

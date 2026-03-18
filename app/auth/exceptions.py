class AuthSyncError(Exception):
    """認証同期処理の汎用エラー"""


class TokenUpdateError(AuthSyncError):
    """トークン更新エラー"""


class AuthRepositoryError(AuthSyncError):
    """リポジトリエラー(作成/更新/検索の失敗)"""


class InvalidRefreshTokenError(AuthSyncError):
    """リフレッシュトークンが無効または期限切れ"""


class InvalidAccessTokenError(Exception):
    """アクセストークンが無効または期限切れ (AuthSyncErrorとは独立)"""


class ProviderNotFoundError(AuthSyncError):
    """プロバイダー情報が見つからないエラー"""


class TokenRefreshError(AuthSyncError):
    """プロバイダートークンのリフレッシュに失敗したエラー"""


class EmailDomainNotAllowedError(Exception):
    """許可されていないメールドメインによるログイン試行"""

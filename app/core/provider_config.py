"""プロバイダー設定管理モジュール

OAuth2プロバイダー(Google, Microsoft等)の設定を一元管理する。
トークンエンドポイントやスコープなどの設定を提供。
"""

from typing import TypedDict


class ProviderConfig(TypedDict):
    """プロバイダー設定の型定義"""

    token_endpoint: str  # OAuth2トークンエンドポイント(必須)


# プロバイダー別設定
PROVIDER_CONFIGS: dict[str, ProviderConfig] = {
    "google": {
        "token_endpoint": "https://oauth2.googleapis.com/token",
    },
}


def _get_provider_config_value(provider: str, key: str) -> str:
    """プロバイダー設定から値を取得(内部ヘルパー)

    Args:
        provider: プロバイダーID
        key: 設定キー

    Returns:
        設定値

    Raises:
        ValueError: プロバイダーが未知、またはキーが存在しない場合

    """
    config = PROVIDER_CONFIGS.get(provider)
    if not config:
        message = f"Unknown provider: {provider}"
        raise ValueError(message)

    value: str = config.get(key)  # type: ignore[assignment]
    if not value:
        message = f"Config key '{key}' not found for provider '{provider}'"
        raise ValueError(message)

    return value


def get_provider_token_endpoint(provider: str) -> str:
    """プロバイダーのトークンエンドポイントURLを取得

    Args:
        provider: プロバイダーID(例: "google")

    Returns:
        トークンエンドポイントURL

    Raises:
        ValueError: 未知のプロバイダー、またはエンドポイント未設定の場合

    Example:
        >>> endpoint = get_provider_token_endpoint("google")
        >>> # "https://oauth2.googleapis.com/token"

    """
    return _get_provider_config_value(provider, "token_endpoint")

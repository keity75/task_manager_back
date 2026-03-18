"""認証機能固有のバリデーション関数"""

from __future__ import annotations


def validate_email_domain(email: str, allowed_domains: list[str]) -> None:
    """メールアドレスのドメインが許可リストに含まれるか検証する。

    allowed_domainsが空の場合は全てのドメインを許可する。

    Args:
        email: 検証対象のメールアドレス(Pydantic EmailStrで検証済みを想定)
        allowed_domains: 許可するドメインのリスト(空の場合は制限なし)

    Raises:
        ValueError: ドメインが許可されていない場合

    """
    if not allowed_domains:
        return

    # emailはPydantic EmailStrで検証済みなので、@の存在は保証される
    domain = email.rsplit("@", 1)[1].lower()
    allowed_lower = [d.lower() for d in allowed_domains]
    if domain not in allowed_lower:
        msg = f"Email domain '{domain}' is not allowed"
        raise ValueError(msg)

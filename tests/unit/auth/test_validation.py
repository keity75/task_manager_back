"""validate_email_domain関数の単体テスト

ドメイン制限のバリデーションロジックをテストする。
テストでは汎用ドメイン(allowed.com等)を使用し、特定のビジネスドメインに結合しない。
"""

import pytest

from app.auth.validation import validate_email_domain


class TestValidateEmailDomain:
    """validate_email_domain関数のテスト"""

    # --- 正常系: ドメイン制限あり ---

    def test_allowed_domain_passes(self) -> None:
        """許可ドメインのメールアドレスはエラーなく通過する"""
        # Arrange
        email = "user@allowed.com"
        allowed_domains = ["allowed.com"]

        # Act
        result = validate_email_domain(email, allowed_domains)

        # Assert
        assert result is None

    def test_multiple_allowed_domains_passes(self) -> None:
        """複数の許可ドメインのいずれかに一致すれば通過する"""
        # Arrange
        email = "user@partner.com"
        allowed_domains = ["allowed.com", "partner.com"]

        # Act
        result = validate_email_domain(email, allowed_domains)

        # Assert
        assert result is None

    def test_case_insensitive_domain_passes(self) -> None:
        """ドメイン部分の大文字小文字を区別しない(RFC 5321準拠)"""
        # Arrange
        allowed_domains = ["allowed.com"]

        # Act & Assert
        result1 = validate_email_domain("user@ALLOWED.COM", allowed_domains)
        result2 = validate_email_domain("user@Allowed.Com", allowed_domains)

        # Assert
        assert result1 is None
        assert result2 is None

    # --- 異常系: ドメイン制限あり ---

    def test_disallowed_domain_raises_value_error(self) -> None:
        """許可されていないドメインはValueErrorを送出する"""
        with pytest.raises(ValueError, match="not allowed"):
            validate_email_domain("user@other.com", ["allowed.com"])

    def test_subdomain_not_matching_parent_raises_value_error(self) -> None:
        """サブドメインは許可ドメインと一致しない(完全一致)"""
        with pytest.raises(ValueError, match="not allowed"):
            validate_email_domain("user@sub.allowed.com", ["allowed.com"])

    # --- 正常系: ドメイン制限なし ---

    def test_empty_allowed_domains_allows_all(self) -> None:
        """許可ドメインリストが空の場合、全てのドメインを許可する"""
        # Arrange
        email = "user@any-domain.com"
        allowed_domains = []

        # Act
        result = validate_email_domain(email, allowed_domains)

        # Assert
        assert result is None

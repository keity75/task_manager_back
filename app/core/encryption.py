"""プロバイダートークンの暗号化・復号化モジュール

AES-256-GCMを使用してOAuth2プロバイダートークンを安全に暗号化・復号化する。

セキュリティ要件:
- アルゴリズム: AES-256-GCM (認証付き暗号化)
- 鍵長: 256ビット (32バイト)
- IV: ランダム生成 (16バイト)
- AuthTag: 改ざん検出 (16バイト)
"""

import os

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.core.logging import get_logger
from app.core.settings import settings

log = get_logger(__name__)

# ENCRYPTION_KEYは64文字のhex文字列(32バイト)
ENCRYPTION_KEY_BYTES = bytes.fromhex(settings.ENCRYPTION_KEY)

# 追加認証データ(AAD) - フロントエンドと同じ値を使用
AAD = b"auth-token"

# 暗号化フォーマット定数
EXPECTED_CIPHERTEXT_PARTS = 3  # IV:AuthTag:Ciphertext


def encrypt(plaintext: str) -> str:
    """プロバイダートークンを暗号化する

    Args:
        plaintext: 暗号化する平文(プロバイダートークン)

    Returns:
        暗号化された文字列(形式: "IV:AuthTag:暗号文" のhex表現)

    Raises:
        ValueError: 暗号化に失敗した場合

    Example:
        >>> token = "ya29.a0AfH6SMB..."
        >>> encrypted = encrypt(token)
        >>> # encrypted: "1a2b3c4d...:9f8e7d6c...:5a4b3c2d..."

    """
    try:
        # ランダムIV生成(16バイト)
        iv = os.urandom(16)

        # AES-256-GCM Cipherオブジェクト作成
        cipher = Cipher(
            algorithms.AES(ENCRYPTION_KEY_BYTES),
            modes.GCM(iv),
            backend=default_backend(),
        )
        encryptor = cipher.encryptor()

        # 追加認証データ(AAD)を設定
        encryptor.authenticate_additional_data(AAD)

        # 暗号化実行
        ciphertext = encryptor.update(plaintext.encode("utf-8")) + encryptor.finalize()

        # AuthTag取得(改ざん検出用)
        auth_tag = encryptor.tag

        # IV + AuthTag + 暗号文 をコロン区切りで返す(全てhex)
        return f"{iv.hex()}:{auth_tag.hex()}:{ciphertext.hex()}"

    except Exception as err:
        log.exception(
            "Token encryption failed.",
            error_type=type(err).__name__,
            original_error=str(err),
        )
        message = "Failed to encrypt token"
        raise ValueError(message) from err


def decrypt(ciphertext: str) -> str:
    """暗号化されたプロバイダートークンを復号化する

    Args:
        ciphertext: 暗号化された文字列("IV:AuthTag:暗号文" 形式)

    Returns:
        復号化された平文(プロバイダートークン)

    Raises:
        ValueError: 復号化に失敗した場合、または改ざんが検出された場合

    Example:
        >>> encrypted = "1a2b3c4d...:9f8e7d6c...:5a4b3c2d..."
        >>> token = decrypt(encrypted)
        >>> # token: "ya29.a0AfH6SMB..."

    """
    try:
        # IV、AuthTag、暗号文を分離
        parts = ciphertext.split(":")
        if len(parts) != EXPECTED_CIPHERTEXT_PARTS:
            message = "Invalid ciphertext format (expected IV:AuthTag:Ciphertext)"
            raise ValueError(message)

        iv_hex, auth_tag_hex, ciphertext_hex = parts
        iv = bytes.fromhex(iv_hex)
        auth_tag = bytes.fromhex(auth_tag_hex)
        encrypted_data = bytes.fromhex(ciphertext_hex)

        # AES-256-GCM Cipherオブジェクト作成
        cipher = Cipher(
            algorithms.AES(ENCRYPTION_KEY_BYTES),
            modes.GCM(iv, auth_tag),
            backend=default_backend(),
        )
        decryptor = cipher.decryptor()

        # 追加認証データ(AAD)を設定
        decryptor.authenticate_additional_data(AAD)

        # 復号化実行(AuthTagによる改ざん検証も自動実行)
        plaintext_bytes = decryptor.update(encrypted_data) + decryptor.finalize()

        return plaintext_bytes.decode("utf-8")

    except Exception as err:
        log.exception(
            "Token decryption failed.",
            error_type=type(err).__name__,
            original_error=str(err),
        )
        message = "Failed to decrypt token"
        raise ValueError(message) from err

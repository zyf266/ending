"""`.env` 内敏感字段加密/解密（Fernet + 口令派生密钥）。"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

_KDF_SALT = b"backpack_quant_trading.env.v1"
_KDF_ITERATIONS = 480_000
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_ENV_SECRETS_PATH = _PACKAGE_ROOT / ".env.secrets"


def _derive_fernet(passphrase: str) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KDF_SALT,
        iterations=_KDF_ITERATIONS,
    )
    key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))
    return Fernet(key)


def encrypt_secret(plaintext: str, passphrase: str) -> str:
    if not plaintext or not passphrase:
        raise ValueError("plaintext 与 passphrase 均不能为空")
    return _derive_fernet(passphrase).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str, passphrase: str) -> str:
    if not ciphertext or not passphrase:
        raise ValueError("ciphertext 与 passphrase 均不能为空")
    try:
        return _derive_fernet(passphrase).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("解密失败：口令错误或密文已损坏") from exc


def _load_env_secrets_file() -> None:
    if not _ENV_SECRETS_PATH.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(_ENV_SECRETS_PATH, override=False)


def resolve_encrypted_env_vars() -> None:
    """将 DEEPSEEK_API_KEY_ENC 解密为 DEEPSEEK_API_KEY（进程环境变量）。"""
    if os.getenv("DEEPSEEK_API_KEY", "").strip():
        return

    enc = os.getenv("DEEPSEEK_API_KEY_ENC", "").strip()
    if not enc:
        return

    _load_env_secrets_file()
    passphrase = os.getenv("ENV_SECRETS_PASSPHRASE", "").strip()
    if not passphrase:
        logger.warning(
            "已配置 DEEPSEEK_API_KEY_ENC 但未设置 ENV_SECRETS_PASSPHRASE（见 .env.secrets）"
        )
        return

    try:
        os.environ["DEEPSEEK_API_KEY"] = decrypt_secret(enc, passphrase)
    except ValueError as exc:
        logger.error("DeepSeek API Key 解密失败: %s", exc)

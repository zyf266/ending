#!/usr/bin/env python3
"""加密/解密 .env 中的敏感字段（如 DEEPSEEK_API_KEY）。"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

from backpack_quant_trading.utils.env_secrets import decrypt_secret, encrypt_secret  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="加密/解密环境变量密文")
    sub = parser.add_subparsers(dest="cmd", required=True)

    enc_p = sub.add_parser("encrypt", help="生成 DEEPSEEK_API_KEY_ENC")
    enc_p.add_argument("--value", help="明文（不传则交互输入）")
    enc_p.add_argument("--passphrase", help="加密口令（不传则交互输入）")

    dec_p = sub.add_parser("decrypt", help="验证密文能否解密")
    dec_p.add_argument("--ciphertext", required=True)
    dec_p.add_argument("--passphrase", help="解密口令（不传则交互输入）")

    args = parser.parse_args()

    if args.cmd == "encrypt":
        value = args.value or getpass.getpass("明文: ")
        phrase = args.passphrase or getpass.getpass("加密口令: ")
        print(encrypt_secret(value.strip(), phrase.strip()))
        return 0

    phrase = args.passphrase or getpass.getpass("解密口令: ")
    plain = decrypt_secret(args.ciphertext.strip(), phrase.strip())
    print(f"OK (长度 {len(plain)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

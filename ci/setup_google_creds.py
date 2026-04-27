"""
GitHub Actions 用 Google認証ファイル構築スクリプト

ローカルで動作中の credentials.json / token.pickle を
base64エンコードしてGitHub Secretsに登録しておく方式。
morning_briefing.py 実行前に本スクリプトを実行すること。

必要な GitHub Secrets:
  GOOGLE_CREDENTIALS_B64  - credentials.json の base64エンコード値
  GOOGLE_TOKEN_PICKLE_B64 - token.pickle の base64エンコード値 (g.kamifor)

ローカルでの値取得コマンド:
  base64 -i ~/.config/ai-secretary/credentials.json | tr -d '\\n'
  base64 -i ~/.config/ai-secretary/token.pickle     | tr -d '\\n'
"""

import base64
import os
import sys
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "ai-secretary"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# 必須環境変数チェック
required = [
    "GOOGLE_CREDENTIALS_B64",
    "GOOGLE_TOKEN_PICKLE_B64",
]
missing = [k for k in required if not os.environ.get(k)]
if missing:
    print(f"[ERROR] 以下の GitHub Secrets が未登録です: {missing}", file=sys.stderr)
    print("", file=sys.stderr)
    print("ローカルで以下のコマンドを実行し、出力値をGitHub Secretsに登録してください:", file=sys.stderr)
    print("  base64 -i ~/.config/ai-secretary/credentials.json   | tr -d '\\n'  → GOOGLE_CREDENTIALS_B64", file=sys.stderr)
    print("  base64 -i ~/.config/ai-secretary/token.pickle        | tr -d '\\n'  → GOOGLE_TOKEN_PICKLE_B64", file=sys.stderr)
    sys.exit(1)

# credentials.json を復元
creds_path = CONFIG_DIR / "credentials.json"
creds_path.write_bytes(base64.b64decode(os.environ["GOOGLE_CREDENTIALS_B64"]))
print(f"credentials.json 復元完了: {creds_path}")

# token.pickle を復元（g.kamifor: Gmail + Calendar）
token_path = CONFIG_DIR / "token.pickle"
token_path.write_bytes(base64.b64decode(os.environ["GOOGLE_TOKEN_PICKLE_B64"]))
print(f"token.pickle 復元完了: {token_path}")

print("=== Google認証ファイル復元完了 ===")

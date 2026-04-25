"""
Google OAuthトークン（g.kamifor）再発行スクリプト

GitHub Actions で invalid_grant エラーが出た場合にローカルで実行する。
ブラウザ認証完了後、新しいトークンのbase64値を出力するので
GitHub Secrets の GOOGLE_TOKEN_PICKLE_B64 を更新すること。

使い方:
  python3 ci/refresh_token.py
"""

import base64
import pickle
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

CONFIG_DIR = Path.home() / ".config" / "ai-secretary"
CREDENTIALS = CONFIG_DIR / "credentials.json"
TOKEN_FILE = CONFIG_DIR / "token.pickle"

if not CREDENTIALS.exists():
    print(f"[ERROR] credentials.json が見つかりません: {CREDENTIALS}", file=sys.stderr)
    sys.exit(1)

if TOKEN_FILE.exists():
    TOKEN_FILE.unlink()
    print("古い token.pickle を削除しました")

print("\n" + "=" * 60)
print("ブラウザが開きます。g.kamifor@gmail.com でログインしてください。")
print("=" * 60 + "\n")

flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS), SCOPES)
creds = flow.run_local_server(
    port=0,
    login_hint="g.kamifor@gmail.com",
    prompt="consent",
)

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
with open(TOKEN_FILE, "wb") as f:
    pickle.dump(creds, f)

print(f"\n✓ token.pickle を保存しました: {TOKEN_FILE}")
print("\n" + "=" * 60)
print("GitHub Secrets を以下の値で更新してください:")
print("Secret名: GOOGLE_TOKEN_PICKLE_B64")
print("=" * 60)
encoded = base64.b64encode(TOKEN_FILE.read_bytes()).decode()
print(encoded)
print("=" * 60)
print("\nGitHub: https://github.com/yonetomo113/ai-secretary/settings/secrets/actions")

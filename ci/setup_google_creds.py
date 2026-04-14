"""
GitHub Actions 用 Google認証ファイル構築スクリプト

環境変数から credentials.json と token pickle ファイルを生成する。
morning_briefing.py 実行前に必ず本スクリプトを実行すること。

必要な環境変数:
  GMAIL_CLIENT_ID           - Google OAuth クライアントID
  GMAIL_CLIENT_SECRET       - Google OAuth クライアントシークレット
  GMAIL_REFRESH_TOKEN       - g.kamifor@gmail.com のリフレッシュトークン
  GMAIL_REFRESH_TOKEN_XEDGE - xedgeltd@gmail.com のリフレッシュトークン
"""

import json
import os
import pickle
import sys
from pathlib import Path

from google.oauth2.credentials import Credentials

CONFIG_DIR = Path.home() / ".config" / "ai-secretary"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# 必須環境変数チェック
required = [
    "GMAIL_CLIENT_ID",
    "GMAIL_CLIENT_SECRET",
    "GMAIL_REFRESH_TOKEN",
    "GMAIL_REFRESH_TOKEN_XEDGE",
]
missing = [k for k in required if not os.environ.get(k)]
if missing:
    print(f"[ERROR] 以下の環境変数が未設定です: {missing}", file=sys.stderr)
    sys.exit(1)

client_id     = os.environ["GMAIL_CLIENT_ID"]
client_secret = os.environ["GMAIL_CLIENT_SECRET"]

# ── credentials.json を構築 ───────────────────────────────────────
creds_json = {
    "installed": {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}
creds_path = CONFIG_DIR / "credentials.json"
with open(creds_path, "w") as f:
    json.dump(creds_json, f)
print(f"credentials.json 作成完了: {creds_path}")

# ── token.pickle（g.kamifor: Gmail + Calendar）を構築 ────────────
scopes_full = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]
creds_kamifor = Credentials(
    token=None,
    refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
    token_uri="https://oauth2.googleapis.com/token",
    client_id=client_id,
    client_secret=client_secret,
    scopes=scopes_full,
)
token_path = CONFIG_DIR / "token.pickle"
with open(token_path, "wb") as f:
    pickle.dump(creds_kamifor, f)
print(f"token.pickle (g.kamifor) 作成完了: {token_path}")

# ── token_xedge.pickle（xedgeltd: Calendar のみ）を構築 ──────────
scopes_cal = ["https://www.googleapis.com/auth/calendar.readonly"]
creds_xedge = Credentials(
    token=None,
    refresh_token=os.environ["GMAIL_REFRESH_TOKEN_XEDGE"],
    token_uri="https://oauth2.googleapis.com/token",
    client_id=client_id,
    client_secret=client_secret,
    scopes=scopes_cal,
)
token_xedge_path = CONFIG_DIR / "token_xedge.pickle"
with open(token_xedge_path, "wb") as f:
    pickle.dump(creds_xedge, f)
print(f"token_xedge.pickle (xedgeltd) 作成完了: {token_xedge_path}")

print("=== Google認証ファイル構築完了 ===")

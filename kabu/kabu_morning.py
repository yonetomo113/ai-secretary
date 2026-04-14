"""
カブさん 朝次実行スクリプト
  - データ取得 → ルール/パターン分析 → レポート生成 → Gmail送信
  - GitHub Actions（毎朝JST 8:50）および手動実行の両対応

Gmail認証に必要な環境変数:
  GMAIL_CLIENT_ID
  GMAIL_CLIENT_SECRET
  GMAIL_REFRESH_TOKEN
"""

import os
import sys
import base64
import json
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

import requests

# kabu/ ディレクトリをパスに追加（ローカル・CI両対応）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SYMBOLS, SYMBOL_NAMES
from fetch import fetch_and_store
from db import load_prices
from rules import evaluate_rules, summarize_flags
from patterns import detect_patterns
from report import build_report, save_report, FLAG_LABELS

RECIPIENT = "g.kamifor@gmail.com"

OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://www.googleapis.com/gmail/v1/users/me/messages/send"


# -----------------------------------------------------------------------
# Gmail送信
# -----------------------------------------------------------------------

def _get_access_token() -> str:
    """リフレッシュトークンからアクセストークンを取得"""
    client_id = os.environ["GMAIL_CLIENT_ID"]
    client_secret = os.environ["GMAIL_CLIENT_SECRET"]
    refresh_token = os.environ["GMAIL_REFRESH_TOKEN"]

    resp = requests.post(OAUTH_TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }, timeout=15)
    resp.raise_for_status()
    return resp.json()["access_token"]


def _build_mime(subject: str, body: str) -> str:
    """MIMEメッセージをbase64urlエンコードして返す"""
    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = RECIPIENT
    msg["From"] = "me"
    msg["Subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return raw


def send_report_email(report_text: str, date_str: str) -> None:
    """レポートをGmailで送信する"""
    subject = f"【カブさん】本日の相場報告 {date_str}"
    access_token = _get_access_token()

    raw = _build_mime(subject, report_text)
    resp = requests.post(
        GMAIL_SEND_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        json={"raw": raw},
        timeout=20,
    )
    resp.raise_for_status()
    print(f"メール送信完了 → {RECIPIENT}")


# -----------------------------------------------------------------------
# 分析
# -----------------------------------------------------------------------

def run_analysis() -> list:
    results = []
    for symbol in SYMBOLS:
        df = load_prices(symbol, limit=60)
        if df.empty or len(df) < 5:
            print(f"  {symbol}: データ不足のためスキップ")
            continue

        rule_results = evaluate_rules(df, symbol)
        pattern_results = detect_patterns(df)
        final_flag = summarize_flags(rule_results)

        results.append({
            "symbol": symbol,
            "final_flag": final_flag,
            "rules": rule_results,
            "patterns": pattern_results,
        })

        name = SYMBOL_NAMES.get(symbol, symbol)
        flag_label = FLAG_LABELS.get(final_flag, final_flag)
        print(f"  {name}（{symbol}）: {flag_label}")
    return results


# -----------------------------------------------------------------------
# メイン
# -----------------------------------------------------------------------

def main():
    today = datetime.now().strftime("%Y年%m月%d日")
    print(f"\n{'='*50}")
    print(f"  カブさん朝次実行  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    # Step1: データ取得
    print("【Step1】データ取得中...")
    fetch_and_store()
    print()

    # Step2/3: 分析
    print("【Step2/3】ルール・パターン分析中...")
    results = run_analysis()
    print()

    # Step4: レポート生成
    print("【Step4】レポート生成中...")
    report_text = build_report(results, today)
    path = save_report(report_text)
    print(f"レポート保存先: {path}\n")
    print(report_text)

    # Step5: Gmail送信
    gmail_vars = ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")
    if all(os.environ.get(v) for v in gmail_vars):
        print("\n【Step5】Gmail送信中...")
        try:
            send_report_email(report_text, today)
        except Exception as e:
            print(f"メール送信失敗: {e}")
            sys.exit(1)
    else:
        print("\n【Step5】Gmail環境変数が未設定のためメール送信をスキップ")


if __name__ == "__main__":
    main()

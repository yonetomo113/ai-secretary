"""
カブさん メインエントリーポイント

使い方:
  python main.py fetch      # データ取得・保存のみ
  python main.py report     # レポート生成のみ（DBデータ使用）
  python main.py            # fetch + report を両方実行
"""

import sys
import os
import base64
import pickle
from email.mime.text import MIMEText
from pathlib import Path

# kabu/ ディレクトリを import パスに追加
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime, timezone, timedelta
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from config import SYMBOLS, SYMBOL_NAMES
from fetch import fetch_and_store
from db import load_prices
from rules import evaluate_rules, summarize_flags
from patterns import detect_patterns
from report import build_report, save_report, FLAG_LABELS

SEND_FROM = "g.kamifor@gmail.com"
RECIPIENT = "g.kamifor@gmail.com"
TOKEN_FILE = Path.home() / ".config" / "ai-secretary" / "token.pickle"
JST = timezone(timedelta(hours=9))


def _get_gmail_service():
    """token.pickle から Gmail API サービスを取得する"""
    with open(TOKEN_FILE, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
    return build("gmail", "v1", credentials=creds)


def send_report_email(report_text: str, date_str: str) -> None:
    """Gmail API（g.kamifor OAuth）でレポートを送信する"""
    service = _get_gmail_service()
    subject = f"【カブさん】本日の相場報告 {date_str}"
    msg = MIMEText(report_text, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = SEND_FROM
    msg["To"]      = RECIPIENT
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"メール送信完了 → {RECIPIENT}")


def run_analysis() -> list[dict]:
    """全銘柄を分析してresultsリストを返す"""
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


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    print(f"\n{'='*50}")
    print(f"  カブさん起動  {datetime.now(JST).strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    if mode in ("fetch", "all"):
        print("【Step1】データ取得中...")
        fetch_and_store()
        print()

    if mode in ("report", "all"):
        today = datetime.now(JST).strftime("%Y年%m月%d日")

        print("【Step2/3】ルール・パターン分析中...")
        results = run_analysis()
        print()

        print("【Step4】レポート生成中...")
        report_text = build_report(results, today)
        path = save_report(report_text)

        print()
        print(report_text)
        print(f"\nレポート保存先: {path}")

        print("\n【Step5】Gmail送信中...")
        now_jst = datetime.now(JST)
        if now_jst.hour < 15 or (now_jst.hour == 15 and now_jst.minute < 30):
            print(f"⚠ 現在 {now_jst.strftime('%H:%M')} JST — 大引け(15:30)前のため送信をスキップします")
            print("  15:30以降に再実行してください")
            sys.exit(0)
        try:
            send_report_email(report_text, today)
        except Exception as e:
            print(f"メール送信失敗: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()

"""
カブさん 朝次実行スクリプト
  - データ取得 → ルール/パターン分析 → レポート生成 → Gmail送信
  - GitHub Actions（毎朝JST 8:50）および手動実行の両対応

メール送信に必要な環境変数:
  XEDGE_GMAIL_APP_PASSWORD  - xedgeltd@gmail.com のアプリパスワード
"""

import os
import sys
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

# kabu/ ディレクトリをパスに追加（ローカル・CI両対応）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SYMBOLS, SYMBOL_NAMES
from fetch import fetch_and_store
from db import load_prices
from rules import evaluate_rules, summarize_flags
from patterns import detect_patterns
from report import build_report, save_report, FLAG_LABELS

SMTP_HOST  = "smtp.gmail.com"
SMTP_PORT  = 587
SMTP_USER  = "xedgeltd@gmail.com"
SEND_FROM  = "xedgeltd@gmail.com"
RECIPIENT  = "g.kamifor@gmail.com"


# -----------------------------------------------------------------------
# Gmail送信（SMTP）
# -----------------------------------------------------------------------

def send_report_email(report_text: str, date_str: str) -> None:
    """レポートをSMTP経由でGmail送信する"""
    app_password = os.environ["XEDGE_GMAIL_APP_PASSWORD"]
    subject = f"【カブさん】本日の相場報告 {date_str}"

    msg = MIMEText(report_text, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = SEND_FROM
    msg["To"]      = RECIPIENT

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(SMTP_USER, app_password)
        smtp.sendmail(SEND_FROM, RECIPIENT, msg.as_string())

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
    if os.environ.get("XEDGE_GMAIL_APP_PASSWORD"):
        print("\n【Step5】Gmail送信中...")
        try:
            send_report_email(report_text, today)
        except Exception as e:
            print(f"メール送信失敗: {e}")
            sys.exit(1)
    else:
        print("\n【Step5】XEDGE_GMAIL_APP_PASSWORD未設定のためメール送信をスキップ")


if __name__ == "__main__":
    main()

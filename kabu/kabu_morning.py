"""
カブさん 朝次実行スクリプト
フロー:
  1. yfinanceでデータ取得・保存（10銘柄）
  2. Gmail APIで「マーケットメール-朝刊-」最新メールを取得
  3. Claude APIで12銘柄の影響を分析
  4. テクニカル分析と併記してメール送信
"""
import os, sys, base64, pickle
from email.mime.text import MIMEText
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import anthropic

from config import SYMBOLS, SYMBOL_NAMES
from fetch import fetch_and_store
from db import load_prices
from rules import evaluate_rules, summarize_flags
from patterns import detect_patterns
from report import build_report, save_report, FLAG_LABELS

load_dotenv(Path.home() / ".env")

SEND_FROM = "g.kamifor@gmail.com"
RECIPIENT = "g.kamifor@gmail.com"
TOKEN_FILE = Path.home() / ".config" / "ai-secretary" / "token.pickle"

# Claude分析対象12銘柄
CLAUDE_SYMBOLS = {
    "5016.T": "JX金属",
    "5803.T": "フジクラ",
    "7011.T": "三菱重工業",
    "9984.T": "ソフトバンクG",
    "6758.T": "ソニーグループ",
    "7203.T": "トヨタ自動車",
    "8306.T": "三菱UFJ",
    "4062.T": "イビデン",
    "7974.T": "任天堂",
    "5801.T": "古河電工",
    "285A.T": "キオクシアHD",
    "1547.T": "上場米国(S&P500)",
}


def _get_gmail_service():
    with open(TOKEN_FILE, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
    return build("gmail", "v1", credentials=creds)


def _extract_body(payload: dict) -> str:
    """Gmail messageのpayloadから本文テキストを再帰的に抽出"""
    mime = payload.get("mimeType", "")
    data = payload.get("body", {}).get("data", "")

    if data and mime == "text/plain":
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        result = _extract_body(part)
        if result:
            return result

    # text/plainが見つからない場合はhtmlにフォールバック
    if data and "html" in mime:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    return ""


def fetch_market_mail() -> tuple[str, str]:
    """「マーケットメール-朝刊-」を含む最新メールの件名と本文を返す"""
    service = _get_gmail_service()
    result = service.users().messages().list(
        userId="me",
        q='subject:"マーケットメール-朝刊-"',
        maxResults=1,
    ).execute()

    messages = result.get("messages", [])
    if not messages:
        return "", ""

    msg = service.users().messages().get(
        userId="me",
        id=messages[0]["id"],
        format="full",
    ).execute()

    headers = msg["payload"].get("headers", [])
    subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")
    body = _extract_body(msg["payload"])
    return subject, body


def analyze_with_claude(mail_subject: str, mail_body: str) -> str:
    """Claude APIでマーケットメールを分析し、12銘柄の判定を返す"""
    symbol_list = "\n".join(
        f"- {name}（{code}）" for code, name in CLAUDE_SYMBOLS.items()
    )
    prompt = f"""以下は今朝のマーケットメール（朝刊）です。

件名: {mail_subject}

---
{mail_body[:6000]}
---

上記のマーケット情報をもとに、以下の12銘柄それぞれについて本日の取引判断を行ってください。

対象銘柄:
{symbol_list}

各銘柄について以下のフォーマットで出力してください（12銘柄全て）:
[銘柄名（コード）] 判定: 買い推奨 / 見送り / 様子見 — 理由（1〜2文）

判定基準:
- 買い推奨: マーケット情報がその銘柄にとってポジティブ
- 見送り: マーケット情報がその銘柄にとってネガティブ、または下落リスクが高い
- 様子見: 方向感が定まらない、または情報が不十分

簡潔に、各銘柄1〜2文で。"""

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def run_technical_analysis() -> list[dict]:
    """10銘柄のテクニカル分析を実行"""
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
        print(f"  {name}（{symbol}）: {FLAG_LABELS.get(final_flag, final_flag)}")
    return results


def build_morning_report(
    claude_analysis: str,
    technical_results: list[dict],
    today: str,
    mail_subject: str,
) -> str:
    """Claude分析 + テクニカル分析を合わせたレポートを生成"""
    now_str = datetime.now().strftime("%H:%M")
    lines = []
    lines.append("=" * 60)
    lines.append(f"  カブさん 朝刊分析レポート  {today}  {now_str}")
    lines.append("=" * 60)
    lines.append("")
    lines.append("社長！本日のマーケット分析です。")
    lines.append(f"参照: {mail_subject}")
    lines.append("")

    lines.append("【AI分析（マーケットメール朝刊）】")
    lines.append(claude_analysis)
    lines.append("")

    lines.append("【テクニカル分析（直近データ）】")
    tech_lines = build_report(technical_results, today).split("\n")
    lines.extend(l for l in tech_lines if not l.startswith("="))

    return "\n".join(lines)


def send_report_email(report_text: str, date_str: str) -> None:
    """Gmail APIでレポートを送信"""
    service = _get_gmail_service()
    subject = f"【カブさん】朝刊分析レポート {date_str}"
    msg = MIMEText(report_text, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SEND_FROM
    msg["To"] = RECIPIENT
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"メール送信完了 → {RECIPIENT}")


def main():
    today = datetime.now().strftime("%Y年%m月%d日")
    print(f"\n{'='*50}\n  カブさん朝次実行  {datetime.now().strftime('%Y-%m-%d %H:%M')}\n{'='*50}\n")

    print("【Step1】株価データ取得中...")
    fetch_and_store()

    print("\n【Step2】マーケットメール取得中...")
    mail_subject, mail_body = fetch_market_mail()
    if not mail_body:
        print("  ⚠ マーケットメールが見つかりません。Claude分析をスキップします。")
        claude_analysis = "（マーケットメールが取得できなかったため、AI分析は実施しませんでした）"
        mail_subject = "（未取得）"
    else:
        print(f"  件名: {mail_subject}")
        print("\n【Step3】Claude APIで銘柄分析中...")
        claude_analysis = analyze_with_claude(mail_subject, mail_body)

    print("\n【Step4】テクニカル分析中...")
    technical_results = run_technical_analysis()

    print("\n【Step5】レポート生成中...")
    report_text = build_morning_report(claude_analysis, technical_results, today, mail_subject)
    path = save_report(report_text)
    print(f"レポート保存先: {path}\n")
    print(report_text)

    print("\n【Step6】Gmail送信中...")
    try:
        send_report_email(report_text, today)
    except Exception as e:
        print(f"メール送信失敗: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

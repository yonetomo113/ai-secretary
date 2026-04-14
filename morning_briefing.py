#!/usr/bin/env python3
"""
morning_briefing.py
朝のブリーフィング：Gmail + Google Calendar（2アカウント）→ Claude要約 → メール送信

Cloud Project  : crossedge-airbnb（xedgeltd@gmail.com）
Gmail取得      : g.kamifor@gmail.com
Calendar取得   : g.kamifor@gmail.com + xedgeltd@gmail.com（マージ）
送信先         : g.kamifor@gmail.com

credentials.json    : ~/.config/ai-secretary/credentials.json
token.pickle        : ~/.config/ai-secretary/token.pickle        (g.kamifor)
token_xedge.pickle  : ~/.config/ai-secretary/token_xedge.pickle  (xedgeltd)
ログ                : ~/ai-secretary/logs/morning_briefing_YYYYMMDD.log

使い方:
  python3 morning_briefing.py              # 通常実行
  python3 morning_briefing.py --reauth     # g.kamifor を再認証
  python3 morning_briefing.py --auth-xedge # xedgeltd を再認証
"""

import os
import pickle
import re
import smtplib
import sys
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ── 設定 ──────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
CONFIG_DIR  = Path.home() / ".config" / "ai-secretary"
CREDENTIALS      = CONFIG_DIR / "credentials.json"
TOKEN_FILE       = CONFIG_DIR / "token.pickle"        # g.kamifor@gmail.com
TOKEN_FILE_XEDGE = CONFIG_DIR / "token_xedge.pickle"  # xedgeltd@gmail.com
LOG_DIR     = BASE_DIR / "ai-secretary" / "logs"
JST         = timezone(timedelta(hours=9))

load_dotenv(BASE_DIR / ".env")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
GMAIL_APP_PASSWORD = os.environ.get("XEDGE_GMAIL_APP_PASSWORD", "")
# SMTPはxedgeltd経由で送信（g.kamifor宛）
SMTP_USER   = "xedgeltd@gmail.com"
SEND_FROM   = "xedgeltd@gmail.com"
SEND_TO     = "g.kamifor@gmail.com"
CLAUDE_MODEL = "claude-sonnet-4-20250514"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]
SCOPES_CAL_ONLY = [
    "https://www.googleapis.com/auth/calendar.readonly",
]

# Gmail検索クエリ（g.kamifor@gmail.com のメールボックス）
GMAIL_QUERIES = {
    # "未読":           "is:unread -category:promotions",
    "チェックイン":   "subject:(チェックイン OR check-in OR 予約確認 OR reservation) newer_than:3d",
    "チェックアウト": "subject:(チェックアウト OR check-out) newer_than:3d",
    "清掃":           "subject:(清掃 OR クリーニング OR cleaning) newer_than:3d",
}


# ── ログ ──────────────────────────────────────────────────────────
class Tee:
    def __init__(self, *streams):
        self.streams = streams
    def write(self, data):
        for s in self.streams:
            s.write(data)
            s.flush()
    def flush(self):
        for s in self.streams:
            s.flush()

def setup_log():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(JST).strftime("%Y%m%d")
    log_path = LOG_DIR / f"morning_briefing_{date_str}.log"
    log_file = open(log_path, "a", encoding="utf-8")
    sys.stdout = Tee(sys.stdout, log_file)
    sys.stderr = Tee(sys.stderr, log_file)
    return log_path

def log(msg):
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")


# ── Google OAuth ──────────────────────────────────────────────────
def get_google_creds(reauth=False):
    if reauth and TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
        log("token.pickle を削除しました（再認証）")

    creds = None
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_FILE, "wb") as f:
                pickle.dump(creds, f)
            log("token.pickle を更新しました")
            return creds
        except Exception as e:
            log(f"トークンリフレッシュ失敗: {e} → 再認証します")
            if TOKEN_FILE.exists():
                TOKEN_FILE.unlink()

    # 新規認証
    if not CREDENTIALS.exists():
        raise FileNotFoundError(
            f"credentials.json が見つかりません: {CREDENTIALS}\n"
            "Google Cloud Console > crossedge-airbnb プロジェクト >\n"
            "APIとサービス > 認証情報 > OAuth 2.0クライアントID からダウンロードしてください。"
        )

    print("\n" + "=" * 60)
    print("【Google認証が必要です】")
    print("ブラウザが開いたら  g.kamifor@gmail.com  でログインしてください。")
    print("=" * 60 + "\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS), SCOPES)
    creds = flow.run_local_server(
        port=0,
        login_hint="g.kamifor@gmail.com",   # ログインアカウントを事前指定
        prompt="consent",                    # 毎回同意画面を表示（アカウント切替ミス防止）
    )

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, "wb") as f:
        pickle.dump(creds, f)
    log(f"token.pickle を保存しました: {TOKEN_FILE}")
    return creds


def get_google_creds_xedge(reauth=False):
    """xedgeltd@gmail.com 用 OAuth（Calendar のみ）"""
    if reauth and TOKEN_FILE_XEDGE.exists():
        TOKEN_FILE_XEDGE.unlink()
        log("token_xedge.pickle を削除しました（再認証）")

    creds = None
    if TOKEN_FILE_XEDGE.exists():
        with open(TOKEN_FILE_XEDGE, "rb") as f:
            creds = pickle.load(f)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_FILE_XEDGE, "wb") as f:
                pickle.dump(creds, f)
            log("token_xedge.pickle を更新しました")
            return creds
        except Exception as e:
            log(f"xedge トークンリフレッシュ失敗: {e} → 再認証します")
            if TOKEN_FILE_XEDGE.exists():
                TOKEN_FILE_XEDGE.unlink()

    if not CREDENTIALS.exists():
        raise FileNotFoundError(f"credentials.json が見つかりません: {CREDENTIALS}")

    print("\n" + "=" * 60)
    print("【xedgeltd@gmail.com の Google認証が必要です】")
    print("ブラウザが開いたら  xedgeltd@gmail.com  でログインしてください。")
    print("=" * 60 + "\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS), SCOPES_CAL_ONLY)
    creds = flow.run_local_server(
        port=0,
        login_hint="xedgeltd@gmail.com",
        prompt="consent",
    )

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE_XEDGE, "wb") as f:
        pickle.dump(creds, f)
    log(f"token_xedge.pickle を保存しました: {TOKEN_FILE_XEDGE}")
    return creds


# ── Gmail ─────────────────────────────────────────────────────────
def fetch_gmail(service, query, max_results=10):
    result = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()
    messages = result.get("messages", [])
    items = []
    for m in messages:
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["Subject", "From", "Date"]
        ).execute()
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        items.append({
            "subject": headers.get("Subject", "(件名なし)"),
            "from":    headers.get("From", ""),
            "date":    headers.get("Date", ""),
            "snippet": msg.get("snippet", ""),
        })
    return items

def gmail_section(service):
    lines = []
    for label, query in GMAIL_QUERIES.items():
        items = fetch_gmail(service, query, max_results=5)
        lines.append(f"\n### {label}（{len(items)}件）")
        if not items:
            lines.append("  なし")
            continue
        for it in items:
            date_short = it["date"][:16] if it["date"] else ""
            lines.append(f"  - [{date_short}] {it['subject']}")
            if it["snippet"]:
                snippet = re.sub(r"\s+", " ", it["snippet"])[:80]
                lines.append(f"      {snippet}")
    return "\n".join(lines)


# ── Google Calendar ───────────────────────────────────────────────
def fetch_events(service):
    """1日分のイベントリストを取得"""
    jst_today = datetime.now(JST)
    day_start = jst_today.replace(hour=0,  minute=0,  second=0,  microsecond=0)
    day_end   = jst_today.replace(hour=23, minute=59, second=59, microsecond=0)
    result = service.events().list(
        calendarId="primary",
        timeMin=day_start.isoformat(),
        timeMax=day_end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=20,
    ).execute()
    return result.get("items", [])


def calendar_section(gkami_service, xedge_service=None):
    """g.kamifor + xedgeltd のカレンダーをマージして表示"""
    jst_today = datetime.now(JST)

    # g.kamifor のイベント
    gkami_events = [(e, "g.kamifor") for e in fetch_events(gkami_service)]

    # xedgeltd のイベント
    xedge_events = []
    if xedge_service:
        try:
            xedge_events = [(e, "xedgeltd") for e in fetch_events(xedge_service)]
        except Exception as ex:
            log(f"xedgeltd カレンダー取得失敗（スキップ）: {ex}")

    # 時刻でソートしてマージ
    all_events = gkami_events + xedge_events

    def sort_key(item):
        e = item[0]
        start = e["start"].get("dateTime", e["start"].get("date", ""))
        return start

    all_events.sort(key=sort_key)

    lines = [f"\n### 本日のカレンダー（{jst_today.strftime('%Y-%m-%d %a')}）"]
    if not all_events:
        lines.append("  予定なし")
    for e, account in all_events:
        start = e["start"].get("dateTime", e["start"].get("date", ""))
        t = datetime.fromisoformat(start).astimezone(JST).strftime("%H:%M") \
            if "T" in start else "終日"
        title  = e.get("summary", "(タイトルなし)")
        label  = f" [{account}]" if xedge_service else ""
        lines.append(f"  {t}  {title}{label}")
    return "\n".join(lines)


# ── Claude 要約 ───────────────────────────────────────────────────
def summarize(raw_text: str) -> str:
    if not ANTHROPIC_API_KEY:
        return "（ANTHROPIC_API_KEY 未設定のため要約スキップ）"
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""以下は有限会社クロスエッジ代表・米岡朋彦の朝のブリーフィングデータです。
民泊・旅館（竹屋旅籠・登竜庵）の運営に関係する情報を優先し、
今日やるべきことを箇条書きで簡潔にまとめてください。

【データ】
{raw_text}

【出力ルール】
- 箇条書き、重要度順
- 絵文字なし、断定調
- 1行100字以内
- アクション不要な情報は省略
"""
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


# ── メール送信（SMTP / xedgeltd→g.kamifor）────────────────────────
def send_mail(subject: str, body: str):
    if not GMAIL_APP_PASSWORD:
        log("警告: XEDGE_GMAIL_APP_PASSWORD 未設定のためメール送信スキップ")
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SEND_FROM
    msg["To"]      = SEND_TO
    msg.attach(MIMEText(body, "plain", "utf-8"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
            s.login(SMTP_USER, GMAIL_APP_PASSWORD)
            s.send_message(msg)
        log(f"メール送信完了 → {SEND_TO}")
    except Exception as e:
        log(f"メール送信失敗: {e}")


# ── メイン ────────────────────────────────────────────────────────
def main():
    reauth      = "--reauth"     in sys.argv
    auth_xedge  = "--auth-xedge" in sys.argv
    log_path    = setup_log()
    now_str     = datetime.now(JST).strftime("%Y-%m-%d %H:%M")

    log(f"=== 朝のブリーフィング開始 {now_str} ===")

    # g.kamifor@gmail.com 認証（Gmail + Calendar）
    log("Google認証中（g.kamifor@gmail.com）...")
    creds_gkami = get_google_creds(reauth=reauth)
    gmail_sv    = build("gmail",    "v1", credentials=creds_gkami)
    cal_gkami   = build("calendar", "v3", credentials=creds_gkami)
    log("g.kamifor 認証完了")

    # xedgeltd@gmail.com 認証（Calendar のみ）
    log("Google認証中（xedgeltd@gmail.com）...")
    try:
        creds_xedge = get_google_creds_xedge(reauth=auth_xedge)
        cal_xedge   = build("calendar", "v3", credentials=creds_xedge)
        log("xedgeltd 認証完了")
    except Exception as e:
        log(f"xedgeltd 認証失敗（スキップ）: {e}")
        cal_xedge = None

    # データ収集
    log("Gmail取得中...")
    g_text = gmail_section(gmail_sv)

    log("カレンダー取得中（両アカウント）...")
    c_text = calendar_section(cal_gkami, cal_xedge)

    raw = f"{g_text}\n\n{c_text}"

    # Claude要約
    log("Claude要約中...")
    summary = summarize(raw)

    # 出力組み立て
    sep    = "=" * 60
    output = (
        f"{sep}\n"
        f"朝のブリーフィング  {now_str}\n"
        f"{sep}\n"
        f"\n## 【今日のアクション】\n{summary}\n"
        f"\n{sep}\n"
        f"{raw}\n"
        f"{sep}\n"
        f"ログ: {log_path}\n"
    )

    print(output)

    # メール送信
    send_mail(f"朝のブリーフィング {now_str}", output)

    log("=== 完了 ===\n")


if __name__ == "__main__":
    main()

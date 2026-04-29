#!/usr/bin/env python3
"""
morning_briefing.py
朝のブリーフィング：Gmail + Google Calendar → Claude要約 → メール送信

Gmail取得  : g.kamifor@gmail.com（通常メール + Airbnbメール）
Calendar  : g.kamifor@gmail.com
送信先    : g.kamifor@gmail.com

credentials.json : ~/.config/ai-secretary/credentials.json
token.pickle     : ~/.config/ai-secretary/token.pickle  (g.kamifor)
ログ             : ~/ai-secretary/logs/morning_briefing_YYYYMMDD.log

使い方:
  python3 morning_briefing.py          # 通常実行
  python3 morning_briefing.py --reauth # g.kamifor を再認証
"""

import base64
import json
import os
import pickle
import re
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

try:
    from assift_automator import sync_airbnb_to_pending, load_pending
except ImportError:
    sync_airbnb_to_pending = None
    load_pending = None

# ── 設定 ──────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
CONFIG_DIR  = Path.home() / ".config" / "ai-secretary"
CREDENTIALS      = CONFIG_DIR / "credentials.json"
TOKEN_FILE       = CONFIG_DIR / "token.pickle"        # g.kamifor@gmail.com
LOG_DIR     = BASE_DIR / "ai-secretary" / "logs"
JST         = timezone(timedelta(hours=9))

load_dotenv(BASE_DIR / ".env")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
SEND_FROM   = "g.kamifor@gmail.com"
SEND_TO     = "g.kamifor@gmail.com"
CLAUDE_MODEL = "claude-sonnet-4-6"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# Gmail検索クエリ（g.kamifor@gmail.com のメールボックス）
GMAIL_QUERIES = {
    # "未読":           "is:unread -category:promotions",
    "チェックイン":   "subject:(チェックイン OR check-in OR 予約確認 OR reservation) newer_than:3d",
    "チェックアウト": "subject:(チェックアウト OR check-out) newer_than:3d",
    "清掃":           "subject:(清掃 OR クリーニング OR cleaning) newer_than:3d",
}

# Airbnb検索クエリ（g.kamifor@gmail.com のメールボックス）
AIRBNB_QUERIES = {
    "チェックイン": (
        "from:airbnb.com "
        "(subject:チェックイン OR subject:check-in OR subject:本日のゲスト OR subject:arriving) "
        "newer_than:2d"
    ),
    "チェックアウト": (
        "from:airbnb.com "
        "(subject:チェックアウト OR subject:check-out OR subject:checkout) "
        "newer_than:2d"
    ),
    "新規予約": (
        "from:airbnb.com "
        "(subject:予約確認 OR subject:reservation confirmed OR subject:booking confirmed OR subject:新しいご予約) "
        "newer_than:2d"
    ),
    "清掃": (
        "from:airbnb.com "
        "(subject:清掃 OR subject:クリーニング OR subject:cleaning) "
        "newer_than:2d"
    ),
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

    # CI環境ではブラウザ認証不可 → 明確なエラーで終了
    if os.environ.get("CI"):
        raise RuntimeError(
            "Google OAuthトークン（g.kamifor）が失効しています。\n"
            "ローカルで再認証後、GitHub Secretsを更新してください:\n"
            "  python3 morning_briefing.py  # ブラウザ認証を完了させる\n"
            "  base64 -i ~/.config/ai-secretary/token.pickle | tr -d '\\n'\n"
            "  → GitHub Settings > Secrets > GOOGLE_TOKEN_PICKLE_B64 を更新"
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


def airbnb_section(gmail_service):
    """g.kamifor@gmail.com のAirbnb予約メールを取得して表示"""
    lines = ["\n### Airbnb予約メール"]
    found_any = False
    for label, query in AIRBNB_QUERIES.items():
        items = fetch_gmail(gmail_service, query, max_results=5)
        if not items:
            continue
        found_any = True
        lines.append(f"\n  ▼ {label}（{len(items)}件）")
        for it in items:
            date_short = it["date"][:16] if it["date"] else ""
            lines.append(f"    - [{date_short}] {it['subject']}")
            if it["snippet"]:
                snippet = re.sub(r"\s+", " ", it["snippet"])[:100]
                lines.append(f"        {snippet}")
    if not found_any:
        lines.append("  なし")
    return "\n".join(lines)


# ── Google Calendar ───────────────────────────────────────────────
def fetch_events(service):
    """当日分のイベントリストを取得（UTC1日ずれ対応）"""
    jst_today = datetime.now(JST)
    today_str = jst_today.strftime("%Y-%m-%d")

    # timeMinを前日JST0時に設定（終日イベントのUTCずれをカバー）
    day_start = (jst_today - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    day_end = jst_today.replace(hour=23, minute=59, second=59, microsecond=0)

    result = service.events().list(
        calendarId="primary",
        timeMin=day_start.isoformat(),
        timeMax=day_end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=50,
    ).execute()

    filtered = []
    for e in result.get("items", []):
        start_date = e["start"].get("date")      # 終日イベント: "YYYY-MM-DD"
        start_dt   = e["start"].get("dateTime")  # 時刻付き: ISO8601
        if start_date:
            if start_date == today_str:
                filtered.append(e)
        elif start_dt:
            dt_jst = datetime.fromisoformat(start_dt).astimezone(JST)
            if dt_jst.strftime("%Y-%m-%d") == today_str:
                filtered.append(e)
    return filtered


def calendar_section(gkami_service):
    """g.kamifor@gmail.com のカレンダーを表示"""
    jst_today = datetime.now(JST)
    events = fetch_events(gkami_service)

    def sort_key(e):
        return e["start"].get("dateTime", e["start"].get("date", ""))

    events.sort(key=sort_key)

    lines = [f"\n### 本日のカレンダー（{jst_today.strftime('%Y-%m-%d %a')}）"]
    if not events:
        lines.append("  予定なし")
    for e in events:
        start = e["start"].get("dateTime", e["start"].get("date", ""))
        t = datetime.fromisoformat(start).astimezone(JST).strftime("%H:%M") \
            if "T" in start else "終日"
        title = e.get("summary", "(タイトルなし)")
        lines.append(f"  {t}  {title}")
    return "\n".join(lines)


# ── Claude 要約 ───────────────────────────────────────────────────
def summarize(raw_text: str) -> str:
    if not ANTHROPIC_API_KEY:
        return "（ANTHROPIC_API_KEY 未設定のため要約スキップ）"
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""以下は有限会社クロスエッジ代表・米岡朋彦の朝のブリーフィングデータです。
民泊・旅館（竹屋旅籠・登竜庵）の運営に関係する情報を優先し、
今日やるべきことを箇条書きで簡潔にまとめてください。

重要度の基準（高→低）: 法的期限・許認可 > 対外アポイント > ゲスト対応 > 業者・清掃対応 > その他

【データ】
{raw_text}

【出力ルール】
- 箇条書き、重要度順
- 絵文字なし、断定調
- 1行100字以内
- アクション不要な情報は省略
- データが空またはアクション不要な情報のみの場合は「本日のアクションなし」と1行だけ出力
"""
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        system="あなたは有限会社クロスエッジの秘書AIです。出力は「・」始まりの箇条書きのみ。前置き・後書き・ヘッダーは一切書かない。",
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


# ── メール送信（Gmail API / g.kamifor OAuth）──────────────────────
def send_mail(subject: str, body: str, gmail_service):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SEND_FROM
    msg["To"]      = SEND_TO
    msg.attach(MIMEText(body, "plain", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        gmail_service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        log(f"メール送信完了 → {SEND_TO}")
    except Exception as e:
        log(f"メール送信失敗: {e}")



def shift_reminder_section() -> str:
    """毎月24日のみ assift シフト自動割当リマインドを返す。それ以外は空文字。"""
    now = datetime.now(JST)
    if now.day != 24:
        return ""
    next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
    nm_str = f"{next_month.year}年{next_month.month}月"
    return (
        "\n## 💡 【重要】シフト自動割当リマインド\n"
        f"本日17:00に{nm_str}分のシフト自動割当（assift_automator.py）を実行します。\n"
        f"assiftで{nm_str}分のURLを発行し、`config/shift-urls.md` の **{nm_str}** セクションに追記してください。\n"
        "追記フォーマット:\n"
        f"```\n## {nm_str}\n\n| 物件 | URL |\n|------|-----|\n"
        "| 竹屋旅籠 | https://assift.com/share/XXXXXXXX |\n"
        "| 登竜庵   | https://assift.com/share/YYYYYYYY |\n```\n"
    )


def _pending_shifts_section() -> str:
    """shift_pending.json の未登録・要手動対応シフトをブリーフィングに表示する。"""
    if load_pending is None:
        return ""
    try:
        pending = load_pending()
    except Exception:
        return ""

    items = pending.get("assignments", [])
    actionable = [a for a in items if a.get("status") in ("未登録", "要手動対応")]
    if not actionable:
        return "\n### シフト待ち（assift）\n  なし"

    lines = [f"\n### シフト待ち（assift）: {len(actionable)} 件"]
    for a in actionable:
        status = a.get("status", "")
        reason = f" ※{a['reason']}" if a.get("reason") else ""
        lines.append(
            f"  - [{status}] {a.get('date')} {a.get('property')} {a.get('guest','')}{reason}"
        )
    return "\n".join(lines)


# ── メイン ────────────────────────────────────────────────────────
def main():
    reauth      = "--reauth"     in sys.argv
    log_path    = setup_log()
    now_str     = datetime.now(JST).strftime("%Y-%m-%d %H:%M")

    log(f"=== 朝のブリーフィング開始 {now_str} ===")

    # g.kamifor@gmail.com 認証（Gmail + Calendar）
    log("Google認証中（g.kamifor@gmail.com）...")
    creds_gkami = get_google_creds(reauth=reauth)
    gmail_sv    = build("gmail",    "v1", credentials=creds_gkami)
    cal_gkami   = build("calendar", "v3", credentials=creds_gkami)
    log("g.kamifor 認証完了")

    # データ収集
    log("Gmail取得中（g.kamifor）...")
    g_text = gmail_section(gmail_sv)

    log("カレンダー取得中（g.kamifor）...")
    c_text = calendar_section(cal_gkami)

    log("Airbnb予約メール取得中（g.kamifor）...")
    a_text = airbnb_section(gmail_sv)

    # Airbnb予約を shift_pending.json にキュー（Playwright なし）
    if sync_airbnb_to_pending is not None:
        try:
            new_count, _ = sync_airbnb_to_pending(gmail_sv)
            if new_count:
                log(f"新規Airbnb予約 {new_count} 件をシフトキューに追加")
        except Exception as e:
            log(f"shift_pending 同期失敗（スキップ）: {e}")

    shift_pending_text = _pending_shifts_section()
    raw = f"{g_text}\n\n{c_text}\n\n{a_text}\n\n{shift_pending_text}"

    # Claude要約
    log("Claude要約中...")
    summary = summarize(raw)

    # 24日リマインド
    shift_reminder = shift_reminder_section()

    # 出力組み立て
    sep    = "=" * 60
    output = (
        f"{sep}\n"
        f"朝のブリーフィング  {now_str}\n"
        f"{sep}\n"
        + (shift_reminder if shift_reminder else "")
        + f"\n## 【今日のアクション】\n{summary}\n"
        f"\n{sep}\n"
        f"{raw}\n"
        f"{sep}\n"
        f"ログ: {log_path}\n"
    )

    print(output)

    # メール送信
    send_mail(f"朝のブリーフィング {now_str}", output, gmail_sv)

    log("=== 完了 ===\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
content_draft.py - ブログ記事自動生成 → WordPress下書き保存

フロー:
  1. Xの直近7日分の投稿を取得（X API or キャッシュ）
  2. blog_style.md の文体ガイドを読み込む
  3. 火・土曜日のみ Claudeでテーマ選定 → 記事生成（約2000字）
  4. Context/content_draft/YYYY-MM-DD.md に保存
  5. WordPress REST API で下書き保存（同日同タイトル重複スキップ）
  6. Context/content_pending.json に「未確認」として記録

環境変数（.env または GitHub Secrets）:
  ANTHROPIC_API_KEY    - 必須
  WP_URL / WP_BASE_URL - WordPress URL
  WP_USERNAME / WP_USER
  WP_APP_PASSWORD
  X_BEARER_TOKEN       - 任意（未設定時はキャッシュファイルを使用）
"""

import json
import os
import sys
from base64 import b64encode
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import anthropic
import requests
from dotenv import load_dotenv

# ── パス定義 ──────────────────────────────────────────────────────
REPO_DIR        = Path(__file__).parent
HOME            = Path.home()
load_dotenv(HOME / ".env")
load_dotenv(REPO_DIR / ".env")

CONTEXT_DIR     = HOME / "Context"
DAILY_MEMO_DIR  = CONTEXT_DIR / "daily_memo"
DRAFT_DIR       = CONTEXT_DIR / "content_draft"
PENDING_FILE    = CONTEXT_DIR / "content_pending.json"
BLOG_STYLE_FILE = REPO_DIR / "config" / "blog_style_summary.md"
X_CACHE_FILE    = REPO_DIR / "data" / "x_posts_cache.json"

X_USERNAME      = "yonetomo113"

# ローカル変数名とGitHub Secrets名の両方に対応
# WP_BASE_URL は "https://example.com/wp-json/wp/v2" 形式を想定（wp_buffer_integration 準拠）
# WP_URL は "https://example.com" 形式（ローカル .env 用）
_wp_raw = (os.environ.get("WP_BASE_URL") or os.environ.get("WP_URL", "")).rstrip("/")
# サイトルートURLを抽出し、httpはhttpsに昇格
WP_SITE_URL = _wp_raw.replace("/wp-json/wp/v2", "").replace("http://", "https://", 1)
WP_USERNAME     = os.environ.get("WP_USER") or os.environ.get("WP_USERNAME", "")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

JST = timezone(timedelta(hours=9))
# ─────────────────────────────────────────────────────────────────


def log(msg: str):
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")


def is_post_day(d: date) -> bool:
    return d.weekday() in (1, 5)  # 火=1, 土=5


# ── X投稿取得 ─────────────────────────────────────────────────────

def _within_7days(created_at: str) -> bool:
    if not created_at:
        return True
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - dt <= timedelta(days=7)
    except ValueError:
        return True


def _fetch_x_api(bearer: str) -> list[str]:
    headers = {"Authorization": f"Bearer {bearer}"}
    try:
        r = requests.get(
            f"https://api.twitter.com/2/users/by/username/{X_USERNAME}",
            headers=headers,
            timeout=10,
        )
        r.raise_for_status()
        user_id = r.json()["data"]["id"]

        start_time = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = requests.get(
            f"https://api.twitter.com/2/users/{user_id}/tweets",
            headers=headers,
            params={"max_results": 20, "start_time": start_time, "tweet.fields": "created_at,text"},
            timeout=10,
        )
        r.raise_for_status()
        tweets = r.json().get("data", [])

        X_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        X_CACHE_FILE.write_text(
            json.dumps(
                {"posts": tweets, "cached_at": datetime.now(JST).isoformat()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        log(f"  X API: {len(tweets)}件取得・キャッシュ更新")
        return [t["text"] for t in tweets]
    except Exception as e:
        log(f"  X API エラー: {e}")
        return []


def fetch_x_posts() -> list[str]:
    bearer = os.environ.get("X_BEARER_TOKEN")
    if bearer:
        posts = _fetch_x_api(bearer)
        if posts:
            return posts
        log("  X API失敗 → キャッシュにフォールバック")

    if X_CACHE_FILE.exists():
        try:
            data = json.loads(X_CACHE_FILE.read_text(encoding="utf-8"))
            posts = [p["text"] for p in data.get("posts", []) if _within_7days(p.get("created_at", ""))]
            log(f"  X キャッシュ読み込み: {len(posts)}件")
            return posts
        except Exception as e:
            log(f"  X キャッシュ読み込みエラー: {e}")

    log("  X投稿なし（APIキー未設定・キャッシュなし）")
    return []


# ── blog_style.md 読み込み ─────────────────────────────────────────

def load_blog_style() -> str:
    if not BLOG_STYLE_FILE.exists():
        log("  警告: blog_style.md 未生成（learn_blog_style.py を実行してください）")
        return ""
    text = BLOG_STYLE_FILE.read_text(encoding="utf-8")
    end = text.find("## 記事一覧")
    style = text[:end].strip() if end > 0 else text
    return style[:4000]


# ── daily_memo 読み込み ────────────────────────────────────────────

def read_latest_memo() -> str:
    files = sorted(DAILY_MEMO_DIR.glob("*.md")) if DAILY_MEMO_DIR.exists() else []
    if not files:
        return ""
    latest = files[-1]
    log(f"  daily_memo読み込み: {latest.name}")
    return latest.read_text(encoding="utf-8")[:1500]


# ── テーマ選定 ────────────────────────────────────────────────────

def select_theme(x_posts: list[str], memo: str, today: date) -> str:
    if not ANTHROPIC_API_KEY:
        log("エラー: ANTHROPIC_API_KEY が未設定です")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    context_parts = []
    if x_posts:
        posts_text = "\n".join(f"- {p}" for p in x_posts[:10])
        context_parts.append(f"【直近のX投稿】\n{posts_text}")
    if memo:
        context_parts.append(f"【最近の業務メモ】\n{memo[:500]}")

    if not context_parts:
        return "最近の旅館運営で気づいたこと"

    context = "\n\n".join(context_parts)

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": f"""旅館オーナー（米岡朋彦）のブログ記事テーマを1つ選んでください。

{context}

今日の日付: {today.strftime("%Y年%m月%d日")}

上記のX投稿や業務メモを起点に、ブログ記事として自然に展開できるテーマを1つ選び、
「テーマ: ○○」という形式で1行だけ返してください。
「清掃チェックリスト」のような汎用テーマは避け、具体的なエピソードや気づきを軸にしてください。"""}]
    )

    theme_line = msg.content[0].text.strip()
    theme = theme_line.split(":", 1)[-1].strip() if ":" in theme_line else theme_line
    log(f"  テーマ選定: {theme}")
    return theme


# ── 記事生成 ──────────────────────────────────────────────────────

def generate_article(x_posts: list[str], theme: str, blog_style: str, today: date) -> dict:
    if not ANTHROPIC_API_KEY:
        log("エラー: ANTHROPIC_API_KEY が未設定です")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    x_section = ""
    if x_posts:
        x_section = "【Xの直近投稿（記事の起点・雰囲気の参考）】\n" + "\n".join(f"- {p}" for p in x_posts[:8])

    prompt = f"""あなたは有限会社クロスエッジの代表・米岡朋彦（おかぴこ）本人のブログライターです。
以下の「文体ガイド」に記載された著者の文体・口癖・構成パターンを忠実に再現して、
テーマ「{theme}」でブログ記事を書いてください。

【今日の日付】{today.strftime("%Y年%m月%d日")}

{x_section}

【文体ガイド（必ず従うこと）】
{blog_style}

【執筆ルール】
- 文字数：約2000字
- 一人称：「僕」（「私」は使わない）
- テーマはX投稿を起点に展開する（Xで触れた出来事・気づきを記事の導入に使う）
- 構成：見出し（##）を2〜3個使う
- 「ｗ」「。。。」「知らんけど」「うーん」など口癖を自然に入れる
- 短文と長文を交互に混ぜてリズムに緩急をつける
- 広島・大竹・竹屋旅籠・登竜庵への言及を自然に入れる
- SEOを意識したタイトルにする

【出力形式】
1行目: TITLE: （タイトル）
空行
本文（Markdown形式）"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    lines = raw.split("\n")
    title = ""
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("TITLE:"):
            title = line.replace("TITLE:", "").strip()
            body_start = i + 1
            break

    if not title:
        title = f"{theme}【{today.strftime('%Y年%m月%d日')}】"
        body_start = 0

    body = "\n".join(lines[body_start:]).strip()
    return {"title": title, "body": body, "theme": theme}


# ── WP重複チェック ────────────────────────────────────────────────

def check_wp_duplicate(title: str, today: date) -> bool:
    if not WP_SITE_URL or not WP_USERNAME or not WP_APP_PASSWORD:
        return False
    token = b64encode(f"{WP_USERNAME}:{WP_APP_PASSWORD}".encode()).decode()
    try:
        resp = requests.get(
            f"{WP_SITE_URL}/",
            headers={"Authorization": f"Basic {token}"},
            params={
                "rest_route": "/wp/v2/posts",
                "status": "draft",
                "per_page": 20,
                "after": f"{today.isoformat()}T00:00:00",
            },
            timeout=10,
        )
        resp.raise_for_status()
        existing = [p["title"]["rendered"] for p in resp.json()]
        if title in existing:
            log(f"  スキップ: 同タイトルの下書きが既に存在 → 「{title}」")
            return True
        return False
    except Exception as e:
        log(f"  WP重複チェックエラー（無視して続行）: {e}")
        return False


# ── ファイル保存 ──────────────────────────────────────────────────

def save_draft(article: dict, today: date) -> Path:
    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    filename = DRAFT_DIR / f"{today.isoformat()}.md"
    content = (
        f"# {article['title']}\n\n"
        f"> テーマ: {article['theme']} | 生成日: {today.isoformat()}\n\n"
        f"{article['body']}\n"
    )
    filename.write_text(content, encoding="utf-8")
    log(f"  保存: {filename}")
    return filename


# ── WordPress REST API ────────────────────────────────────────────

def post_to_wordpress(article: dict) -> str:
    if not WP_SITE_URL or not WP_USERNAME or not WP_APP_PASSWORD:
        log("  警告: WordPress認証情報が未設定のためスキップ")
        return ""

    token = b64encode(f"{WP_USERNAME}:{WP_APP_PASSWORD}".encode()).decode()
    headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
    payload = {"title": article["title"], "content": article["body"], "status": "draft"}

    try:
        # LiteSpeed環境では /wp-json/ ルーティングが機能しないため ?rest_route= 経由で投稿
        resp = requests.post(
            f"{WP_SITE_URL}/?rest_route=/wp/v2/posts",
            headers=headers,
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        post_id = resp.json().get("id", "")
        edit_url = f"{WP_SITE_URL}/wp-admin/post.php?post={post_id}&action=edit"
        log(f"  WP下書き保存: ID={post_id} {edit_url}")
        return edit_url
    except requests.RequestException as e:
        log(f"  WP保存エラー: {e}")
        if hasattr(e, "response") and e.response is not None:
            log(f"  レスポンス: {e.response.text[:200]}")
        return ""


# ── pending.json 管理 ─────────────────────────────────────────────

def load_pending() -> list:
    if PENDING_FILE.exists():
        with open(PENDING_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_pending(entries: list):
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    log(f"  pending保存: {PENDING_FILE}")


def add_pending(entries: list, article: dict, wp_url: str, today: date, draft_path: Path):
    entries.append({
        "date":        today.isoformat(),
        "title":       article["title"],
        "theme":       article["theme"],
        "draft_file":  str(draft_path),
        "wp_edit_url": wp_url or "",
        "status":      "未確認",
        "created_at":  datetime.now(JST).isoformat(),
    })


# ── メイン ────────────────────────────────────────────────────────

def main():
    force = "--force" in sys.argv
    today = datetime.now(JST).date()
    log(f"=== content_draft.py 開始 ({today}){' [--force]' if force else ''} ===")

    if not force and not is_post_day(today):
        weekday_name = ["月", "火", "水", "木", "金", "土", "日"][today.weekday()]
        log(f"今日は{weekday_name}曜日のため記事生成をスキップ（火・土のみ実行）")
        log("=== 終了 ===\n")
        return

    # X投稿取得
    log("X投稿取得中...")
    x_posts = fetch_x_posts()
    log(f"  取得件数: {len(x_posts)}件")

    # 文体ガイド読み込み
    log("文体ガイド読み込み中...")
    blog_style = load_blog_style()
    if blog_style:
        log(f"  blog_style.md: {len(blog_style)}字読み込み")

    # 業務メモ読み込み
    memo = read_latest_memo()

    # テーマ選定（Xネタから動的に）
    log("テーマ選定中...")
    theme = select_theme(x_posts, memo, today)

    # 生成前に重複チェック（テーマベース）
    if check_wp_duplicate(theme, today):
        log("=== スキップ（テーマ重複）===\n")
        return

    # 記事生成
    log("Claude API で記事生成中...")
    article = generate_article(x_posts, theme, blog_style, today)
    log(f"  タイトル: {article['title']}")
    log(f"  文字数: {len(article['body'])}字")

    # 生成後にタイトルで重複チェック
    if check_wp_duplicate(article["title"], today):
        log("=== スキップ（タイトル重複）===\n")
        return

    # ファイル保存
    draft_path = save_draft(article, today)

    # WordPress下書き保存
    log("WordPress に下書き保存中...")
    wp_edit_url = post_to_wordpress(article)

    # pending記録
    entries = load_pending()
    add_pending(entries, article, wp_edit_url, today, draft_path)
    save_pending(entries)

    log("=== 完了 ===")
    log(f"  記事: {draft_path.name}")
    if wp_edit_url:
        log(f"  WP編集URL: {wp_edit_url}")
    log("")


if __name__ == "__main__":
    main()

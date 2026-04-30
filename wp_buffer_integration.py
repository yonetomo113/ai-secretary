#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wp_buffer_integration.py — Claudeでブログ下書き＋Bufferコピーを生成しWordPress投稿

フロー:
  1. x_posts_cache.json から直近7日のX投稿を読み込む
  2. blog_style_summary.md から文体ガイドを読み込む
  3. Claudeでテーマを動的選定（X投稿を起点に）
  4. Claudeでブログ本文（約1000字）とBuffer用SNSコピーを生成
  5. WordPress REST API でブログを下書き保存
  6. Buffer用コピーを buffer_copy.txt に書き出す

使い方:
  python3 wp_buffer_integration.py                      # X投稿からテーマ自動選定
  TOPIC="民泊清掃のコツ" python3 wp_buffer_integration.py  # テーマ指定

前提条件:
  - 環境変数 WP_USER, WP_APP_PASSWORD, WP_BASE_URL, ANTHROPIC_API_KEY が設定済み
  - data/x_posts_cache.json（fetch_x_posts.py で生成）があると多様なテーマが選定される
"""

import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from llm_client import call_llm

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────
JST = timezone(timedelta(hours=9))
REPO_DIR = Path(__file__).parent

WP_USER           = os.environ["WP_USER"]
WP_APP_PASSWORD   = os.environ["WP_APP_PASSWORD"]
WP_BASE_URL       = os.environ["WP_BASE_URL"].rstrip("/")
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

CLAUDE_MODEL    = "claude-haiku-4-5-20251001"
X_CACHE_FILE    = REPO_DIR / "data" / "x_posts_cache.json"
BLOG_STYLE_FILE = REPO_DIR / "config" / "blog_style_summary.md"
BUFFER_OUTPUT   = REPO_DIR / "buffer_copy.txt"


def log(msg: str) -> None:
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")


# ─────────────────────────────────────────────
# X投稿読み込み
# ─────────────────────────────────────────────

def _within_7days(created_at: str) -> bool:
    if not created_at:
        return True
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - dt <= timedelta(days=7)
    except ValueError:
        return True


def load_x_posts() -> list[str]:
    if not X_CACHE_FILE.exists():
        log("  x_posts_cache.json が存在しません（Xデータなしで続行）")
        return []
    try:
        data = json.loads(X_CACHE_FILE.read_text(encoding="utf-8"))
        posts = [
            p["text"] for p in data.get("posts", [])
            if _within_7days(p.get("created_at", ""))
        ]
        log(f"  Xキャッシュ読み込み: {len(posts)}件（更新: {data.get('updated_at', '不明')}）")
        return posts
    except Exception as e:
        log(f"  Xキャッシュ読み込みエラー: {e}")
        return []


# ─────────────────────────────────────────────
# 文体ガイド読み込み
# ─────────────────────────────────────────────

def load_blog_style() -> str:
    if not BLOG_STYLE_FILE.exists():
        log("  blog_style_summary.md が見つかりません（文体ガイドなしで生成）")
        return ""
    text = BLOG_STYLE_FILE.read_text(encoding="utf-8")
    end = text.find("## 記事一覧")
    style = text[:end].strip() if end > 0 else text
    trimmed = style[:3000]
    log(f"  blog_style読み込み: {len(trimmed)}字")
    return trimmed


# ─────────────────────────────────────────────
# テーマ動的選定
# ─────────────────────────────────────────────

def select_theme(x_posts: list[str], today: datetime) -> str:
    if not x_posts:
        fallback = f"旅館・民泊運営の現場レポート（{today.strftime('%Y年%m月%d日')}）"
        log(f"  X投稿なし → フォールバックテーマ: {fallback}")
        return fallback

    posts_text = "\n".join(f"- {p}" for p in x_posts[:10])

    theme_line = call_llm(
        messages=[{"role": "user", "content": f"""旅館オーナー（米岡朋彦）のブログ記事テーマを1つ選んでください。

【直近のX投稿】
{posts_text}

今日の日付: {today.strftime("%Y年%m月%d日")}

上記のX投稿を起点に、ブログ記事として自然に展開できる具体的なテーマを1つ選び、
「テーマ: ○○」という形式で1行だけ返してください。
「清掃チェックリスト」のような汎用テーマは避け、エピソードや気づきを軸にしてください。"""}],
        max_tokens=150,
        anthropic_model=CLAUDE_MODEL,
    ).strip()
    theme = theme_line.split(":", 1)[-1].strip() if ":" in theme_line else theme_line
    log(f"  テーマ選定: {theme}")
    return theme


# ─────────────────────────────────────────────
# Claude 生成
# ─────────────────────────────────────────────

def _extract_section(text: str, start_marker: str, end_marker: str | None) -> str:
    start = text.find(start_marker)
    if start == -1:
        return ""
    start += len(start_marker)
    if end_marker:
        end = text.find(end_marker, start)
        return text[start:end] if end != -1 else text[start:]
    return text[start:]


def generate_content(theme: str, x_posts: list[str], blog_style: str) -> tuple[str, str, str]:
    """(タイトル, ブログ本文, Bufferコピー) を返す。"""
    x_section = ""
    if x_posts:
        x_section = (
            "【直近のX投稿（記事の起点・雰囲気の参考）】\n"
            + "\n".join(f"- {p}" for p in x_posts[:8])
        )

    style_section = ""
    if blog_style:
        style_section = f"\n【文体ガイド（必ず従うこと）】\n{blog_style}"

    prompt = f"""あなたは有限会社クロスエッジの代表・米岡朋彦（おかぴこ）本人のブログライターです。
テーマ「{theme}」でWordPressブログ記事を日本語で1000字程度で書いてください。

{x_section}

{style_section}

【執筆ルール】
- 一人称は「僕」（「私」は使わない）
- 広島・大竹・竹屋旅籠・登竜庵への言及を自然に入れる
- X投稿がある場合はその出来事・気づきを導入に使う
- 「ｗ」「知らんけど」「うーん」などの口癖を自然に入れる
- 短文と長文を交互に混ぜてリズムに緩急をつける

【出力フォーマット】
---BLOG---
TITLE: （SEOを意識したタイトル）

（ブログ本文1000字程度）
---BUFFER---
（X/Twitter用SNSコピーを140字以内。ハッシュタグ2〜3個含む）
"""

    text: str = call_llm(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
        anthropic_model=CLAUDE_MODEL,
    )
    blog_raw    = _extract_section(text, "---BLOG---",   "---BUFFER---")
    buffer_part = _extract_section(text, "---BUFFER---", None)

    if not blog_raw:
        raise RuntimeError(f"Claudeレスポンスからブログ本文を抽出できませんでした:\n{text[:300]}")

    # TITLE: 行をタイトルとして分離
    title = theme
    body_lines = []
    for line in blog_raw.strip().splitlines():
        if line.startswith("TITLE:") and title == theme:
            title = line.replace("TITLE:", "").strip()
        else:
            body_lines.append(line)
    body = "\n".join(body_lines).strip()

    return title, body, buffer_part.strip()


# ─────────────────────────────────────────────
# WordPress 投稿
# ─────────────────────────────────────────────

def post_to_wordpress(title: str, content: str) -> str:
    """WordPressに下書き投稿して管理画面編集URLを返す。"""
    token = base64.b64encode(f"{WP_USER}:{WP_APP_PASSWORD}".encode()).decode()
    headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}
    payload = {"title": title, "content": content, "status": "draft"}

    # LiteSpeed環境では /wp-json/ ルーティングが機能しないため ?rest_route= 経由で投稿
    site_url = WP_BASE_URL.replace("/wp-json/wp/v2", "")
    resp = requests.post(
        f"{site_url}/?rest_route=/wp/v2/posts",
        headers=headers,
        json=payload,
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"WordPress投稿エラー: {resp.status_code} {resp.text[:200]}")

    post_id: int = resp.json()["id"]
    return f"{site_url}/wp-admin/post.php?post={post_id}&action=edit"


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────

def main() -> None:
    today = datetime.now(JST)
    log(f"=== wp_buffer_integration.py 開始 {today.strftime('%Y-%m-%d %H:%M')} ===")

    log("X投稿読み込み中...")
    x_posts = load_x_posts()

    log("文体ガイド読み込み中...")
    blog_style = load_blog_style()

    # TOPIC環境変数があれば優先、なければX投稿から動的選定
    if os.environ.get("TOPIC"):
        theme = os.environ["TOPIC"]
        log(f"テーマ（環境変数）: {theme}")
    else:
        log("テーマ選定中（X投稿から）...")
        theme = select_theme(x_posts, today)

    log(f"コンテンツ生成中（テーマ: {theme}）...")
    title, blog_content, buffer_copy = generate_content(theme, x_posts, blog_style)
    log(f"  タイトル: {title}")
    log(f"  ブログ本文: {len(blog_content)}字 / Bufferコピー: {len(buffer_copy)}字")

    log("WordPress に下書き保存中...")
    edit_url = post_to_wordpress(title, blog_content)
    log(f"  投稿完了: {edit_url}")

    BUFFER_OUTPUT.write_text(buffer_copy, encoding="utf-8")
    log(f"  Bufferコピー保存: {BUFFER_OUTPUT}")

    print("\n" + "=" * 50)
    print(f"タイトル: {title}")
    print(f"下書きURL: {edit_url}")
    print(f"Bufferコピー:\n{buffer_copy}")
    print("=" * 50)
    log("=== 完了 ===\n")


if __name__ == "__main__":
    try:
        main()
    except KeyError as e:
        print(f"ERROR: 環境変数 {e} が未設定です", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

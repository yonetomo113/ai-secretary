#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wp_buffer_integration.py — Geminiでブログ下書き＋Bufferコピーを生成しWordPress投稿

フロー:
  1. 環境変数 TOPIC（またはデフォルトトピック）を取得
  2. Gemini API でブログ本文（約1000字）とBuffer用SNSコピーを生成
  3. WordPress REST API でブログを下書き保存
  4. Buffer用コピーを buffer_copy.txt に書き出す

使い方:
  TOPIC="民泊清掃のコツ" python3 wp_buffer_integration.py
  python3 wp_buffer_integration.py  # デフォルトトピック使用

前提条件:
  - 環境変数 WP_USER, WP_APP_PASSWORD, WP_BASE_URL, GEMINI_API_KEY が設定済み
  - WP_BASE_URL 例: https://example.com/wp-json/wp/v2

注意事項:
  - WordPress投稿は status="draft"（下書き）で保存。公開は手動で行う
  - Gemini API 呼び出し失敗時は RuntimeError を送出してスクリプトを終了する
  - buffer_copy.txt は毎回上書きされる
"""

import base64
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────
JST = timezone(timedelta(hours=9))

WP_USER         = os.environ["WP_USER"]
WP_APP_PASSWORD = os.environ["WP_APP_PASSWORD"]
WP_BASE_URL     = os.environ["WP_BASE_URL"].rstrip("/")
GEMINI_API_KEY  = os.environ["GEMINI_API_KEY"]

DEFAULT_TOPIC = "広島の民泊・旅館運営で役立つ清掃チェックリスト"
GEMINI_MODEL  = "gemini-2.0-flash"
GEMINI_URL    = (
    f"https://generativelanguage.googleapis.com/v1beta/models"
    f"/{GEMINI_MODEL}:generateContent"
)

BUFFER_OUTPUT = Path(__file__).parent / "buffer_copy.txt"


def log(msg: str) -> None:
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")


# ─────────────────────────────────────────────
# Gemini 生成
# ─────────────────────────────────────────────
def generate_content(topic: str) -> tuple[str, str]:
    """ブログ本文（約1000字）とBuffer用SNSコピーを返す。"""
    prompt = f"""あなたは民泊・旅館運営の専門家ブロガーです。
以下のトピックについて、WordPressブログ記事の本文を日本語で1000字程度で書いてください。
読者は民泊オーナーや宿泊施設経営者です。

トピック: {topic}

【出力フォーマット】
---BLOG---
（ここにブログ本文を1000字程度）
---BUFFER---
（ここにX/Twitter用SNSコピーを140字以内。ハッシュタグ2〜3個含む）
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1500},
    }

    resp = requests.post(
        GEMINI_URL,
        params={"key": GEMINI_API_KEY},
        json=payload,
        timeout=60,
    )
    if not resp.ok:
        raise RuntimeError(f"Gemini API エラー: {resp.status_code} {resp.text[:200]}")

    text: str = resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    blog_part   = _extract_section(text, "---BLOG---",   "---BUFFER---")
    buffer_part = _extract_section(text, "---BUFFER---", None)

    if not blog_part:
        raise RuntimeError(f"Gemini レスポンスからブログ本文を抽出できませんでした:\n{text[:300]}")

    return blog_part.strip(), buffer_part.strip()


def _extract_section(text: str, start_marker: str, end_marker: str | None) -> str:
    start = text.find(start_marker)
    if start == -1:
        return ""
    start += len(start_marker)
    if end_marker:
        end = text.find(end_marker, start)
        return text[start:end] if end != -1 else text[start:]
    return text[start:]


# ─────────────────────────────────────────────
# WordPress 投稿
# ─────────────────────────────────────────────
def post_to_wordpress(title: str, content: str) -> str:
    """WordPressに下書き投稿して管理画面編集URLを返す。"""
    token = base64.b64encode(f"{WP_USER}:{WP_APP_PASSWORD}".encode()).decode()
    headers = {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "title":   title,
        "content": content,
        "status":  "draft",
    }

    resp = requests.post(
        f"{WP_BASE_URL}/posts",
        headers=headers,
        json=payload,
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"WordPress投稿エラー: {resp.status_code} {resp.text[:200]}")

    post_id: int = resp.json()["id"]
    site_url = WP_BASE_URL.replace("/wp-json/wp/v2", "")
    return f"{site_url}/wp-admin/post.php?post={post_id}&action=edit"


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────
def main() -> None:
    topic = os.environ.get("TOPIC", DEFAULT_TOPIC)
    log(f"トピック: {topic}")

    log("Gemini でコンテンツ生成中...")
    blog_content, buffer_copy = generate_content(topic)
    log(f"ブログ本文: {len(blog_content)}字 / Bufferコピー: {len(buffer_copy)}字")

    title = f"【下書き】{topic}｜{datetime.now(JST).strftime('%Y年%m月%d日')}"

    log("WordPress に下書き保存中...")
    edit_url = post_to_wordpress(title, blog_content)
    log(f"投稿完了: {edit_url}")

    BUFFER_OUTPUT.write_text(buffer_copy, encoding="utf-8")
    log(f"Bufferコピー保存: {BUFFER_OUTPUT}")

    print("\n" + "=" * 50)
    print(f"下書きURL: {edit_url}")
    print(f"Bufferコピー:\n{buffer_copy}")
    print("=" * 50)


if __name__ == "__main__":
    try:
        main()
    except KeyError as e:
        print(f"ERROR: 環境変数 {e} が未設定です", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""
tools/fetch_x_posts.py - @gkamifor の X 投稿を収集して data/x_posts_cache.json に保存

収集期間:
  火曜実行: 前金曜 13:01 〜 月曜 24:00 (=火曜 00:00)
  土曜実行: 月曜 24:01 (=火曜 00:01) 〜 金曜 13:00
  --force : 直近7日間

必要な環境変数 (GitHub Secrets):
  X_EMAIL     - X ログインメール (ログインウォールが出た場合)
  X_PASSWORD  - X パスワード
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

REPO_DIR   = Path(__file__).parent.parent
CACHE_FILE = REPO_DIR / "data" / "x_posts_cache.json"
X_HANDLE   = "gkamifor"
JST        = timezone(timedelta(hours=9))


# ── 日付レンジ計算 ─────────────────────────────────────────────────

def get_date_range(today: datetime, force: bool) -> tuple[datetime, datetime]:
    weekday = today.weekday()  # 0=月 1=火 5=土

    if force and weekday not in (1, 5):
        start = (today - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=JST)
        end   = today.replace(tzinfo=JST)
        return start, end

    if weekday == 1:  # 火曜 → 前金曜13:01〜月曜24:00(=火曜00:00)
        prev_fri = today - timedelta(days=4)
        start = prev_fri.replace(hour=13, minute=1, second=0, microsecond=0, tzinfo=JST)
        end   = today.replace(  hour=0,  minute=0, second=0, microsecond=0, tzinfo=JST)
    elif weekday == 5:  # 土曜 → 火曜00:01〜金曜13:00
        prev_tue = today - timedelta(days=4)
        prev_fri = today - timedelta(days=1)
        start = prev_tue.replace(hour=0,  minute=1, second=0, microsecond=0, tzinfo=JST)
        end   = prev_fri.replace(hour=13, minute=0, second=0, microsecond=0, tzinfo=JST)
    else:
        print(f"[SKIP] 今日は火・土以外（weekday={weekday}）。--force を付けて実行してください。")
        sys.exit(0)

    return start, end


# ── X ログイン ────────────────────────────────────────────────────

def login_x(page) -> bool:
    email    = os.environ.get("X_EMAIL", "")
    password = os.environ.get("X_PASSWORD", "")
    if not email or not password:
        print("  X_EMAIL / X_PASSWORD が未設定のためログインをスキップ")
        return False

    print("  X ログイン中...")
    page.goto("https://x.com/i/flow/login", wait_until="networkidle", timeout=20000)

    page.wait_for_selector('input[autocomplete="username"]', timeout=10000)
    page.fill('input[autocomplete="username"]', email)
    page.locator('[role="button"]:has-text("Next"), [role="button"]:has-text("次へ")').first.click()
    page.wait_for_timeout(2000)

    # 途中でユーザー名確認が入る場合
    if page.query_selector('[data-testid="ocfEnterTextTextInput"]'):
        page.fill('[data-testid="ocfEnterTextTextInput"]', X_HANDLE)
        page.locator('[role="button"]:has-text("Next"), [role="button"]:has-text("次へ")').first.click()
        page.wait_for_timeout(2000)

    page.wait_for_selector('input[name="password"]', timeout=10000)
    page.fill('input[name="password"]', password)
    page.locator('[data-testid="LoginForm_Login_Button"]').click()

    try:
        page.wait_for_url("**/home", timeout=15000)
        print("  ログイン成功")
        return True
    except PWTimeout:
        print("  ログイン失敗（タイムアウト）")
        return False


# ── スクレイピング ────────────────────────────────────────────────

def scrape_posts(start_dt: datetime, end_dt: datetime) -> list[dict]:
    posts = []
    seen  = set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx  = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()

        print(f"  プロフィールページ取得中: https://x.com/{X_HANDLE}")
        try:
            page.goto(f"https://x.com/{X_HANDLE}", wait_until="networkidle", timeout=30000)
        except PWTimeout:
            print("  ページ読み込みタイムアウト")
            browser.close()
            return []

        # ログインウォール検出
        if "login" in page.url or "signin" in page.url:
            if not login_x(page):
                browser.close()
                return []
            page.goto(f"https://x.com/{X_HANDLE}", wait_until="networkidle", timeout=20000)

        # ツイート収集ループ
        stop = False
        for _ in range(40):
            articles = page.query_selector_all('article[data-testid="tweet"]')

            for art in articles:
                try:
                    time_el = art.query_selector("time")
                    text_el = art.query_selector('[data-testid="tweetText"]')
                    if not time_el or not text_el:
                        continue

                    dt_str = time_el.get_attribute("datetime")
                    text   = text_el.inner_text().strip()
                    key    = dt_str + text[:40]
                    if key in seen:
                        continue
                    seen.add(key)

                    dt_jst = datetime.fromisoformat(dt_str.replace("Z", "+00:00")).astimezone(JST)

                    if dt_jst < start_dt:
                        stop = True
                        break
                    if dt_jst <= end_dt:
                        posts.append({"text": text, "created_at": dt_str})
                except Exception:
                    continue

            if stop:
                break

            prev_h = page.evaluate("document.body.scrollHeight")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2500)
            if page.evaluate("document.body.scrollHeight") == prev_h:
                break  # スクロール限界

        browser.close()

    print(f"  収集完了: {len(posts)} 件")
    return posts


# ── キャッシュ保存 ────────────────────────────────────────────────

def save_cache(posts: list[dict]):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"posts": posts, "updated_at": datetime.now(JST).isoformat()}
    CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  キャッシュ保存: {len(posts)} 件 → {CACHE_FILE}")


# ── メイン ────────────────────────────────────────────────────────

def main():
    force = "--force" in sys.argv
    today = datetime.now(JST).replace(tzinfo=None)  # naive で weekday 計算
    print(f"=== fetch_x_posts.py 開始 ({today.strftime('%Y-%m-%d %H:%M')}){' [--force]' if force else ''} ===")

    start_dt, end_dt = get_date_range(today, force)
    print(f"  収集期間: {start_dt.strftime('%m/%d %H:%M')} 〜 {end_dt.strftime('%m/%d %H:%M')} JST")

    posts = scrape_posts(start_dt, end_dt)
    save_cache(posts)
    print("=== 完了 ===\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assift_automator.py — Airbnb予約メール → assift シフト自動登録

フロー:
  1. Gmail (xedgeltd@gmail.com) から未処理のAirbnb予約メールを取得
  2. チェックアウト日 = 清掃シフト日として抽出
  3. config/shift-urls.md から物件→assift URL を取得
  4. Playwright で assift シフト提出フォームを操作
  5. 結果を Context/shift_pending.json に記録

使い方:
  python3 assift_automator.py           # 通常実行
  python3 assift_automator.py --dry-run # フォーム送信せずに確認のみ（JSON記録もしない）
  python3 assift_automator.py --debug   # ブラウザを表示して操作確認

前提条件:
  - ~/.config/ai-secretary/credentials.json（Google Cloud OAuthクライアント）
  - 初回実行時にブラウザが開き xedgeltd@gmail.com でのOAuth認証が必要
  - config/shift-urls.md に物件ごとの assift URL が登録済みであること

注意事項:
  - 英語件名（"Reservation confirmed" 等）も処理対象。AIRBNB_QUERY に英語キーワードを含む
  - 物件名キーワード（PROPERTY_KEYWORDS）が本文・件名どちらにも見つからない場合は
    shift_pending.json に status="要手動対応" で記録してスキップする
  - config/shift-urls.md に該当物件・月のURLが未登録の場合（get_assift_url が None を返す）、
    shift_pending.json に status="要手動対応", reason="assift URL 未設定" で記録し、
    assift への自動登録はスキップする。その場合は shift-urls.md に対象月セクションを追記して
    手動で assift に登録すること
  - 新しい物件を追加するには PROPERTY_KEYWORDS dict にエントリを追加し、
    config/shift-urls.md にも URL を追記すること
"""

import argparse
import base64
import json
import pickle
import re
import sys
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
CONFIG_DIR     = Path.home() / ".config" / "ai-secretary"
CREDENTIALS    = CONFIG_DIR / "credentials.json"
TOKEN_XEDGE    = CONFIG_DIR / "token_xedge.pickle"   # xedgeltd@gmail.com
SHIFT_URLS_MD  = BASE_DIR / "config" / "shift-urls.md"
SHIFT_PENDING  = Path.home() / "Context" / "shift_pending.json"
SCREENSHOT_DIR = BASE_DIR / "logs" / "assift_screenshots"

JST = timezone(timedelta(hours=9))

SCOPES_XEDGE = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# Airbnb予約メール検索クエリ（xedgeltd@gmail.com）
# 日本語件名（ご予約）と英語件名（confirmed/reservation）の両方をカバー。
# 本文パースで対象物件に絞る。「ご予約」のみにすると英語通知がスキップされるため注意。
AIRBNB_QUERY = "from:airbnb.com (ご予約 OR confirmed OR reservation) newer_than:30d"

# 物件名キーワード → shift-urls.md のテーブル見出しにマッチさせる
PROPERTY_KEYWORDS: dict[str, list[str]] = {
    "竹屋旅籠": ["竹屋", "takeyaryoko", "takeyaryokan"],
    "登竜庵": ["登竜庵", "touryu", "toryuan"],
}


def log(msg: str):
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")


# ─────────────────────────────────────────────
# Google OAuth（xedgeltd 用）
# ─────────────────────────────────────────────
def _get_gmail_service_xedge():
    creds = None
    if TOKEN_XEDGE.exists():
        with open(TOKEN_XEDGE, "rb") as f:
            creds = pickle.load(f)

    if creds and creds.valid:
        return build("gmail", "v1", credentials=creds)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_XEDGE, "wb") as f:
                pickle.dump(creds, f)
            return build("gmail", "v1", credentials=creds)
        except Exception as e:
            log(f"xedge トークンリフレッシュ失敗: {e}")

    if not CREDENTIALS.exists():
        log(f"ERROR: credentials.json が見つかりません: {CREDENTIALS}")
        return None

    print("\n" + "=" * 60)
    print("【xedgeltd@gmail.com の Google認証が必要です】")
    print("ブラウザが開いたら xedgeltd@gmail.com でログインしてください。")
    print("=" * 60 + "\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS), SCOPES_XEDGE)
    creds = flow.run_local_server(port=0, login_hint="xedgeltd@gmail.com", prompt="consent")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_XEDGE, "wb") as f:
        pickle.dump(creds, f)
    return build("gmail", "v1", credentials=creds)


# ─────────────────────────────────────────────
# shift-urls.md パーサー
# ─────────────────────────────────────────────
def load_shift_urls() -> dict[str, dict[str, str]]:
    """
    shift-urls.md のテーブルを {YYYY-MM: {物件名: URL}} 形式で返す。

    対応フォーマット:
      ## 2026年4月       →  {"2026-04": {"竹屋旅籠": "...", "登竜庵": "..."}}
      ## 現在のURL（2026年4月）  も同様にパース

    月ヘッダーがない行のテーブルは "latest" キーに格納する（後方互換）。
    """
    if not SHIFT_URLS_MD.exists():
        log(f"WARNING: {SHIFT_URLS_MD} が見つかりません")
        return {}

    result: dict[str, dict[str, str]] = {}
    current_key = "latest"

    for line in SHIFT_URLS_MD.read_text(encoding="utf-8").splitlines():
        # ## 見出しから年月を抽出
        h = re.match(r"^##\s+.*?(\d{4})年(\d{1,2})月", line)
        if h:
            current_key = f"{h.group(1)}-{int(h.group(2)):02d}"
            continue

        # テーブル行
        m = re.match(r"\|\s*(.+?)\s*\|\s*(https://assift\.com/\S+?)\s*\|", line)
        if m:
            result.setdefault(current_key, {})[m.group(1)] = m.group(2)

    return result


def get_assift_url(shift_urls: dict[str, dict[str, str]], property_name: str, target_date: date) -> str | None:
    """
    対象日の年月に対応する assift URL を返す。
    該当月のエントリがなければ 'latest' キーにフォールバック。
    """
    ym = target_date.strftime("%Y-%m")
    url = shift_urls.get(ym, {}).get(property_name)
    if not url:
        url = shift_urls.get("latest", {}).get(property_name)
    if not url:
        # 月に関わらず最初に見つかったエントリを使う（旧フォーマット対応）
        for month_urls in shift_urls.values():
            if property_name in month_urls:
                url = month_urls[property_name]
                break
    return url


def detect_property(text: str) -> str | None:
    """メール本文から物件名を推定する"""
    for prop, keywords in PROPERTY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return prop
    return None


# ─────────────────────────────────────────────
# Airbnb メール解析
# ─────────────────────────────────────────────
def _decode_body(payload: dict) -> str:
    """Gmail API メッセージペイロードから本文テキストを取得する"""
    def _extract(part: dict) -> str:
        mime = part.get("mimeType", "")
        if mime in ("text/plain", "text/html"):
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        for sub in part.get("parts", []):
            result = _extract(sub)
            if result:
                return result
        return ""

    return _extract(payload)


def parse_airbnb_reservation(body: str, subject: str) -> dict | None:
    """
    Airbnb予約メール本文から予約情報を抽出する。
    返り値: {"property": str, "checkin": date, "checkout": date, "guest": str, "confirmation": str}
    """
    # 確認番号
    conf_m = re.search(r"(?:予約番号|Confirmation code|確認コード)[:\s：]*([A-Z0-9]{8,12})", body)
    confirmation = conf_m.group(1) if conf_m else ""

    # ゲスト名
    guest_m = re.search(r"(?:ゲスト名?|Guest)[:\s：]*([^\n\r,、]{2,30})", body)
    guest = guest_m.group(1).strip() if guest_m else ""

    # 件名と本文を結合して日付抽出（件名に日付が入るケースに対応）
    search_text = subject + "\n" + body
    found_dates: list[date] = []
    current_year = datetime.now(JST).year

    # 2026年4月15日
    for m in re.finditer(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", search_text):
        try:
            found_dates.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass

    # 4月18日～20日（年なし・同月範囲）例: "4月18日～20日のご予約"
    if len(found_dates) < 2:
        for m in re.finditer(r"(\d{1,2})月(\d{1,2})日[〜～\-](\d{1,2})日", search_text):
            try:
                mo, d1, d2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
                found_dates.append(date(current_year, mo, d1))
                found_dates.append(date(current_year, mo, d2))
            except ValueError:
                pass

    # 4月18日～5月2日（年なし・月跨ぎ）
    if len(found_dates) < 2:
        for m in re.finditer(r"(\d{1,2})月(\d{1,2})日[〜～\-](\d{1,2})月(\d{1,2})日", search_text):
            try:
                mo1, d1 = int(m.group(1)), int(m.group(2))
                mo2, d2 = int(m.group(3)), int(m.group(4))
                found_dates.append(date(current_year, mo1, d1))
                found_dates.append(date(current_year, mo2, d2))
            except ValueError:
                pass

    # 2026-04-15 / 2026/04/15
    if len(found_dates) < 2:
        for m in re.finditer(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", search_text):
            try:
                found_dates.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
            except ValueError:
                pass

    # Apr 15, 2026
    if len(found_dates) < 2:
        month_map = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        for m in re.finditer(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})", search_text):
            mo_str = m.group(1)[:3].lower()
            if mo_str in month_map:
                try:
                    found_dates.append(date(int(m.group(3)), month_map[mo_str], int(m.group(2))))
                except ValueError:
                    pass

    if len(found_dates) < 2:
        log(f"日付抽出失敗: found={found_dates} subject={subject[:60]}")
        return None

    found_dates.sort()
    checkin, checkout = found_dates[0], found_dates[1]

    # 物件検出
    property_name = detect_property(body + subject)
    if not property_name:
        log(f"物件検出失敗（キーワード不一致）: subject={subject}")
        return None

    return {
        "property": property_name,
        "checkin": checkin,
        "checkout": checkout,
        "guest": guest,
        "confirmation": confirmation,
    }


def fetch_unprocessed_reservations(service, processed_ids: list[str]) -> list[dict]:
    """未処理のAirbnb予約メールを取得してパースする"""
    results = []
    try:
        resp = service.users().messages().list(
            userId="me", q=AIRBNB_QUERY, maxResults=20
        ).execute()
        messages = resp.get("messages", [])
        log(f"Airbnbメール: {len(messages)}件取得")
    except Exception as e:
        log(f"Gmail取得エラー: {e}")
        return results

    for msg_ref in messages:
        msg_id = msg_ref["id"]
        if msg_id in processed_ids:
            continue
        try:
            msg = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()
            headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
            subject = headers.get("Subject", "")
            body = _decode_body(msg["payload"])
            reservation = parse_airbnb_reservation(body, subject)
            if reservation:
                reservation["gmail_id"] = msg_id
                results.append(reservation)
                log(
                    f"予約検出: {reservation['property']} "
                    f"{reservation['checkin']}〜{reservation['checkout']} "
                    f"{reservation['guest']}"
                )
            else:
                log(f"スキップ（物件/日付不一致）: {subject[:60]}")
        except Exception as e:
            log(f"メール取得エラー (id={msg_id}): {e}")

    return results


# ─────────────────────────────────────────────
# shift_pending.json 管理
# ─────────────────────────────────────────────
def load_pending() -> dict:
    if SHIFT_PENDING.exists():
        with open(SHIFT_PENDING, encoding="utf-8") as f:
            return json.load(f)
    return {"processed": [], "assignments": []}


def save_pending(data: dict):
    SHIFT_PENDING.parent.mkdir(parents=True, exist_ok=True)
    with open(SHIFT_PENDING, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


# ─────────────────────────────────────────────
# Playwright: assift フォーム操作
# ─────────────────────────────────────────────
def _screenshot(page, name: str):
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(JST).strftime("%Y%m%d_%H%M%S")
    path = SCREENSHOT_DIR / f"{ts}_{name}.png"
    page.screenshot(path=str(path))
    log(f"スクリーンショット: {path}")


def submit_assift_shift(
    assift_url: str,
    shift_date: date,
    reservation: dict,
    dry_run: bool = False,
    debug: bool = False,
) -> bool:
    """
    assift シフト提出フォームを操作して清掃シフトを登録する。

    assift.com/share/{code} の想定構造:
    - 月カレンダー形式で日付セルをクリック → 選択状態に
    - 送信ボタンで確定

    NOTE: assift のUI仕様は変わる可能性がある。
    --debug オプションでブラウザを表示して実際の構造を確認してから
    _click_day() のセレクタを調整すること。
    """
    log(f"assift 操作開始: url={assift_url} date={shift_date} dry_run={dry_run}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not debug, slow_mo=300 if debug else 0)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="ja-JP",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            log(f"ページ読み込み: {assift_url}")
            page.goto(assift_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            _screenshot(page, "01_loaded")

            _verify_month(page, shift_date)
            _screenshot(page, "02_month_verified")

            clicked = _click_day(page, shift_date)
            if not clicked:
                log(f"WARNING: {shift_date} のセルが見つかりませんでした")
                _screenshot(page, "03_day_not_found")
                browser.close()
                return False
            _screenshot(page, "03_day_clicked")
            log(f"日付クリック完了: {shift_date}")

            if dry_run:
                log(f"[DRY-RUN] 送信をスキップしました: {shift_date}")
                _screenshot(page, "04_dryrun_skip")
                browser.close()
                return True

            # assift はセルクリックで即時登録（送信ボタン不要）
            # モーダルが出る場合のみ _submit_form が機能する
            _submit_form(page)
            _screenshot(page, "04_done")
            log(f"送信完了: {reservation['property']} {shift_date}")

            browser.close()
            return True

        except PlaywrightTimeout as e:
            _screenshot(page, "error_timeout")
            log(f"タイムアウト: {e}")
            browser.close()
            return False
        except Exception as e:
            _screenshot(page, "error_unexpected")
            log(f"予期しないエラー: {e}")
            browser.close()
            return False


def _verify_month(page, target_date: date) -> bool:
    """
    assift の share URL は月固定表示（月ナビなし）。
    ヘッダーの「M/1 〜 M/末」テキストで対象月が一致するか確認する。
    不一致の場合は警告を出すだけで続行（shift-urls.md の更新を促す）。
    """
    try:
        header = page.locator(".calendar-header").first
        if header.count() == 0:
            return True  # ヘッダー不明の場合は続行
        txt = header.inner_text(timeout=3000)
        # "4/1 〜 4/30" のような形式
        m = re.search(r"(\d{1,2})/1", txt)
        if m:
            page_month = int(m.group(1))
            if page_month != target_date.month:
                log(
                    f"WARNING: assift URL の表示月({page_month}月) と "
                    f"対象日({target_date.month}月)が不一致。"
                    "config/shift-urls.md のURLを翌月分に更新してください。"
                )
                return False
    except Exception:
        pass
    return True


def _click_day(page, target_date: date) -> bool:
    """
    assift カレンダーの構造:
      table.share-calendar > thead > tr.date-area > th > p.day  （日付ヘッダー）
      table.share-calendar > tbody > tr.staff > td.pattern-name （クリック対象）

    p.day のテキストで列インデックスを特定し、tbody の同列 td をクリックする。
    """
    day_str = str(target_date.day)

    # ── 1. thead の th から対象日の列インデックスを特定 ──
    ths = page.locator("table.share-calendar thead tr.date-area th")
    col_idx = -1
    th_count = ths.count()
    for i in range(th_count):
        th = ths.nth(i)
        day_p = th.locator("p.day")
        if day_p.count() == 0:
            continue
        try:
            if day_p.inner_text(timeout=1000).strip() == day_str:
                col_idx = i + 1  # :nth-child は 1-indexed
                break
        except Exception:
            continue

    if col_idx < 0:
        log(f"列インデックス特定失敗: day={day_str} (thead th数={th_count})")
        return False

    log(f"列インデックス: {col_idx} (day={day_str})")

    # ── 2. tbody の staff 行で同列の td.pattern-name をクリック ──
    td = page.locator(
        f"table.share-calendar tbody tr.staff td.pattern-name:nth-child({col_idx})"
    ).first
    if td.count() > 0:
        td.scroll_into_view_if_needed()
        td.click(timeout=5000)
        page.wait_for_timeout(800)
        return True

    # フォールバック: staff 行の全 td から nth-child で選択
    td_fallback = page.locator(
        f"table.share-calendar tbody tr.staff td:nth-child({col_idx})"
    ).first
    if td_fallback.count() > 0:
        td_fallback.scroll_into_view_if_needed()
        td_fallback.click(timeout=5000)
        page.wait_for_timeout(800)
        return True

    log(f"td クリック失敗: nth-child({col_idx})")
    return False


def _submit_form(page) -> bool:
    """
    日付セルクリック後に表示されるモーダル・ドロップダウンの確定ボタンを押す。
    assift はセル選択後にパターン選択モーダルが出る場合がある。
    """
    page.wait_for_timeout(1000)

    submit_selectors = [
        # assift 独自ボタン（実際のDOMに合わせて更新可）
        ".modal button:has-text('保存')",
        ".modal button:has-text('登録')",
        ".modal button:has-text('確定')",
        ".modal button[type='submit']",
        # 汎用
        "button:has-text('保存')",
        "button:has-text('登録')",
        "button:has-text('確定')",
        "button:has-text('送信')",
        "button[type='submit']",
        "input[type='submit']",
    ]
    for sel in submit_selectors:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible():
                btn.click(timeout=3000)
                page.wait_for_timeout(1500)
                return True
        except Exception:
            continue
    return False


# ─────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────
def run(dry_run: bool = False, debug: bool = False):
    log("=== assift_automator 開始 ===")

    service = _get_gmail_service_xedge()
    if service is None:
        log("ERROR: Gmail サービス取得失敗")
        sys.exit(1)

    shift_urls = load_shift_urls()
    if not shift_urls:
        log("ERROR: shift-urls.md から URL を取得できませんでした")
        sys.exit(1)
    log(f"シフトURL読込: {list(shift_urls.keys())} 月分")

    pending = load_pending()
    processed_ids: list[str] = pending.get("processed", [])

    reservations = fetch_unprocessed_reservations(service, processed_ids)
    if not reservations:
        log("未処理の予約メールなし")
        return

    for res in reservations:
        prop_name = res["property"]
        checkout  = res["checkout"]   # 清掃日 = チェックアウト日
        url = get_assift_url(shift_urls, prop_name, checkout)

        if not url:
            log(f"WARNING: {prop_name} ({checkout.strftime('%Y-%m')}) の assift URL が未設定 → shift-urls.md に {checkout.year}年{checkout.month}月セクションを追記してください")
            pending["assignments"].append({
                "date": str(checkout),
                "property": prop_name,
                "guest": res.get("guest", ""),
                "confirmation": res.get("confirmation", ""),
                "status": "要手動対応",
                "reason": "assift URL 未設定",
            })
            save_pending(pending)
            continue

        success = submit_assift_shift(
            assift_url=url,
            shift_date=checkout,
            reservation=res,
            dry_run=dry_run,
            debug=debug,
        )

        pending["assignments"].append({
            "date": str(checkout),
            "property": prop_name,
            "guest": res.get("guest", ""),
            "confirmation": res.get("confirmation", ""),
            "checkin": str(res["checkin"]),
            "gmail_id": res.get("gmail_id", ""),
            "status": "完了" if success else "要手動対応",
            "registered_at": datetime.now(JST).isoformat(),
            "dry_run": dry_run,
        })

        if success and not dry_run:
            processed_ids.append(res.get("gmail_id", ""))

    pending["processed"] = processed_ids
    save_pending(pending)

    completed = [a for a in pending["assignments"] if a["status"] == "完了"]
    manual    = [a for a in pending["assignments"] if a["status"] == "要手動対応"]
    log(f"=== 完了: 登録{len(completed)}件 / 要手動対応{len(manual)}件 ===")
    for m in manual:
        log(
            f"【要対応】{m['date']} {m['property']} {m.get('guest', '')} "
            f"— {m.get('reason', '手動でassiftに登録してください')}"
        )


def main():
    parser = argparse.ArgumentParser(description="Airbnb予約メール → assift シフト自動登録")
    parser.add_argument("--dry-run", action="store_true", help="フォーム送信せず確認のみ")
    parser.add_argument("--debug",   action="store_true", help="ブラウザを表示して操作確認")
    args = parser.parse_args()
    run(dry_run=args.dry_run, debug=args.debug)


if __name__ == "__main__":
    main()

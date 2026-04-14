"""
日次レポート生成モジュール
カブさん口調でテキストファイルに出力する。
"""

import os
from datetime import datetime
from config import SYMBOL_NAMES, REPORT_DIR
from rules import FLAG_BUY, FLAG_SELL, FLAG_WATCH, FLAG_WAIT, FLAG_NONE


FLAG_LABELS = {
    FLAG_BUY:   "買い推奨",
    FLAG_SELL:  "売り・空売り推奨",
    FLAG_WATCH: "静観推奨",
    FLAG_WAIT:  "様子見",
    FLAG_NONE:  "判定なし",
}

FLAG_EMOJIS = {
    FLAG_BUY:   "▲",
    FLAG_SELL:  "▼",
    FLAG_WATCH: "─",
    FLAG_WAIT:  "◎",
    FLAG_NONE:  "  ",
}


def build_report(results: list[dict], date_str=None) -> str:
    """
    results 形式:
    [
      {
        "symbol": "7011.T",
        "final_flag": "BUY",
        "rules": [{"rule": int, "flag": str, "reason": str}, ...],
        "patterns": [{"name": str, "signal": str, "description": str}, ...]
      },
      ...
    ]
    """
    today = date_str or datetime.now().strftime("%Y年%m月%d日")
    now_str = datetime.now().strftime("%H:%M")

    lines = []
    lines.append("=" * 60)
    lines.append(f"  カブさん 日次レポート  {today}  {now_str}")
    lines.append("=" * 60)
    lines.append("")
    lines.append("社長！本日の大引け報告です。")
    lines.append("")

    # グループ化
    groups = {FLAG_BUY: [], FLAG_SELL: [], FLAG_WATCH: [], FLAG_WAIT: [], FLAG_NONE: []}
    for r in results:
        groups[r["final_flag"]].append(r)

    # ---- 買い推奨 --------------------------------------------------------
    if groups[FLAG_BUY]:
        lines.append("【買い推奨銘柄】")
        for r in groups[FLAG_BUY]:
            name = SYMBOL_NAMES.get(r["symbol"], r["symbol"])
            lines.append(f"  ▲ {name}（{r['symbol']}）")
            for rule in r["rules"]:
                if rule["flag"] == FLAG_BUY:
                    lines.append(f"      ルール{rule['rule']}: {rule['reason']}")
            for p in r["patterns"]:
                if p["signal"] == "BUY":
                    lines.append(f"      パターン: {p['name']}")
                    lines.append(f"        → {p['description']}")
        lines.append("")

    # ---- 売り・空売り推奨 ------------------------------------------------
    if groups[FLAG_SELL]:
        lines.append("【売り・空売り推奨銘柄】")
        for r in groups[FLAG_SELL]:
            name = SYMBOL_NAMES.get(r["symbol"], r["symbol"])
            lines.append(f"  ▼ {name}（{r['symbol']}）")
            for rule in r["rules"]:
                if rule["flag"] == FLAG_SELL:
                    lines.append(f"      ルール{rule['rule']}: {rule['reason']}")
            for p in r["patterns"]:
                if p["signal"] == "SELL":
                    lines.append(f"      パターン: {p['name']}")
                    lines.append(f"        → {p['description']}")
        lines.append("")

    # ---- 静観 ------------------------------------------------------------
    if groups[FLAG_WATCH]:
        lines.append("【静観推奨銘柄】")
        for r in groups[FLAG_WATCH]:
            name = SYMBOL_NAMES.get(r["symbol"], r["symbol"])
            reason = r["rules"][0]["reason"] if r["rules"] else "─"
            lines.append(f"  ─ {name}（{r['symbol']}）: {reason}")
        lines.append("")

    # ---- 様子見 ----------------------------------------------------------
    if groups[FLAG_WAIT]:
        lines.append("【様子見銘柄（ブレイク待ち / 買い見送り）】")
        for r in groups[FLAG_WAIT]:
            name = SYMBOL_NAMES.get(r["symbol"], r["symbol"])
            lines.append(f"  ◎ {name}（{r['symbol']}）")
            for rule in r["rules"]:
                if rule["flag"] == FLAG_WAIT:
                    lines.append(f"      ルール{rule['rule']}: {rule['reason']}")
        lines.append("")

    # ---- 全銘柄パターンサマリー ------------------------------------------
    all_patterns = []
    for r in results:
        for p in r["patterns"]:
            name = SYMBOL_NAMES.get(r["symbol"], r["symbol"])
            all_patterns.append(f"  {name}: {p['name']}（{p['signal']}）")

    if all_patterns:
        lines.append("【検出パターン一覧】")
        lines.extend(all_patterns)
        lines.append("")

    lines.append("=" * 60)
    lines.append("以上、カブさんからのご報告でした。")
    lines.append("本日もお疲れ様でございます、社長！")
    lines.append("=" * 60)

    return "\n".join(lines)


def save_report(report_text: str) -> str:
    """レポートをファイルに保存してパスを返す"""
    os.makedirs(REPORT_DIR, exist_ok=True)
    filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    path = os.path.join(REPORT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(report_text)
    return path

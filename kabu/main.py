"""
カブさん メインエントリーポイント

使い方:
  python main.py fetch      # データ取得・保存のみ
  python main.py report     # レポート生成のみ（DBデータ使用）
  python main.py            # fetch + report を両方実行
"""

import sys
import os

# kabu/ ディレクトリを import パスに追加
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime
from config import SYMBOLS, SYMBOL_NAMES
from fetch import fetch_and_store
from db import load_prices
from rules import evaluate_rules, summarize_flags
from patterns import detect_patterns
from report import build_report, save_report, FLAG_LABELS


def run_analysis() -> list[dict]:
    """全銘柄を分析してresultsリストを返す"""
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


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    print(f"\n{'='*50}")
    print(f"  カブさん起動  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    if mode in ("fetch", "all"):
        print("【Step1】データ取得中...")
        fetch_and_store()
        print()

    if mode in ("report", "all"):
        print("【Step2/3】ルール・パターン分析中...")
        results = run_analysis()
        print()

        print("【Step4】レポート生成中...")
        report_text = build_report(results)
        path = save_report(report_text)

        print()
        print(report_text)
        print(f"\nレポート保存先: {path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
hermes_agent.py
Telegram ボット: Gemini AI 返答 + 朝ブリーフィング転送 + カブさんアラート転送

.env に必要な変数:
  TELEGRAM_BOT_TOKEN   BotFather から取得
  TELEGRAM_CHAT_ID     転送先チャット ID (数値)
  GEMINI_API_KEY       Google AI Studio から取得

使い方:
  python3 hermes_agent.py            # ボット起動（polling）
  python3 hermes_agent.py briefing   # 朝ブリーフィングを Telegram に転送
  python3 hermes_agent.py kabu       # カブさんレポートを Telegram に転送
"""

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = int(os.environ["TELEGRAM_CHAT_ID"])
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]
JST = timezone(timedelta(hours=9))

genai.configure(api_key=GEMINI_API_KEY)
_gemini = genai.GenerativeModel("gemini-2.0-flash")


# ── ハンドラ ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Hermes Agent 稼働中。メッセージを送ってください。")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """テキストメッセージを Gemini に渡して返答"""
    user_text = update.message.text
    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(
        None, lambda: _gemini.generate_content(user_text)
    )
    await update.message.reply_text(response.text[:4096])


async def cmd_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """朝ブリーフィングを実行して転送"""
    await update.message.reply_text("ブリーフィング生成中...")
    text = await _morning_briefing_text()
    for chunk in _split(text):
        await update.message.reply_text(chunk)


async def cmd_kabu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """カブさんレポートを実行して転送"""
    await update.message.reply_text("カブさん分析中...")
    text = await _kabu_report_text()
    for chunk in _split(text):
        await update.message.reply_text(chunk)


# ── 外部呼び出し用（cron・他スクリプトから） ──────────────────────────

async def send_morning_briefing() -> None:
    """朝ブリーフィングを TELEGRAM_CHAT_ID に送信"""
    text = await _morning_briefing_text()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    async with app:
        for chunk in _split(text):
            await app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=chunk)


async def send_kabu_alert() -> None:
    """カブさんアラートを TELEGRAM_CHAT_ID に送信"""
    text = await _kabu_report_text()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    async with app:
        for chunk in _split(text):
            await app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=chunk)


# ── 内部ヘルパー ──────────────────────────────────────────────────────

async def _morning_briefing_text() -> str:
    """morning_briefing.py をサブプロセス実行して stdout を返す"""
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            [sys.executable, str(BASE_DIR / "morning_briefing.py")],
            capture_output=True, text=True, timeout=120,
        ),
    )
    output = result.stdout.strip() or result.stderr.strip()
    return output or "ブリーフィング出力なし"


async def _kabu_report_text() -> str:
    """kabu モジュールを直接呼び出してレポートテキストを返す"""
    sys.path.insert(0, str(BASE_DIR / "kabu"))
    from config import SYMBOLS
    from fetch import fetch_and_store
    from db import load_prices
    from rules import evaluate_rules, summarize_flags
    from patterns import detect_patterns
    from report import build_report

    today = datetime.now(JST).strftime("%Y年%m月%d日")
    loop = asyncio.get_running_loop()

    def _run() -> str:
        fetch_and_store()
        results = []
        for symbol in SYMBOLS:
            df = load_prices(symbol, limit=60)
            if df.empty or len(df) < 5:
                continue
            results.append({
                "symbol": symbol,
                "final_flag": summarize_flags(evaluate_rules(df, symbol)),
                "rules": evaluate_rules(df, symbol),
                "patterns": detect_patterns(df),
            })
        return build_report(results, today)

    return await loop.run_in_executor(None, _run)


def _split(text: str, size: int = 4096) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


# ── エントリーポイント ─────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "briefing":
            asyncio.run(send_morning_briefing())
        elif cmd == "kabu":
            asyncio.run(send_kabu_alert())
        else:
            sys.exit(f"不明なコマンド: {cmd}  (briefing / kabu)")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("briefing", cmd_briefing))
    app.add_handler(CommandHandler("kabu", cmd_kabu))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print(f"[{datetime.now(JST):%Y-%m-%d %H:%M}] Hermes Agent 起動")
    app.run_polling()


if __name__ == "__main__":
    main()

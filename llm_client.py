#!/usr/bin/env python3
"""Ollama-first LLMクライアント（Anthropicフォールバック付き）

使い方:
    from llm_client import call_llm

    text = call_llm(
        messages=[{"role": "user", "content": "..."}],
        max_tokens=512,
        system="システムプロンプト",
        anthropic_model="claude-sonnet-4-6",   # フォールバック時のモデル
    )

優先順位: Ollama (qwen2.5:14b) → Anthropic API
"""

import json
import os
import urllib.error
import urllib.request

OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://192.168.11.31:11434")
OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
_DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
_OLLAMA_TIMEOUT = 120  # 長文生成を考慮


def call_llm(
    messages: list[dict],
    max_tokens: int = 1024,
    system: str = "",
    anthropic_model: str = _DEFAULT_ANTHROPIC_MODEL,
) -> str:
    """Ollamaで呼び出し、失敗したらAnthropicにフォールバック。"""
    try:
        return _call_ollama(messages, max_tokens, system)
    except Exception as e:
        print(f"[llm_client] Ollama失敗 ({e})、Anthropicにフォールバック", flush=True)
        return _call_anthropic(messages, max_tokens, system, anthropic_model)


def _call_ollama(messages: list[dict], max_tokens: int, system: str) -> str:
    ollama_messages: list[dict] = []
    if system:
        ollama_messages.append({"role": "system", "content": system})
    ollama_messages.extend(messages)

    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": ollama_messages,
        "max_tokens": max_tokens,
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_OLLAMA_TIMEOUT) as resp:
        data = json.loads(resp.read())

    return data["choices"][0]["message"]["content"]


def _call_anthropic(
    messages: list[dict],
    max_tokens: int,
    system: str,
    model: str,
) -> str:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY未設定かつOllamaも失敗。LLM呼び出し不可。")

    import anthropic  # 遅延インポート（Ollamaのみ環境でも動作するよう）

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = system
    msg = client.messages.create(**kwargs)
    return msg.content[0].text

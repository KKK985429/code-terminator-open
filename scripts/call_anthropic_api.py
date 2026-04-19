#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv


def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


def _build_messages_url(base_url: str) -> str:
    raw = base_url.strip().rstrip("/")
    if raw.endswith("/v1/messages"):
        return raw
    if raw.endswith("/v1"):
        return f"{raw}/messages"
    return f"{raw}/v1/messages"


def _extract_text(content: object) -> str:
    if not isinstance(content, list):
        return ""
    texts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                texts.append(text)
    return "\n".join(texts).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="调用 Anthropic Messages API（支持第三方 URL 与 Key）。")
    parser.add_argument("--env-file", default="", help="环境变量文件路径，默认 .env")
    parser.add_argument("--base-url", default="https://api.ikuncode.cc", help="第三方 Anthropic 兼容服务 URL，例如 https://api.anthropic.com")
    parser.add_argument("--api-key", default="", help="服务 API Key（优先级高于环境变量）")
    parser.add_argument("--model", default="claude-sonnet-4-6", help="模型名，如 claude-3-5-sonnet-20241022")
    parser.add_argument("--prompt", default="你好，请简短介绍你自己。", help="用户提问内容")
    parser.add_argument("--max-tokens", type=int, default=256, help="最大输出 token 数")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP 超时时间（秒）")
    parser.add_argument("--anthropic-version", default="2023-06-01", help="Anthropic-Version 请求头")
    args = parser.parse_args()

    env_file = Path(args.env_file)
    if env_file.exists():
        load_dotenv(env_file, override=False)
    else:
        print(f"[WARN] env 文件不存在：{env_file}，仅使用当前 shell 环境变量。")

    base_url = (args.base_url or os.environ.get("ANTHROPIC_BASE_URL", "")).strip()
    api_key = (args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
    model = (args.model or os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")).strip()

    missing = [name for name, value in [("base_url", base_url), ("api_key", api_key), ("model", model)] if not value]
    if missing:
        print(f"[ERROR] 缺少必要参数: {', '.join(missing)}")
        print("[HINT] 可用命令行参数传入，或设置 ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY / ANTHROPIC_MODEL")
        return 2

    url = _build_messages_url(base_url)
    payload = {
        "model": model,
        "max_tokens": args.max_tokens,
        "messages": [{"role": "user", "content": args.prompt}],
    }
    body = json.dumps(payload).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": args.anthropic_version,
    }
    request = urllib.request.Request(url=url, data=body, headers=headers, method="POST")

    print("[INFO] 准备发起 Anthropic 格式请求")
    print(f"[INFO] url={url}")
    print(f"[INFO] model={model}")
    print(f"[INFO] api_key={_mask_key(api_key)}")

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            raw = response.read()
            status = response.getcode()
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        err_body = exc.read().decode("utf-8", errors="replace")
        print(f"[FAIL] HTTP 错误，耗时 {elapsed_ms:.0f}ms, status={exc.code}")
        print(f"[FAIL] response body: {err_body}")
        return 1
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(f"[FAIL] 请求失败，耗时 {elapsed_ms:.0f}ms")
        print(f"[FAIL] 错误类型: {type(exc).__name__}")
        print(f"[FAIL] 错误信息: {exc}")
        return 1

    elapsed_ms = (time.perf_counter() - started) * 1000
    text = raw.decode("utf-8", errors="replace")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        print(f"[OK] 请求成功，耗时 {elapsed_ms:.0f}ms, status={status}")
        print("[OK] 非 JSON 响应原文：")
        print(text)
        return 0

    output_text = _extract_text(data.get("content"))
    usage = data.get("usage", {})

    print(f"[OK] 请求成功，耗时 {elapsed_ms:.0f}ms, status={status}")
    if isinstance(usage, dict):
        print(
            "[OK] token usage:",
            f"input={usage.get('input_tokens', 'n/a')}",
            f"output={usage.get('output_tokens', 'n/a')}",
        )
    if output_text:
        print(f"[OK] 模型返回:\n{output_text}")
    else:
        print("[OK] 原始响应 JSON：")
        print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

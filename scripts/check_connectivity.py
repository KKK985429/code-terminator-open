#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 OpenAI 兼容接口连通性（真实请求）。")
    parser.add_argument("--env-file", default=".env", help="环境变量文件路径，默认 .env")
    parser.add_argument("--prompt", default="请回复：pong", help="测试请求的 prompt")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP 超时时间（秒）")
    parser.add_argument("--max-tokens", type=int, default=16, help="生成 token 上限")
    args = parser.parse_args()

    env_file = Path(args.env_file)
    if env_file.exists():
        load_dotenv(env_file, override=False)
    else:
        print(f"[WARN] env 文件不存在：{env_file}，将仅使用当前 shell 环境变量。")

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
    model = (
        os.environ.get("DEFAULT_MODEL", "")
        or os.environ.get("OPENAI_MODEL", "")
    ).strip()

    missing = [name for name, val in [("OPENAI_API_KEY", api_key), ("OPENAI_BASE_URL", base_url), ("DEFAULT_MODEL", model)] if not val]
    if missing:
        print(f"[ERROR] 缺少必要环境变量: {', '.join(missing)}")
        return 2

    print("[INFO] 准备发起真实连通性请求")
    print(f"[INFO] base_url={base_url}")
    print(f"[INFO] model={model}")
    print(f"[INFO] api_key={_mask_key(api_key)}")

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=args.timeout)

    started = time.perf_counter()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": args.prompt}],
            max_tokens=args.max_tokens,
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(f"[FAIL] 请求失败，耗时 {elapsed_ms:.0f}ms")
        print(f"[FAIL] 错误类型: {type(exc).__name__}")
        print(f"[FAIL] 错误信息: {exc}")
        return 1

    elapsed_ms = (time.perf_counter() - started) * 1000
    content = ""
    if resp.choices and resp.choices[0].message:
        content = (resp.choices[0].message.content or "").strip()
    usage = getattr(resp, "usage", None)

    print(f"[OK] 连通性正常，耗时 {elapsed_ms:.0f}ms")
    if usage:
        print(
            "[OK] token usage:",
            f"prompt={getattr(usage, 'prompt_tokens', 'n/a')}",
            f"completion={getattr(usage, 'completion_tokens', 'n/a')}",
            f"total={getattr(usage, 'total_tokens', 'n/a')}",
        )
    print(f"[OK] 模型返回: {content!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

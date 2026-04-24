from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from services.shared.settings import log_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay ecommerce gateway access logs from a file or a shard directory."
    )
    parser.add_argument(
        "--input",
        default=str(log_file()),
        help="Path to a JSONL file or a directory containing JSONL shards.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:58081",
        help="Replay target base URL.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Replay at most N matching gateway access records. 0 means all.",
    )
    parser.add_argument(
        "--pace",
        choices={"off", "recorded"},
        default="off",
        help="Replay immediately or preserve recorded spacing.",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Speed multiplier when --pace=recorded. 2.0 means twice as fast.",
    )
    parser.add_argument(
        "--only-errors",
        action="store_true",
        help="Replay only gateway records with warning/error statuses.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Max concurrent in-flight replay requests when --pace=off.",
    )
    parser.add_argument(
        "--output",
        default="logs/replay-results.jsonl",
        help="Where to write replay result records.",
    )
    return parser.parse_args()


def resolve_path(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    return path


def resolve_output(path_str: str) -> Path:
    path = resolve_path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def iter_input_files(path: Path) -> Iterator[Path]:
    if path.is_file():
        yield path
        return
    if not path.exists():
        raise FileNotFoundError(path)
    manifest = path / "manifest.json"
    if manifest.exists():
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        for name in payload.get("shards", []):
            shard = path / name
            if shard.exists():
                yield shard
        return
    for candidate in sorted(path.glob("*.jsonl")):
        if candidate.name.startswith("replay-results"):
            continue
        yield candidate


def iter_gateway_records(path: Path, *, only_errors: bool) -> Iterator[dict[str, Any]]:
    for input_file in iter_input_files(path):
        with input_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("event") != "gateway_access":
                    continue
                if record.get("source") != "gateway":
                    continue
                status_code = int(record.get("status_code", 0) or 0)
                if only_errors and status_code < 400:
                    continue
                yield record


def build_url(base_url: str, record: dict[str, Any]) -> str:
    path = record.get("path", "")
    query = record.get("query", "")
    if query:
        return f"{base_url.rstrip('/')}{path}?{query}"
    return f"{base_url.rstrip('/')}{path}"


def body_and_headers(record: dict[str, Any]) -> tuple[dict[str, str], Any, bytes | None]:
    headers = {"x-replay-source": "replay-log", "x-trace-id": f"replay-{uuid.uuid4().hex}"}
    request_body = record.get("request_body")
    if request_body is None:
        return headers, None, None
    if isinstance(request_body, (dict, list)):
        headers["content-type"] = "application/json"
        return headers, request_body, None
    if isinstance(request_body, str):
        return headers, None, request_body.encode("utf-8")
    return headers, None, json.dumps(request_body, ensure_ascii=False).encode("utf-8")


def _response_body(response: httpx.Response) -> Any:
    content_type = response.headers.get("content-type", "")
    text = response.text
    if len(text) > 1000:
        text = f"{text[:1000]}...[truncated]"
    if "json" in content_type.lower():
        try:
            return response.json()
        except json.JSONDecodeError:
            return text
    return text


def _parse_timestamp(raw: Any) -> float | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


async def replay_one(
    client: httpx.AsyncClient,
    *,
    index: int,
    base_url: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    headers, json_body, raw_body = body_and_headers(record)
    started = time.perf_counter()
    response = await client.request(
        method=record.get("method", "GET"),
        url=build_url(base_url, record),
        headers=headers,
        json=json_body,
        content=raw_body,
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    result = {
        "replay_index": index,
        "timestamp": time.time(),
        "method": record.get("method"),
        "path": record.get("path"),
        "recorded_status": record.get("status_code"),
        "replayed_status": response.status_code,
        "latency_ms": latency_ms,
        "trace_id": response.headers.get("x-trace-id"),
        "response_body": _response_body(response),
    }
    print(
        f"[replay] #{index} {record.get('method')} {record.get('path')} "
        f"{record.get('status_code')} -> {response.status_code} {latency_ms:.2f}ms",
        flush=True,
    )
    return result


async def replay_records(
    records: Iterator[dict[str, Any]],
    *,
    base_url: str,
    output_path: Path,
    limit: int,
    pace: str,
    speed: float,
    workers: int,
) -> int:
    timeout = httpx.Timeout(30.0)
    completed = 0
    previous_timestamp: float | None = None
    semaphore = asyncio.Semaphore(max(1, workers))
    pending: set[asyncio.Task] = set()

    async with httpx.AsyncClient(timeout=timeout) as client:
        with output_path.open("w", encoding="utf-8") as output:
            async def submit(index: int, record: dict[str, Any]) -> None:
                async with semaphore:
                    result = await replay_one(client, index=index, base_url=base_url, record=record)
                    output.write(json.dumps(result, ensure_ascii=False) + "\n")
                    output.flush()

            for index, record in enumerate(records, start=1):
                if limit > 0 and index > limit:
                    break

                current_ts = _parse_timestamp(record.get("timestamp"))
                if pace == "recorded":
                    if previous_timestamp is not None and current_ts is not None:
                        delta = max(0.0, current_ts - previous_timestamp)
                        await asyncio.sleep(delta / max(speed, 0.001))
                    previous_timestamp = current_ts if current_ts is not None else previous_timestamp
                    await submit(index, record)
                    completed += 1
                    continue

                task = asyncio.create_task(submit(index, record))
                pending.add(task)
                if len(pending) >= max(1, workers) * 2:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    completed += len(done)

            if pending:
                done, _ = await asyncio.wait(pending)
                completed += len(done)
    return completed


async def main() -> int:
    args = parse_args()
    input_path = resolve_path(args.input)
    output_path = resolve_output(args.output)
    records = iter_gateway_records(input_path, only_errors=args.only_errors)
    total = await replay_records(
        records,
        base_url=args.base_url,
        output_path=output_path,
        limit=args.limit,
        pace=args.pace,
        speed=args.speed,
        workers=args.workers,
    )
    if total == 0:
        print("No matching gateway_access records found.", flush=True)
        return 1
    print(f"Replayed {total} request(s). Results written to {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

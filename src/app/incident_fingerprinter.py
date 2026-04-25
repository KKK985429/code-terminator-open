from __future__ import annotations

import hashlib
import re
from typing import Any


def _normalize_message(msg: str) -> str:
    """把变量部分抹掉，只留错误类型特征"""
    msg = re.sub(r"'[^']*'", "'?'", msg)  # 单引号字符串
    msg = re.sub(r'"[^"]*"', '"?"', msg)  # 双引号字符串
    msg = re.sub(r"\b\d+\b", "N", msg)  # 纯数字
    msg = re.sub(r"\s+", " ", msg).strip()
    return msg[:200]


def _extract_top_frame(traceback_text: str) -> tuple[str, str, str]:
    """从 traceback 里提取最后一个 File 帧的 file/func/line"""
    if not traceback_text:
        return "", "", ""
    # 找所有 File "..." 行
    file_pattern = re.compile(r'File "([^"]+)", line \d+, in (\w+)')
    code_pattern = re.compile(r"^\s{4}(.+)$", re.MULTILINE)

    matches = file_pattern.findall(traceback_text)
    code_lines = code_pattern.findall(traceback_text)

    if not matches:
        return "", "", ""

    last_file, last_func = matches[-1]
    # 只保留相对路径部分（去掉绝对路径前缀）
    last_file = re.sub(r"^.+site-packages/", "", last_file)
    last_file = re.sub(r"^/\S+/(?=services/)", "", last_file)

    last_code = code_lines[-1].strip() if code_lines else ""
    last_code = last_code[:100]

    return last_file, last_func, last_code


def _normalize_path(path: str) -> str:
    """把 /api/v1/orders/123 变成 /api/v1/orders/{id}"""
    if not path:
        return ""
    path = re.sub(r"/[0-9a-f]{8,}", "/{id}", path)  # UUID/hex
    path = re.sub(r"/\d+", "/{id}", path)  # 纯数字 ID
    return path.split("?")[0]  # 去掉 query string


def generate_fingerprint(log_record: dict[str, Any]) -> str:
    """
    生成错误指纹，同一类错误永远得到相同的 fingerprint hash。
    返回 16 位十六进制字符串。
    """
    service = str(log_record.get("service", "")).strip()
    exception_type = str(log_record.get("exception_type", "")).strip()
    path = _normalize_path(str(log_record.get("path", "")))
    traceback_text = str(log_record.get("traceback", ""))
    error_msg = _normalize_message(str(log_record.get("error", "")))

    top_file, top_func, top_code = _extract_top_frame(traceback_text)

    raw = "|".join(
        [
            service,
            exception_type,
            path,
            top_file,
            top_func,
            top_code,
            error_msg,
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

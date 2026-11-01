#!/usr/bin/env python3
"""以 agy 的 NDJSON stdin 傳遞完整 prompt，不受 argv 大小限制。

agy 1.1.15 起支援 stream-json 輸入；1.4.12 實測使用 event=user、
message.role/content。只採用單次終端 result；進度文字不能當成完成的 review。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def encode_prompt(prompt: str) -> bytes:
    """編碼成單一 user turn，保留 Unicode、換行與所有 diff 內容。"""
    return (
        json.dumps(
            {"event": "user", "message": {"role": "user", "content": prompt}},
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def decode_response(stdout: bytes) -> tuple[int, bytes, bytes]:
    """還原回答與退出碼；不完整輸出僅供上層隔離存檔，不可計入共識。"""
    result: dict | None = None
    partial: list[str] = []
    try:
        for line in stdout.splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if not isinstance(event, dict) or not isinstance(event.get("event"), str):
                raise ValueError("stream event 格式錯誤")
            if result is not None:
                raise ValueError("終端 result 之後仍有 event，無法確認單次 review 結果")
            if event["event"] == "result":
                result = event.get("result")
                if not isinstance(result, dict) or not isinstance(result.get("response"), str):
                    raise ValueError("result 缺少字串 response")
            elif event["event"] == "step_update":
                step = event.get("step_update")
                if isinstance(step, dict) and step.get("step_type") == "agent_response":
                    delta = step.get("text_delta", "")
                    if not isinstance(delta, str):
                        raise ValueError("text_delta 必須是字串")
                    partial.append(delta)
        if result is None:
            raise ValueError("缺少終端 result；請確認 agy 支援 stream-json（1.1.15+）並查看 stderr")
        response = result["response"].encode("utf-8")
        reason = result.get("finished_reason")
        if reason == "print_timeout":
            return (
                124,
                response,
                b"[FAIL] agy print timeout after configured budget "
                b"(finished_reason=print_timeout)\n",
            )
        if result.get("status") != "SUCCESS" or reason not in (None, ""):
            raise ValueError(
                f"review 未完成：status={result.get('status')!r}，"
                f"finished_reason={reason!r}，error={result.get('error')!r}"
            )
        if not response.strip():
            raise ValueError("終端 result 回答為空")
        return 0, response, b""
    except (ValueError, UnicodeError) as exc:
        # 有終端結果時不拼接 delta，避免同一段回答重複；否則留下已收到的片段供診斷。
        text = result.get("response") if isinstance(result, dict) else None
        if not isinstance(text, str):
            text = "".join(partial)
        return 1, text.encode("utf-8", errors="replace"), f"[FAIL] agy stream：{exc}\n".encode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    encoder = commands.add_parser("encode")
    encoder.add_argument("input_file", type=Path)
    commands.add_parser("decode")
    args = parser.parse_args()
    try:
        if args.command == "encode":
            sys.stdout.buffer.write(encode_prompt(args.input_file.read_bytes().decode("utf-8")))
            return 0
        code, response, diagnostic = decode_response(sys.stdin.buffer.read())
        sys.stdout.buffer.write(response)
        sys.stderr.buffer.write(diagnostic)
        return code
    except (OSError, UnicodeError) as exc:
        print(f"[FAIL] agy stream 輸入輸出失敗：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

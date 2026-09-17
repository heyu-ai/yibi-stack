#!/usr/bin/env python3
"""codex_version_gate.py：在 `codex exec` 之前確認 codex-cli 版本足以呼叫 pin 的 model。

pr-cycle-deep 的 Codex R1／R2 review pin `gpt-6-astra`。太舊的 CLI 不會在啟動時報錯，而是
送出請求後才收到 400「The 'gpt-6-astra' model requires a newer version of Codex」，錯誤埋在
stage log 裡，腳本只回報「輸出空白」。實測（2026-09-16）：codex-cli 0.149.0 回 400、
0.154.0-alpha.6.2 正常回應，所以門檻取 0.154.0，並把 prerelease 後綴視為同一個版本號。

用法：
  python3 codex_version_gate.py --min-version 0.154.0 --model gpt-6-astra --label "Codex R2"

退出碼：0 版本足夠；1 版本太舊（附升級指令）；2 無法判定（找不到 codex、--version 失敗或
輸出無法解析）——無法判定時一律不放行。
"""

from __future__ import annotations

import argparse
import re
import subprocess  # nosec B404
import sys

_VERSION_RE = re.compile(r"codex-cli\s+(\d+)\.(\d+)\.(\d+)")
_MIN_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
# asdf 管理的 node 需要 reshim，新版的 codex 才會出現在 shim 上
_UPGRADE_HINT = "npm install -g @openai/codex@latest（asdf 管理的 node 再跑 asdf reshim nodejs）"


def parse_codex_version(text: str) -> tuple[int, int, int] | None:
    """從 `codex --version` 的輸出取出 (major, minor, patch)；prerelease 後綴忽略。"""
    m = _VERSION_RE.search(text)
    if m is None:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def parse_min_version(raw: str) -> tuple[int, int, int]:
    """解析呼叫端給的門檻；格式錯誤是呼叫端的 bug，raise ValueError。"""
    m = _MIN_RE.match(raw)
    if m is None:
        raise ValueError(f"--min-version 必須是 X.Y.Z（收到：{raw!r}）")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _fmt(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="確認 codex-cli 版本足以呼叫 pin 的 model")
    parser.add_argument("--min-version", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--label", default="codex")
    args = parser.parse_args(argv)

    try:
        minimum = parse_min_version(args.min_version)
    except ValueError as e:
        print(f"[FAIL] {args.label}：{e}", file=sys.stderr)
        return 2

    try:
        proc = subprocess.run(  # nosec B603 B607
            ["codex", "--version"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError) as e:
        print(
            f"[FAIL] {args.label}：無法執行 codex --version（{e}），無法確認是否支援 {args.model}",
            file=sys.stderr,
        )
        return 2

    output = proc.stdout + proc.stderr
    if proc.returncode != 0:
        print(
            f"[FAIL] {args.label}：codex --version 失敗（exit {proc.returncode}），"
            f"無法確認是否支援 {args.model}。原始輸出：\n{output}",
            file=sys.stderr,
        )
        return 2

    found = parse_codex_version(output)
    if found is None:
        print(
            f"[FAIL] {args.label}：無法從 codex --version 解析版本，"
            f"無法確認是否支援 {args.model}。原始輸出：\n{output}",
            file=sys.stderr,
        )
        return 2

    if found < minimum:
        print(
            f"[FAIL] {args.label}：codex-cli {_fmt(found)} 太舊，{args.model} 需要 "
            f">= {_fmt(minimum)}（舊版會在送出請求後才回 400「requires a newer version of "
            f"Codex」）。請升級：{_UPGRADE_HINT}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

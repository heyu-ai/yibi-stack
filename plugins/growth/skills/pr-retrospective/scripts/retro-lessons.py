#!/usr/bin/env python3
"""透過 installed Mycelium 寫入，並讀回精確的 canonical lesson identity。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404
import sys


def invoke(args: list[str]) -> subprocess.CompletedProcess[str]:
    """保留真實 session cwd 與外部 CLI 的完整診斷。"""
    result = subprocess.run(  # nosec B603 B607
        ["mycelium", "lessons", *args], capture_output=True, text=True, timeout=60
    )
    sys.stderr.write(result.stderr)
    return result


def read_rows(args: list[str]) -> subprocess.CompletedProcess[str]:
    result = invoke(["rows", *args])
    if result.returncode == 2 and (
        "No such command" in result.stderr or "--key 與 --id 合計最多 200 個" in result.stderr
    ):
        print(
            "[DEGRADED] installed mycelium 版本過舊；請選擇已發布且包含 "
            "#634 無上限 lessons rows 修正的新 release tag，再手動執行："
            'uv tool install --force "yibi-stack @ '
            'git+https://github.com/heyu-ai/yibi-stack@<fixed-release-tag>". '
            "不得拆分讀回或刪減合法參數。",
            file=sys.stderr,
        )
    return result


def write_lesson(args: argparse.Namespace) -> int:
    command = [
        "add",
        "--project",
        args.project,
        "--key",
        args.key,
        "--type",
        args.type,
        "--insight",
        args.insight,
        "--confidence",
        str(args.confidence),
        "--source",
        args.source,
        "--retro-pr",
        str(args.retro_pr),
        "--retrospective-id",
        args.retrospective_id,
    ]
    if args.skill:
        command.extend(["--skill", args.skill])
    command.append("--park" if args.state == "park" else "--skip-if-exists")
    added = invoke(command)
    sys.stdout.write(added.stdout)
    if added.returncode:
        return added.returncode

    # 新增／park 的 stdout 回傳 id；冪等 skip 則在 stderr 回傳合法既有 id，
    # 不應要求既有列屬於本次 retrospective。
    identities = re.findall(r"^id=(\S+)(?:\s|$)", added.stdout, re.M)
    if not identities and args.state == "active":
        identities = re.findall(
            r"^\[INFO\] 已存在相同 key 的 lesson，依 --skip-if-exists 略過寫入（id=([^）\s]+)）$",
            added.stderr,
            re.M,
        )
    if len(identities) != 1:
        print("[FAIL] lessons add 沒有回傳唯一 lesson id；停止，不重試 --park", file=sys.stderr)
        return 1
    lesson_id = identities[0]
    canonical = read_rows(["--project", args.project, "--id", lesson_id])
    if canonical.returncode:
        return canonical.returncode
    try:
        payload = json.loads(canonical.stdout)
        rows = payload["rows"]
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError("必須精確讀回一列")
        row = rows[0]
        if not isinstance(row, dict) or any(
            row.get(name) != value
            for name, value in (
                ("id", lesson_id),
                ("project", args.project),
                ("key", args.key),
                ("type", args.type),
            )
        ):
            raise ValueError("讀回的 identity 與 lessons add 不符")
        if payload.get("missing_ids") != []:
            raise ValueError("讀回結果缺少指定 lesson id")
    except (ValueError, KeyError, TypeError) as exc:
        print(f"[FAIL] lesson 精確讀回失敗：{exc}；停止，不重試 --park", file=sys.stderr)
        return 1
    print(f"verified_id={lesson_id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="寫入一次，再以 project＋回傳 id 驗證")
    for name in ("project", "key", "type", "insight", "source", "retrospective-id"):
        add.add_argument(f"--{name}", required=True)
    add.add_argument("--confidence", type=int, required=True)
    add.add_argument("--retro-pr", type=int, required=True)
    add.add_argument("--skill", default="")
    add.add_argument("--state", choices=("active", "park"), required=True)
    rows = commands.add_parser("rows", help="單一 canonical snapshot，另診斷舊版 CLI")
    rows.add_argument("--project", required=True)
    rows.add_argument("--key", action="append", default=[])
    rows.add_argument("--id", action="append", default=[])
    args = parser.parse_args()
    try:
        if args.command == "add":
            return write_lesson(args)
        command = ["--project", args.project]
        for name in ("key", "id"):
            for value in getattr(args, name):
                command.extend([f"--{name}", value])
        result = read_rows(command)
        sys.stdout.write(result.stdout)
        return result.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[FAIL] mycelium 無法執行或逾時：{exc}；不重試 --park", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

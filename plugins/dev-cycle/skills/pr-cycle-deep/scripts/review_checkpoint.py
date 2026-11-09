#!/usr/bin/env python3
"""PR checkpoint：原子保存早期進度，resume 不得跳過 HEAD 與必要證據檢查。

state.md 使用 JSON；start 建立新 invocation，advance 僅推進早期 step，resume 唯讀。
exit 0 = 成功（stdout JSON）；exit 2 = 無法安全保存／續接；exit 3 = 無外部聲部，等待人類裁決。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from pre_review_check import ensure_review_dir, read_red_first_report

STEPS = (
    "Step 1.5",
    "Step 1.6",
    "Step 1.7",
    "Step 2",
    "Step 3",
    "Step 4",
    "Step 5",
    "Step 5a",
    "Step 5b",
    "Step 5c",
    "Step 6",
    "Step 7",
    "Step 8",
    "Step 9",
    "Step 10",
    "Step 11",
)
SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")


def command(root: Path, *args: str) -> str:
    result = subprocess.run(
        list(args), cwd=root, capture_output=True, text=True, timeout=30, check=False
    )
    if result.returncode:
        raise RuntimeError(f"{args[0]} 失敗：{result.stderr.strip()}")
    return result.stdout.strip()


def live_pr(root: Path, pr: int) -> dict[str, Any]:
    data = json.loads(
        command(root, "gh", "pr", "view", str(pr), "--json", "number,state,headRefOid,baseRefName")
    )
    if (
        not isinstance(data, dict)
        or data.get("number") != pr
        or data.get("state") != "OPEN"
        or not isinstance(data.get("headRefOid"), str)
        or not SHA.fullmatch(data["headRefOid"])
        or not isinstance(data.get("baseRefName"), str)
        or not data["baseRefName"]
    ):
        raise ValueError("PR 不為 OPEN，或 metadata 不完整")
    if command(root, "git", "rev-parse", "HEAD") != data["headRefOid"]:
        raise ValueError("checkout HEAD 與 live PR head 不符")
    return data


def load(path: Path, pr: int, live: dict[str, Any]) -> dict[str, Any]:
    state = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(state, dict)
        or state.get("schema_version") != 1
        or state.get("pr") != pr
        or state.get("head") != live["headRefOid"]
        or state.get("base") != live["baseRefName"]
        or state.get("next") not in STEPS
        or not isinstance(state.get("disputed"), list)
    ):
        raise ValueError("checkpoint PR／base／head／next／disputed 不符；不得續接未審查的 HEAD")
    return state


def save(path: Path, state: dict[str, Any]) -> None:
    fd, name = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def voice_result(
    state: dict[str, Any], source: Path, review_round: int, allow: bool
) -> dict[str, Any]:
    """只依本輪已驗證的成功／失敗結果計數；靜態 auth cache 不是成功證據。"""
    if state.get("review_round", review_round) != review_round:
        raise ValueError("voice outcomes 的 round 與本輪 checkpoint 不符")
    outcomes = json.loads(source.read_text(encoding="utf-8"))
    names = ("claude", "codex", "gemini")
    if not isinstance(outcomes, dict) or set(outcomes) != set(names):
        raise ValueError("voice outcomes 必須包含 claude、codex、gemini")
    active, failed = [], {}
    for name in names:
        item = outcomes[name]
        if not isinstance(item, dict) or item.get("status") not in (
            "success",
            "unavailable",
            "not-selected",
        ):
            raise ValueError(f"{name} status 無效")
        if item["status"] == "success":
            active.append(name)
        elif item["status"] == "unavailable":
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"{name} 失敗必須記錄原因")
            failed[name] = reason
    if "claude" not in active:
        raise ValueError("Claude R1 尚未成功，不得進入 aggregation")
    digest = hashlib.sha256(
        json.dumps([state["pr"], state["head"], review_round, outcomes], sort_keys=True).encode()
    ).hexdigest()
    approved = allow or (
        state.get("voice_digest") == digest and state.get("claude_only_approved") is True
    )
    mode = {1: "claude-only", 2: "2-voice-mob", 3: "3-voice-full-mob"}[len(active)]
    summary = f"{mode} ({len(active)}/3 voices active)"
    if len(active) == 1:
        summary += "; no cross-model family review"
    return {
        "pr": state["pr"],
        "mode": mode,
        "active_voices": active,
        "voice_failures": failed,
        "voice_head": state["head"],
        "voice_round": review_round,
        "voice_digest": digest,
        "claude_only_approved": approved and len(active) == 1,
        "voice_summary": summary,
    }


def require_voice_decision(state: dict[str, Any]) -> None:
    active = state.get("active_voices")
    if (
        not isinstance(active, list)
        or not active
        or "claude" not in active
        or any(name not in ("claude", "codex", "gemini") for name in active)
        or len(set(active)) != len(active)
    ):
        raise ValueError("本輪 active_voices 格式錯誤")
    if (
        state.get("voice_head") != state["head"]
        or state.get("voice_round") != state.get("review_round", 1)
        or not state.get("active_voices")
    ):
        raise ValueError("缺少本輪 voice outcomes；不得從 auth cache 推定 mob review")
    if state["active_voices"] == ["claude"] and state.get("claude_only_approved") is not True:
        raise ValueError("本輪沒有跨模型家族審查，必須等待使用者裁決")


def resume(root: Path, state: dict[str, Any], pr: int) -> dict[str, Any]:
    step = state["next"]
    if STEPS.index(step) >= STEPS.index("Step 2"):
        captured_head, result = read_red_first_report(root, str(pr))
    else:
        captured_head, result = None, "not-run"
    if STEPS.index(step) >= STEPS.index("Step 4"):
        require_voice_decision(state)
    if STEPS.index(step) >= STEPS.index("Step 5a"):
        unresolved = any(
            not isinstance(item, dict) or not item.get("ruling") for item in state["disputed"]
        )
        if unresolved or not (root / ".pr-review/final.md").is_file():
            step = "Step 5"
    return {
        "next": step,
        "head": state["head"],
        "red_first": result,
        "captured_head": captured_head,
        "voice_summary": state.get("voice_summary"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "advance", "resume", "voices"))
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--next", choices=STEPS[:7])
    parser.add_argument("--input", type=Path)
    parser.add_argument("--round", type=int, choices=(1, 2), default=1)
    parser.add_argument("--allow-claude-only", action="store_true")
    parser.add_argument("--read-only", action="store_true")
    args = parser.parse_args()
    try:
        root = Path(command(args.repo_root, "git", "rev-parse", "--show-toplevel"))
        if args.read_only and args.action != "voices":
            raise ValueError("--read-only 僅用於 voices，不建立 lifecycle checkpoint")
        live = (
            {"headRefOid": command(root, "git", "rev-parse", "HEAD")}
            if args.read_only
            else live_pr(root, args.pr)
        )
        path = root / ".pr-review/state.md"
        if args.read_only:
            state = {"pr": args.pr, "head": live["headRefOid"]}
        elif args.action == "start":
            ensure_review_dir(root)
            state = {
                "schema_version": 1,
                "pr": args.pr,
                "base": live["baseRefName"],
                "head": live["headRefOid"],
                "next": "Step 1.5",
                "disputed": [],
                "review_round": 1,
            }
        else:
            state = load(path, args.pr, live)
        if args.action == "voices":
            if args.input is None:
                raise ValueError("voices 必須指定 --input")
            result = voice_result(state, args.input, args.round, args.allow_claude_only)
            if not args.read_only:
                state.update(result)
                save(path, state)
            save(root / ".pr-review/voice-status.json", result)
            print(json.dumps(result, ensure_ascii=False))
            if result["mode"] == "claude-only" and not result["claude_only_approved"]:
                print(
                    "[STOP] 本輪沒有跨模型家族審查；請選擇 Claude-only、切換流程或稍後重跑",
                    file=sys.stderr,
                )
                return 3
            return 0
        if args.action == "resume":
            result = resume(root, state, args.pr)
        else:
            if args.action == "advance":
                current, target = STEPS.index(state["next"]), args.next
                if target is None:
                    raise ValueError("advance 必須指定 --next")
                distance = STEPS.index(target) - current
                if distance not in (0, 1) and not (
                    state["next"] == "Step 3" and target == "Step 5"
                ):
                    raise ValueError("不得跳過未完成的 early step")
                state["next"] = target
                resume(root, state, args.pr)
            save(path, state)
            result = state
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"[FAIL] checkpoint：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

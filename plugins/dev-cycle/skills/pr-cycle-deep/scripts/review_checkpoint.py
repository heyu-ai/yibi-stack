#!/usr/bin/env python3
"""原子 PR 審查 checkpoint；exit 2 拒絕放行，exit 3 等待人類裁決。

state.md 使用 schema_version=1 JSON，不接受舊自由格式。唯讀審查只使用
voice-attempt.json，不建立 lifecycle checkpoint。
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
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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
NAMES = ("claude", "codex", "gemini")


def command(root: Path, *args: str) -> str:
    result = subprocess.run(
        list(args), cwd=root, capture_output=True, text=True, timeout=30, check=False
    )
    if result.returncode:
        raise RuntimeError(f"{args[0]} 失敗：{result.stderr.strip()}")
    return result.stdout.strip()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(value: Any) -> str:
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())


def live_pr(root: Path, pr: int, repo: str | None) -> dict[str, Any]:
    selector = ("--repo", repo) if repo else ()
    data = json.loads(
        command(
            root,
            "gh",
            "pr",
            "view",
            str(pr),
            *selector,
            "--json",
            "number,url,state,headRefOid,baseRefName",
        )
    )
    if not isinstance(data, dict):
        raise ValueError("PR metadata 必須是 object")
    url = urlsplit(data.get("url", ""))
    parts = url.path.strip("/").split("/")
    if (
        data.get("number") != pr
        or isinstance(data.get("number"), bool)
        or data.get("state") not in ("OPEN", "MERGED", "CLOSED")
        or not isinstance(data.get("headRefOid"), str)
        or not SHA.fullmatch(data["headRefOid"])
        or not isinstance(data.get("baseRefName"), str)
        or not data["baseRefName"]
        or url.scheme != "https"
        or not url.netloc
        or url.query
        or url.fragment
        or len(parts) != 4
        or parts[2:] != ["pull", str(pr)]
        or not all(parts[:2])
        or data["url"] != f"https://{url.netloc}/{'/'.join(parts)}"
    ):
        raise ValueError("PR canonical URL／state／base／head metadata 不完整")
    canonical_repo = "/".join(parts[:2])
    if repo and repo.lower() not in (
        canonical_repo.lower(),
        f"{url.netloc}/{canonical_repo}".lower(),
    ):
        raise ValueError("--repo 與 live canonical PR URL 不符")
    data["repo"] = canonical_repo
    return data


def load(path: Path, pr: int, live: dict[str, Any], *, moved: bool = False) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(
            "checkpoint 無效；請不帶 --resume 從 start 重啟（不遷移舊自由格式）"
        ) from exc
    if (
        not isinstance(state, dict)
        or type(state.get("schema_version")) is not int
        or state["schema_version"] != 1
        or state.get("pr") != pr
        or state.get("pr_url") != live["url"]
        or state.get("repo") != live["repo"]
        or state.get("base") != live["baseRefName"]
        or state.get("next") not in STEPS
        or not isinstance(state.get("disputed"), list)
        or type(state.get("review_round")) is not int
        or state["review_round"] not in (1, 2)
        or not isinstance(state.get("head"), str)
        or not SHA.fullmatch(state["head"])
        or (not moved and live["state"] == "OPEN" and state["head"] != live["headRefOid"])
    ):
        raise ValueError(
            "checkpoint PR URL／repo／base／head／schema 不符；"
            "請不帶 --resume 重啟，或使用 post-fix 邊界"
        )
    ids = set()
    for item in state["disputed"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or not item["id"]
            or item["id"] in ids
            or not isinstance(item.get("finding"), str)
            or not item["finding"].strip()
            or item.get("ruling") not in (None, "fix", "false-positive", "accepted-risk")
        ):
            raise ValueError("disputed checkpoint 格式錯誤")
        if item.get("ruling") and (
            not isinstance(item.get("reason"), str)
            or not item["reason"].strip()
            or type(item.get("ruling_round")) is not int
            or item["ruling_round"] not in (1, 2)
            or item["ruling_round"] > state["review_round"]
        ):
            raise ValueError("human ruling 缺少 reason 或有效的 ruling_round")
        ids.add(item["id"])
    for key in ("baseline", "reviewed_head"):
        if key in state and (not isinstance(state[key], str) or not SHA.fullmatch(state[key])):
            raise ValueError(f"{key} SHA 無效")
    if live["state"] == "OPEN" and state["next"] == "Step 11":
        raise ValueError("OPEN PR 不得偽造 terminal cleanup checkpoint")
    return state


def save(path: Path, state: dict[str, Any]) -> None:
    fd, name = tempfile.mkstemp(prefix=".checkpoint-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def identity(state: dict[str, Any], phase: str) -> dict[str, Any]:
    return {
        "pr_url": state["pr_url"],
        "head": state["head"],
        "review_round": state["review_round"],
        "phase": phase,
        "attempt": state["attempts"][phase]["id"],
    }


def report_body(raw: bytes) -> bytes:
    body = (
        raw.split(b"\n", 1)[1] if raw.startswith(b"<!-- review-evidence:") and b"\n" in raw else raw
    )
    return b"\n".join(line for line in body.splitlines() if not line.startswith(b"Review scope:"))


def complete_review_body(raw: bytes, phase: str) -> bool:
    """只驗 canonical compact report 的完整欄位，不把 identity／scope 或程式碼引用當成 review。"""
    wanted = (
        ("Summary", "Findings", "Verdict")
        if phase == "r1"
        else (
            "Cross-review verdict",
            "Per-finding response",
            "New findings",
            "Withdrawals",
            "Final verdict",
        )
    )
    sections: dict[str, list[str]] = {}
    current = None
    fence: tuple[str, int] | None = None
    comment = False
    for line in raw.decode("utf-8").splitlines():
        if fence is None:
            if comment:
                closing = line.find("-->")
                if closing < 0:
                    continue
                line = line[closing + 3 :]
                comment = False
            while "<!--" in line:
                before, _, after = line.partition("<!--")
                if "-->" not in after:
                    line, comment = before, True
                    break
                line = before + after.partition("-->")[2]
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = (token[0], len(token))
            elif (
                token[0] == fence[0] and len(token) >= fence[1] and not line[marker.end() :].strip()
            ):
                fence = None
            continue
        if fence is not None:
            continue
        if line.startswith("## "):
            title = re.sub(r" \([^()\n]*\)$", "", line[3:].strip())
            if title not in wanted or title in sections or wanted[len(sections)] != title:
                return False
            sections[title] = []
            current = title
        elif current is not None:
            sections[current].append(line)
    if (
        comment
        or fence is not None
        or tuple(sections) != wanted
        or any(not "\n".join(lines).strip() for lines in sections.values())
    ):
        return False
    verdict = "\n".join(sections[wanted[-1]]).strip()
    return re.fullmatch(r"(?:-\s*)?(?:\*\*)?(?:LGTM|NEEDS_CHANGES)(?:\*\*)?", verdict) is not None


def begin_attempt(root: Path, state: dict[str, Any], phase: str) -> None:
    if phase == "r1" and state["next"] != "Step 3":
        raise ValueError("R1 begin-attempt 僅可在 Step 3")
    if phase == "r2":
        if state["next"] != "Step 4":
            raise ValueError("R2 begin-attempt 僅可在 Step 4")
        require_voices(root, state)
    old = state.setdefault("voice_decisions", {}).pop(phase, None)
    if old:
        state.setdefault("voice_history", []).append(old)
    existing = [
        digest(report_body(p.read_bytes()))
        for p in (root / ".pr-review").glob("*-r[12].md")
        if p.is_file()
    ]
    state.setdefault("attempts", {})[phase] = {"id": uuid.uuid4().hex, "prior_reports": existing}
    state.pop("final_report", None)
    state.pop("ci", None)


def voice_result(
    root: Path, state: dict[str, Any], source: Path, phase: str, allow: bool
) -> dict[str, Any]:
    if phase not in state.get("attempts", {}):
        raise ValueError("必須先 begin-attempt，再執行本次 reviewers")
    expected = identity(state, phase)
    raw = source.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("identity") != expected:
        raise ValueError("outcomes 缺少本次 canonical PR／head／pass／phase／attempt identity")
    outcomes = payload.get("outcomes")
    if not isinstance(outcomes, dict) or set(outcomes) != set(NAMES):
        raise ValueError("outcomes 必須恰含 claude、codex、gemini")
    selected = NAMES if phase == "r1" else state["voice_decisions"]["r1"]["active_voices"]
    active, failed, reports = [], {}, {}
    prior = state["attempts"][phase]["prior_reports"]
    historical = [
        body
        for record in state.get("voice_history", [])
        for body in record.get("report_bodies", [])
    ]
    bodies = []
    for name in NAMES:
        item = outcomes[name]
        if not isinstance(item, dict) or item.get("status") not in (
            "success",
            "unavailable",
            "not-selected",
        ):
            raise ValueError(f"{name} status 無效")
        if name not in selected and item["status"] != "not-selected":
            raise ValueError("R2 只能選本 pass 的 R1 active_voices")
        if phase == "r2" and name in selected and item["status"] == "not-selected":
            raise ValueError("R2 必須記錄每個 R1 active voice 的結果")
        if item["status"] == "unavailable":
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"{name} unavailable 必須記錄原始原因")
            failed[name] = reason
        if item["status"] == "success":
            path = Path(item.get("report", ""))
            if not path.is_absolute():
                path = root / path
            path = path.resolve()
            if path != (root / ".pr-review" / f"{name}-{phase}.md").resolve():
                raise ValueError("success report 必須是本 voice／phase 的 canonical compact report")
            report = path.read_bytes()
            header, _, body = report.partition(b"\n")
            prefix = b"<!-- review-evidence:"
            if not header.startswith(prefix) or not header.endswith(b" -->"):
                raise ValueError(f"{name} report 缺少 creation identity")
            evidence = json.loads(header[len(prefix) : -4])
            scope = (
                f"Review scope: {expected['pr_url']} head={expected['head']} "
                f"pass={expected['review_round']} phase={phase} attempt={expected['attempt']}"
            )
            if scope.encode() not in body.splitlines():
                raise ValueError("report 正文缺少本次 Review scope；不得只 restamp header")
            substantive = report_body(report)
            if evidence != {**expected, "voice": name} or not complete_review_body(
                substantive, phase
            ):
                raise ValueError(f"{name} report 不是本次完整 review evidence")
            body_hash = digest(substantive)
            if body_hash in prior or body_hash in historical:
                raise ValueError("舊 report 不得改標籤為本次成功；重新執行 review")
            if item.get("sha256") != digest(report):
                raise ValueError(f"{name} report fingerprint 不符")
            reports[str(path)] = digest(report)
            bodies.append(body_hash)
            active.append(name)
    if "claude" not in active:
        raise ValueError("Claude review 尚未成功，不得進入 aggregation")
    previous = state.get("voice_decisions", {}).get(phase, {})
    approved = phase == "r1" and (
        allow
        or (
            previous.get("source_digest") == digest(raw)
            and previous.get("claude_only_approved") is True
        )
    )
    mode = {1: "claude-only", 2: "2-voice-mob", 3: "3-voice-full-mob"}[len(active)]
    summary = f"{mode} ({len(active)}/3 voices active)"
    if len(active) == 1:
        summary += "; no cross-model family review"
    return {
        "identity": expected,
        "phase": phase,
        "mode": mode,
        "active_voices": active,
        "voice_failures": failed,
        "source": str(source.resolve()),
        "source_digest": digest(raw),
        "reports": reports,
        "report_bodies": bodies,
        "claude_only_approved": approved and len(active) == 1,
        "voice_summary": summary,
    }


def voice_status(state: dict[str, Any]) -> dict[str, Any]:
    decisions = state.get("voice_decisions", {})
    r1 = decisions.get("r1", {})
    return {
        "pr_url": state["pr_url"],
        "head": state["head"],
        "review_round": state["review_round"],
        "mode": r1.get("mode"),
        "active_voices": r1.get("active_voices"),
        "voice_summary": r1.get("voice_summary"),
        "voice_failures": r1.get("voice_failures", {}),
        "debate_failures": decisions.get("r2", {}).get("voice_failures", {}),
        "voice_history": state.get("voice_history", []),
        "decisions": decisions,
        "publication": fingerprint(decisions),
    }


def require_voices(root: Path, state: dict[str, Any], *, debate: bool = False) -> None:
    decisions = state.get("voice_decisions", {})
    for phase in ("r1", "r2") if debate and state.get("debate_required") else ("r1",):
        decision = decisions.get(phase)
        if not isinstance(decision, dict) or decision.get("identity") != identity(state, phase):
            raise ValueError("缺少本次 voice decision；必須重新 review")
        source = Path(decision["source"])
        if digest(source.read_bytes()) != decision["source_digest"]:
            raise ValueError("voice outcomes 已改變；舊裁決失效")
        # 同時重讀來源與驗證 bytes：cached active_voices 或手改 state
        # 都不能替缺少 creation identity 的報告提供成功證明。
        fresh = voice_result(
            root, state, source, phase, decision.get("claude_only_approved") is True
        )
        if fresh != decision:
            raise ValueError("voice decision 與目前 outcomes／reports 不符")
        if (
            phase == "r1"
            and decision["active_voices"] == ["claude"]
            and not decision["claude_only_approved"]
        ):
            raise ValueError("本輪無外部成功聲部，必須等待人類裁決")
    published = json.loads((root / ".pr-review/voice-status.json").read_text())
    if published != voice_status(state):
        raise ValueError("voice report publication 不完整或 identity 不符")


def red_evidence(root: Path, state: dict[str, Any]) -> dict[str, str]:
    captured, result = read_red_first_report(root, str(state["pr"]))
    value = {
        "captured_head": captured,
        "result": result,
        "sha256": digest((root / ".pr-review/red-first.md").read_bytes()),
    }
    if state.get("red_first") not in (None, value):
        raise ValueError("原始 red-first capture 已改變；不得將原始證據改標為新 HEAD")
    return value


def final_identity(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "pr_url": state["pr_url"],
        "head": state["head"],
        "review_round": state["review_round"],
        "voice_digest": fingerprint(state.get("voice_decisions", {})),
    }


def final_report(root: Path, state: dict[str, Any]) -> str:
    raw = (root / ".pr-review/final.md").read_bytes()
    header, _, body = raw.partition(b"\n")
    prefix = b"<!-- checkpoint-final:"
    if not header.startswith(prefix) or not header.endswith(b" -->") or not body.strip():
        raise ValueError("final.md 缺少本輪 checkpoint-final identity／正文")
    if json.loads(header[len(prefix) : -4]) != final_identity(state):
        raise ValueError("final.md PR／head／pass／voice decision 不符")
    return digest(raw)


def unresolved(state: dict[str, Any]) -> bool:
    return any(not isinstance(item, dict) or not item.get("ruling") for item in state["disputed"])


def validate(root: Path, state: dict[str, Any], *, late: bool = True) -> dict[str, Any]:
    index = STEPS.index(state["next"])
    red = red_evidence(root, state) if index >= STEPS.index("Step 2") else None
    if (
        index >= STEPS.index("Step 5a")
        and state["next"] != "Step 7"
        and (
            not state.get("baseline")
            or state.get("reviewed_head") != state["head"]
            or type(state.get("blocking")) is not bool
        )
    ):
        raise ValueError("缺少 validated baseline／reviewed_head／blocking checkpoint")
    if index >= STEPS.index("Step 9") and state.get("ship_approved_head") != state["head"]:
        raise ValueError("缺少本 HEAD 的明確 ship 授權")
    if state["next"] == "Step 10" and (
        not isinstance(state.get("ci"), dict) or state["ci"].get("head") != state["head"]
    ):
        raise ValueError("缺少本 HEAD 的 live CI completion")
    if index >= STEPS.index("Step 4"):
        reviewed = dict(state)
        if state["next"] == "Step 7":
            reviewed["head"] = state["reviewed_head"]
        require_voices(root, reviewed, debate=index >= STEPS.index("Step 5"))
    step = state["next"]
    if late and index >= STEPS.index("Step 5a") and step != "Step 7":
        try:
            valid = not unresolved(state) and final_report(root, state) == state.get("final_report")
            source = state.get("aggregation_source")
            valid = (
                valid
                and isinstance(source, str)
                and digest(Path(source).read_bytes()) == state.get("aggregation_digest")
            )
        except (OSError, ValueError):
            valid = False
        if not valid:
            step = "Step 5"
    return {
        "next": step,
        "head": state["head"],
        "reviewed_head": state.get("reviewed_head"),
        "red_first": red["result"] if red else "not-run",
        "captured_head": red["captured_head"] if red else None,
        "voice_summary": state.get("voice_decisions", {}).get("r1", {}).get("voice_summary"),
        "final_identity": final_identity(state),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "start",
            "advance",
            "resume",
            "begin-attempt",
            "voices",
            "verify-voices",
            "checkpoint",
            "ruling",
            "configure-ci",
            "baseline",
            "post-fix",
            "new-pass",
            "ci",
        ),
    )
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--repo")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--next", choices=STEPS)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--round", type=int, choices=(1, 2))
    parser.add_argument("--phase", choices=("r1", "r2"), default="r1")
    parser.add_argument("--allow-claude-only", action="store_true")
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--ship-approved", action="store_true")
    parser.add_argument("--finding")
    parser.add_argument("--ruling", choices=("fix", "false-positive", "accepted-risk"))
    parser.add_argument("--reason")
    parser.add_argument("--ci-command")
    args = parser.parse_args()
    try:
        root = Path(command(args.repo_root, "git", "rev-parse", "--show-toplevel"))
        live = live_pr(root, args.pr, args.repo)
        if args.read_only and args.action not in ("begin-attempt", "voices", "verify-voices"):
            raise ValueError("--read-only 僅用於 voice attempt／publication／verification")
        directory = root / ".pr-review"
        path = directory / ("voice-attempt.json" if args.read_only else "state.md")
        if args.action == "resume" and live["state"] != "OPEN":
            state = load(path, args.pr, live, moved=True)
            print(
                json.dumps(
                    {
                        "next": "Step 11" if live["state"] == "MERGED" else None,
                        "terminal": live["state"],
                        "no_push_no_merge": True,
                    }
                )
            )
            return 0
        if live["state"] != "OPEN":
            raise ValueError(
                f"PR 狀態為 {live['state']}；不得 start／advance／voices 或其他 lifecycle 寫入"
            )
        if command(root, "git", "rev-parse", "HEAD") != live["headRefOid"]:
            raise ValueError("checkout HEAD 與 live PR head 不符")
        if args.action == "start" and path.is_file():
            try:
                previous = json.loads(path.read_text())
            except ValueError:
                previous = {}
            if (
                isinstance(previous, dict)
                and previous.get("pr_url") == live["url"]
                and previous.get("review_round") == 2
            ):
                raise ValueError("本 PR 已進入 pass 2；start 不得重設兩輪上限")
        if args.action == "start" or (
            args.read_only and args.action == "begin-attempt" and not path.exists()
        ):
            ensure_review_dir(root)
            state = {
                "schema_version": 1,
                "pr": args.pr,
                "pr_url": live["url"],
                "repo": live["repo"],
                "base": live["baseRefName"],
                "head": live["headRefOid"],
                "next": "Step 3" if args.read_only else "Step 1.5",
                "disputed": [],
                "review_round": 1,
                "voice_decisions": {},
                "attempts": {},
            }
        else:
            state = load(path, args.pr, live, moved=args.action == "post-fix")
        if args.round is not None and args.round != state["review_round"]:
            raise ValueError("--round 與 checkpoint pass 不符；使用 new-pass，不能 restamp")
        action = args.action
        if action == "resume":
            result = validate(root, state)
        elif action == "verify-voices":
            require_voices(root, state, debate=state.get("debate_required", False))
            result = voice_status(state)
        elif action == "begin-attempt":
            if args.read_only and args.phase == "r2" and state["next"] == "Step 3":
                state["next"] = "Step 4"
                state["debate_required"] = True
            begin_attempt(root, state, args.phase)
            if args.phase == "r2":
                save(directory / "voice-status.json", voice_status(state))
            save(path, state)
            result = {
                "identity": identity(state, args.phase),
                "report_identity": {**identity(state, args.phase), "voice": "<voice>"},
            }
        elif action == "voices":
            if args.input is None or state["next"] != (
                "Step 3" if args.phase == "r1" else "Step 4"
            ):
                raise ValueError("voices 需要 --input 且只能在該 phase 的 review 邊界")
            if args.phase == "r2":
                require_voices(root, state)
            decision = voice_result(root, state, args.input, args.phase, args.allow_claude_only)
            state.setdefault("voice_decisions", {})[args.phase] = decision
            status = voice_status(state)
            # 先 report、後 checkpoint；兩次 replace 間失敗時 identity 不一致，
            # 每個 consumer 都會拒絕採用部分發布結果。
            save(directory / "voice-status.json", status)
            save(path, state)
            print(
                json.dumps(
                    {**status, "claude_only_approved": decision["claude_only_approved"]},
                    ensure_ascii=False,
                )
            )
            if (
                args.phase == "r1"
                and decision["active_voices"] == ["claude"]
                and not decision["claude_only_approved"]
            ):
                print(
                    "[STOP] 本輪沒有跨模型家族審查；請選擇 Claude-only、切換流程或稍後重跑",
                    file=sys.stderr,
                )
                return 3
            return 0
        else:
            if action != "start":
                checked = validate(root, state)
                if checked["next"] != state["next"] and action not in ("checkpoint", "ruling"):
                    raise ValueError("final／disputed 已失效；回 Step 5 重建 checkpoint")
            if action == "advance":
                target, current = args.next, state["next"]
                edges = {
                    "Step 1.5": ("Step 1.6",),
                    "Step 1.6": ("Step 1.7",),
                    "Step 1.7": ("Step 2",),
                    "Step 2": ("Step 3",),
                    "Step 3": ("Step 4", "Step 5"),
                    "Step 4": ("Step 5",),
                    "Step 5a": ("Step 5b",),
                    "Step 5b": ("Step 5c",),
                    "Step 5c": ("Step 6", "Step 8"),
                    "Step 8": ("Step 9",),
                }
                if target not in edges.get(current, ()):
                    raise ValueError(
                        "不得跳過 gate；使用 checkpoint／post-fix／new-pass／ci 的原子邊界"
                    )
                if current == "Step 3":
                    require_voices(root, state)
                    state["debate_required"] = target == "Step 4"
                if current == "Step 4":
                    require_voices(root, state, debate=True)
                if current == "Step 5c" and ((target == "Step 6") != state["blocking"]):
                    raise ValueError("next 與本輪 blocking set 不符")
                if current == "Step 8" and not args.ship_approved:
                    raise ValueError("Step 9 需要本輪明確 ship 授權 --ship-approved")
                if current == "Step 8":
                    state["ship_approved_head"] = state["head"]
                state["next"] = target
                validate(root, state)
            elif action == "baseline":
                if state["next"] != "Step 5" or state["review_round"] != 1:
                    raise ValueError("baseline 僅在 pass 1 Step 5 記錄")
                if state.get("baseline", state["head"]) != state["head"]:
                    raise ValueError("不得改寫原始 baseline")
                state["baseline"] = state["head"]
            elif action == "configure-ci":
                if (
                    state["next"] not in ("Step 5", "Step 5a", "Step 5b", "Step 5c", "Step 6")
                    or not args.ci_command
                    or not args.ci_command.strip()
                ):
                    raise ValueError("configure-ci 需要 review/fix 邊界與非空 --ci-command")
                state["ci_command"] = args.ci_command
            elif action == "checkpoint":
                if (
                    state["next"] not in ("Step 5", "Step 5a") and checked["next"] != "Step 5"
                ) or args.input is None:
                    raise ValueError("checkpoint 只能在 Step 5 使用 --input 保存本輪裁決")
                require_voices(root, state, debate=True)
                source_bytes = args.input.read_bytes()
                payload = json.loads(source_bytes)
                items = payload.get("disputed") if isinstance(payload, dict) else None
                if not isinstance(items, list) or type(payload.get("blocking")) is not bool:
                    raise ValueError("checkpoint input 必須包含 disputed array 與 blocking boolean")
                ids = set()
                for item in items:
                    if (
                        not isinstance(item, dict)
                        or not isinstance(item.get("id"), str)
                        or not item["id"]
                        or item["id"] in ids
                        or not isinstance(item.get("finding"), str)
                        or not item["finding"].strip()
                        or item.get("ruling") is not None
                    ):
                        raise ValueError(
                            "新 disputed 必須有唯一 id／finding／ruling=null；裁決使用 ruling 命令"
                        )
                    ids.add(item["id"])
                previous = {item["id"]: item for item in state["disputed"]}
                for item in items:
                    if (
                        item["id"] in previous
                        and previous[item["id"]]["finding"] != item["finding"]
                    ):
                        raise ValueError(
                            "disputed id 對應不同 finding；請使用新 id，不能繼承舊 ruling"
                        )
                merged = [previous.get(item["id"], item) for item in items]
                # 跨 pass 保留既有 dispute 與人類裁決。
                merged.extend(item for key, item in previous.items() if key not in ids)
                state["disputed"] = merged
                state["blocking"] = payload["blocking"] or any(
                    item.get("ruling") == "fix"
                    and item.get("ruling_round") == state["review_round"]
                    for item in merged
                )
                state["final_report"] = final_report(root, state)
                state["aggregation_source"] = str(args.input.resolve())
                state["aggregation_digest"] = digest(source_bytes)
                state["reviewed_head"] = state["head"]
                if not state.get("baseline"):
                    raise ValueError(
                        "先在 pass 1 Step 5 執行 baseline；不可遺失原始 review surface"
                    )
                state["next"] = "Step 5" if unresolved(state) else "Step 5a"
            elif action == "ruling":
                if (
                    state["next"] != "Step 5"
                    or not args.ruling
                    or not args.reason
                    or not args.reason.strip()
                ):
                    raise ValueError("ruling 需要 Step 5、--finding、--ruling、非空 --reason")
                if final_report(root, state) != state.get("final_report"):
                    raise ValueError("裁決前 final 已改變；先重新 checkpoint")
                matches = [item for item in state["disputed"] if item["id"] == args.finding]
                if len(matches) != 1:
                    raise ValueError("找不到唯一 disputed finding")
                matches[0].update(
                    ruling=args.ruling, reason=args.reason, ruling_round=state["review_round"]
                )
                state["blocking"] = state["blocking"] or args.ruling == "fix"
                if not unresolved(state):
                    state["next"] = "Step 5a"
            elif action == "post-fix":
                if state["next"] not in ("Step 6", "Step 9", "Step 10") or not state.get(
                    "ci_command"
                ):
                    raise ValueError("post-fix 僅可在有 ci_command 的 fix／CI 邊界")
                if live["headRefOid"] == state["head"]:
                    raise ValueError("post-fix 需要已推送的新 fix HEAD")
                command(
                    root, "git", "merge-base", "--is-ancestor", state["head"], live["headRefOid"]
                )
                state["reviewed_head"] = state["head"]
                state["head"] = live["headRefOid"]
                state["next"] = "Step 7"
                state.pop("ci", None)
            elif action == "new-pass":
                if state["next"] != "Step 7" or state["review_round"] != 1:
                    raise ValueError("只允許 pass 1 post-fix → pass 2；不存在第三輪")
                state.setdefault("voice_history", []).extend(
                    state.get("voice_decisions", {}).values()
                )
                state.update(
                    review_round=2,
                    next="Step 2",
                    voice_decisions={},
                    attempts={},
                    debate_required=False,
                )
                state.pop("final_report", None)
                state.pop("blocking", None)
                state.pop("ci", None)
            elif action == "ci":
                if state["next"] != "Step 9":
                    raise ValueError("ci 只能從 Step 9 推進")
                checks = json.loads(
                    command(root, "gh", "pr", "checks", state["pr_url"], "--json", "name,bucket")
                )
                if (
                    not isinstance(checks, list)
                    or not checks
                    or any(
                        not isinstance(item, dict)
                        or item.get("bucket") not in ("pass", "skipping")
                        or not item.get("name")
                        for item in checks
                    )
                ):
                    raise ValueError("live CI 缺漏／未全綠，不能推進 merge")
                state["ci"] = {"head": state["head"], "checks": checks}
                state["next"] = "Step 10"
            if STEPS.index(state["next"]) >= STEPS.index("Step 2"):
                state["red_first"] = red_evidence(root, state)
            save(path, state)
            result = state
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"[FAIL] checkpoint：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

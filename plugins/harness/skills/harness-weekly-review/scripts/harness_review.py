#!/usr/bin/env python3
"""Harness 每週盤點：量測 rule／hook／CI gate 的成本與有效性，產出快照、週對週比對與報告。

子命令：
  collect        讀取各資料源，輸出本週 JSON 快照（含建議清單與本週可判定的建議類型）
  diff           比對上週與本週快照，標出每條建議是 new／persisting／resolved／unmeasured
  report         把快照（與可選的上週快照）寫成繁中 markdown 報告與 lesson 候選
  write-lessons  把 lesson 候選逐行寫進 Mycelium（只在呼叫端明確要求寫入時使用）

資料源（collect／diff／report 全部唯讀，只寫 --out 等明確指定的本地檔案）：
  - <repo>/.claude/settings.json 與 settings.local.json、.claude/hooks/：hook 註冊清單
    （使用者層 ~/.claude/settings.json 不檢查）
  - ~/.claude/hook-events/<repo>-YYYY-MM.jsonl：run-hook.sh 的每次呼叫紀錄
  - ~/.claude/projects/<slug> 與 <slug>--claude-worktrees-*/ 底下的 **/*.jsonl：
    Claude Code transcript（含 plugin hook 阻擋，保留約 30 天；slug 取主 repo 路徑）
  - <repo>/.claude/rules/*.md、CLAUDE.md：每次必載的 context 成本
  - <repo>/.github/workflows/*.yml 與 gh api：CI failed run 與 failed job／step（可用 --no-ci 略過）

Exit code（collect）：
  0  完成；可能帶 notes（資訊性說明，例如秒級計時、--no-ci），不影響判定
  2  參數或環境錯誤（不是 git repo、--now 格式錯）
  3  完成，但有資料源讀取失敗、缺漏或未涵蓋觀察期（warnings）；受影響的建議類型本週不判定
Exit code（diff／report）：0 完成；2 快照不存在、格式或版本不符、--prev auto 無法讀取目錄
Exit code（write-lessons）：0 全部寫入或依 --skip-if-exists 略過；1 有任一筆失敗；
  2 lesson 檔不存在或無法讀取
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import re
import subprocess  # nosec B404
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

SNAPSHOT_VERSION = 2

# 外部指令（git／gh／mycelium）的逾時秒數；逾時視為讀取失敗，不讓排程卡住
CMD_TIMEOUT_SECONDS = 60

# hook-events 最新一筆紀錄距今超過這個天數，代表 logging 已中斷，不能當作「涵蓋觀察期」
EVENTS_MAX_STALENESS = dt.timedelta(days=2)

# runs 端點最多翻 10 頁（每頁 100 筆）；翻滿代表可能還有更早的失敗沒抓到
RUNS_MAX_PAGES = 10
RUNS_PER_PAGE = 100

# write-lessons 寫入 Mycelium 的固定欄位
LESSON_CONFIDENCE = 6
LESSON_SOURCE = "observed"
LESSON_SKILL = "harness-weekly-review"

# 保險型 hook：防範低頻高損事故，觸發次數少不代表沒用，不列入退役建議
INSURANCE_PREFIXES = ("protect-", "validate-", "pre-jira-", "guard-")

IMPERATIVE = re.compile(
    r"禁止|不要|不得|不可|一律|必須|務必|\bMUST\b|\bNEVER\b|\bnever\b|[Dd]o not"
)
BACKTICK = re.compile(r"`[^`\n]+`")
HOOK_ERR_SPLIT = re.compile(
    r"(?=\b(?:PreToolUse|PostToolUse|Stop|SubagentStop|UserPromptSubmit|SessionStart)"
    r":\S* hook error: \[)"
)
HOOK_ERR_HDR = re.compile(r"^(\w+):(\S*) hook error: \[(.*)\]: (.*)$", re.S)
SCRIPT_TOKEN = re.compile(r"[\w.-]+\.(?:sh|py|js|cmd)\b")
WRAPPERS = {"run-hook.sh", "run-hook.cmd", "sg-python.sh", "session-start.sh"}
PLUGIN_VERSION = re.compile(r"/plugins/cache/[^/]+/[^/]+/(\d+(?:\.\d+)+)/")
WEEK_LABEL = re.compile(r"(\d{4})-W(\d{2})")
SNAPSHOT_NAME = re.compile(r"snapshot-\d{4}-W\d{2}\.json")
GATE_NAME = re.compile(r"(rule-gate-|ci-check-).*\.(py|sh)$")
GATE_AFFIX = re.compile(r"^(rule-gate-|ci-check-)|\.(py|sh)$")

# workflow step 的第一個 key（`- name:`、`- run:`…）；只收這些，
# 避免把 matrix include 等清單當成 step
STEP_START = re.compile(r"^(\s*)-\s+([A-Za-z_][\w-]*)\s*:\s*(.*)$")
STEP_KEYS = {
    "name",
    "uses",
    "run",
    "id",
    "if",
    "env",
    "with",
    "shell",
    "working-directory",
    "continue-on-error",
    "timeout-minutes",
}

# 以下類型只讀 repo 內的靜態檔案，每次都能判定
STATIC_KINDS = ("gate-unwired", "rule-heavy", "rule-already-gated", "rule-mechanize-candidate")


def version_key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


# ---------------------------------------------------------------------------
# 共用
# ---------------------------------------------------------------------------


def parse_ts(value: str | None) -> dt.datetime | None:
    """解析 ISO 8601 時間戳；格式錯誤回 None，由呼叫端決定是否計入。"""
    if not value or not isinstance(value, str):
        return None
    try:
        ts = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=dt.UTC)


def iso(ts: dt.datetime) -> str:
    return ts.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_cmd(
    args: list[str], cwd: Path, timeout: int = CMD_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[str]:
    """在目標 repo 的 cwd 執行外部指令（不依賴本 script 所在目錄）。

    逾時或找不到執行檔時回傳非零 returncode 與說明，呼叫端一律當成讀取失敗處理。
    """
    try:
        return subprocess.run(  # nosec B603
            args, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args, 124, "", f"{' '.join(args[:3])} 逾時（{timeout} 秒）"
        )
    except OSError as e:
        return subprocess.CompletedProcess(args, 127, "", f"{args[0]} 無法執行：{e}")


def hook_name_from_command(cmd: str) -> str:
    """從 hook 指令字串推出 hook 名稱。

    run-hook.sh launcher 形狀取其後的 script 名；直接呼叫 script 取 basename；
    其餘（inline 指令）回傳 inline:<前 40 字>。
    """
    tokens: list[str] = [t for t in SCRIPT_TOKEN.findall(cmd or "") if t not in WRAPPERS]
    if tokens:
        return tokens[-1]
    return "inline:" + " ".join((cmd or "").split())[:40]


def is_insurance(hook: str) -> bool:
    return hook.startswith(INSURANCE_PREFIXES)


def _read_lines(path: Path, warnings: list[str], label: str) -> Iterator[str]:
    """逐行讀檔；開檔或讀取失敗記進 warnings（讀取失敗屬於量測不完整），不中斷整體量測。"""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            yield from fh
    except OSError as e:
        warnings.append(f"{label}：{path} 讀取失敗（{e}）")


# ---------------------------------------------------------------------------
# collect：hook 清單
# ---------------------------------------------------------------------------


def _is_referenced(name: str, others: dict[str, str]) -> bool:
    """name 是否被其他 hook 檔以 source／直譯器呼叫／import 的形狀引用（略過註解行）。"""
    stem = Path(name).stem
    call = re.compile(
        r"(?:\bsource\b|^\s*\.\s|\bpython3?\b|\bbash\b|\bsh\b)[^\n#]*?" + re.escape(name)
    )
    imp = re.compile(rf"^\s*(?:from\s+{re.escape(stem)}\s+import\b|import\s+{re.escape(stem)}\b)")
    for text in others.values():
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            if call.search(line) or imp.search(line):
                return True
    return False


def collect_hook_inventory(repo: Path) -> tuple[dict[str, Any], list[str], list[str]]:
    """讀 settings.json 與 settings.local.json 的 hook 註冊，找出 .claude/hooks/ 內沒註冊的 script。

    共用模組（檔名以 `_` 開頭、含 `common`、或被其他 hook source／import／直接呼叫）不是 hook，
    不列入未註冊。回傳 (inventory, warnings, notes)。
    """
    warnings: list[str] = []
    notes = [
        "hook 清單：只檢查 repo 的 settings.json 與 settings.local.json，"
        "未檢查使用者層 ~/.claude/settings.json"
    ]
    registered: dict[str, dict[str, Any]] = {}
    complete = True
    read_files = []
    for fname in ("settings.json", "settings.local.json"):
        settings = repo / ".claude" / fname
        if not settings.is_file():
            continue
        try:
            data = json.loads(settings.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            warnings.append(f"hook 清單：{settings} 讀取失敗（{e}），本週不判定未註冊與沒資料")
            complete = False
            continue
        read_files.append(fname)
        for event, groups in (data.get("hooks") or {}).items():
            for group in groups or []:
                for hook in group.get("hooks", []):
                    name = hook_name_from_command(hook.get("command", ""))
                    if name.startswith("inline:") and hook.get("statusMessage"):
                        name = "inline:" + hook["statusMessage"].rstrip(".")
                    entry = registered.setdefault(
                        name, {"events": [], "matchers": [], "async": False, "sources": []}
                    )
                    entry["events"].append(event)
                    entry["matchers"].append(group.get("matcher", ""))
                    entry["async"] = entry["async"] or bool(hook.get("async"))
                    if fname not in entry["sources"]:
                        entry["sources"].append(fname)
    hooks_dir = repo / ".claude" / "hooks"
    on_disk: list[str] = []
    texts: dict[str, str] = {}
    if hooks_dir.is_dir():
        for p in sorted(hooks_dir.iterdir()):
            if p.is_file() and p.suffix in (".sh", ".py") and p.name not in WRAPPERS:
                on_disk.append(p.name)
                try:
                    texts[p.name] = p.read_text(encoding="utf-8", errors="replace")
                except OSError as e:
                    warnings.append(f"hook 清單：{p} 讀取失敗（{e}）")
                    texts[p.name] = ""
    shared = [
        n
        for n in on_disk
        if n.startswith("_")
        or "common" in n
        or _is_referenced(n, {k: v for k, v in texts.items() if k != n})
    ]
    unregistered = [n for n in on_disk if n not in registered and n not in shared]
    return (
        {
            "registered": registered,
            "on_disk": on_disk,
            "shared_modules": shared,
            "unregistered": unregistered,
            "settings_files": read_files,
            "complete": complete,
        },
        warnings,
        notes,
    )


# ---------------------------------------------------------------------------
# collect：hook-events（run-hook.sh 紀錄）
# ---------------------------------------------------------------------------


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


def hook_event_files(events_dir: Path, repo_name: str) -> list[Path]:
    """只收 `<repo>-YYYY-MM.jsonl`；`<repo>-other-YYYY-MM.jsonl` 屬於另一個 repo，不可混入。"""
    if not events_dir.is_dir():
        return []
    pattern = re.compile(re.escape(repo_name) + r"-\d{4}-\d{2}\.jsonl")
    return sorted(p for p in events_dir.iterdir() if pattern.fullmatch(p.name) and p.is_file())


def collect_hook_events(
    events_dir: Path, repo_name: str, since: dt.datetime, now: dt.datetime
) -> tuple[dict[str, Any], list[str], list[str]]:
    """彙總 run-hook.sh 的 JSONL 紀錄：每支 hook 的呼叫次數、各 outcome 次數與耗時。

    同時判定紀錄是否涵蓋整個觀察期（covers_window）：最早一筆 <= since、觀察期內至少一筆、
    且最新一筆距 now 不超過 EVENTS_MAX_STALENESS。回傳 (events, warnings, notes)。
    """
    warnings: list[str] = []
    notes: list[str] = []
    files = hook_event_files(events_dir, repo_name)
    per_hook: dict[str, dict[str, Any]] = {}
    durations: dict[str, list[int]] = collections.defaultdict(list)
    bad_lines = 0
    earliest: dt.datetime | None = None
    latest: dt.datetime | None = None
    in_window = 0
    for f in files:
        for line in _read_lines(f, warnings, "hook-events"):
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                bad_lines += 1
                continue
            ts = parse_ts(ev.get("ts")) if isinstance(ev, dict) else None
            if ts is None:
                bad_lines += 1
                continue
            earliest = ts if earliest is None or ts < earliest else earliest
            latest = ts if latest is None or ts > latest else latest
            if ts < since or ts > now:
                continue
            in_window += 1
            name = ev.get("hook") or "?"
            s = per_hook.setdefault(
                name,
                {
                    "calls": 0,
                    "pass": 0,
                    "warn": 0,
                    "block": 0,
                    "error": 0,
                    "last_block": None,
                    "last_error": None,
                    "error_sample": None,
                },
            )
            s["calls"] += 1
            outcome = ev.get("outcome", "pass")
            if outcome in ("pass", "warn", "block", "error"):
                s[outcome] += 1
            if outcome == "block":
                s["last_block"] = max(filter(None, [s["last_block"], iso(ts)]))
            if outcome == "error":
                s["last_error"] = max(filter(None, [s["last_error"], iso(ts)]))
                s["error_sample"] = s["error_sample"] or (ev.get("msg") or "")[:200]
            durations[name].append(int(ev.get("ms") or 0))
    for name, s in per_hook.items():
        d = durations[name]
        s["total_ms"] = sum(d)
        s["p95_ms"] = _p95(d)
        s["error_rate"] = round(s["error"] / s["calls"], 4) if s["calls"] else 0.0
    all_ms = [x for d in durations.values() for x in d]
    # macOS 系統 bash 3.2 沒有 EPOCHREALTIME，run-hook.sh 只能記秒級（ms 全是 1000 的倍數）
    resolution = "second" if all_ms and all(x % 1000 == 0 for x in all_ms) else "ms"
    if resolution == "second":
        notes.append(
            "hook-events：耗時只有秒級解析度（bash 3.2），1000ms 讀值代表 0–2 秒，"
            "慢 hook 判定改用 p95 ≥ 2000ms"
        )
    if not files:
        warnings.append(
            f"hook-events：{events_dir} 找不到 {repo_name}-YYYY-MM.jsonl；run-hook.sh 尚未產生紀錄"
            "（需要含執行紀錄的 run-hook.sh 版本），執行率與耗時無法量測"
        )
    if bad_lines:
        warnings.append(f"hook-events：略過 {bad_lines} 行格式錯誤或無時間戳的紀錄")
    reasons = []
    if earliest is None or earliest > since:
        reasons.append(
            f"最早一筆是 {iso(earliest) if earliest else '（無）'}，晚於觀察期起點 {iso(since)}"
        )
    if in_window == 0:
        reasons.append("觀察期內沒有任何紀錄")
    if latest is None or now - latest > EVENTS_MAX_STALENESS:
        reasons.append(
            f"最新一筆是 {iso(latest) if latest else '（無）'}，"
            f"距今超過 {EVENTS_MAX_STALENESS.days} 天"
            "（logging 可能已中斷）"
        )
    covers = bool(files) and not reasons
    if files and reasons:
        warnings.append(
            "hook-events：紀錄未涵蓋觀察期（"
            + "；".join(reasons)
            + "）；本期不產出「沒資料」「低訊號」建議"
        )
    return (
        {
            "files": len(files),
            "hooks": per_hook,
            "resolution": resolution,
            "earliest": iso(earliest) if earliest else None,
            "latest": iso(latest) if latest else None,
            "in_window": in_window,
            "covers_window": covers,
        },
        warnings,
        notes,
    )


# ---------------------------------------------------------------------------
# collect：transcript（涵蓋 plugin hook；保留期約 30 天）
# ---------------------------------------------------------------------------


def project_slug(repo: Path) -> str:
    """Claude Code 以「路徑中每個非英數字元換成 -」命名 ~/.claude/projects 下的目錄。"""
    return re.sub(r"[^A-Za-z0-9]", "-", str(repo.resolve()))


def transcript_files(projects_dir: Path, main_repo: Path) -> list[str]:
    """收主 repo 與其 worktree（<slug>--claude-worktrees-*）的 transcript。

    同前綴的其他 repo（如 yibi-mvp-foo）排除在外。
    """
    slug = project_slug(main_repo)
    out: list[str] = []
    if not projects_dir.is_dir():
        return out
    for d in projects_dir.iterdir():
        name = d.name
        if d.is_dir() and (name == slug or name.startswith(slug + "--claude-worktrees-")):
            for root, _dirs, fnames in os.walk(d):
                out.extend(os.path.join(root, n) for n in fnames if n.endswith(".jsonl"))
    return sorted(out)


def _tool_result_text(block: dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(x.get("text", "") for x in content if isinstance(x, dict))
    return ""


def collect_transcript_blocks(
    projects_dir: Path, main_repo: Path, since: dt.datetime
) -> tuple[dict[str, Any], list[str]]:
    """從 transcript 抽出 hook 阻擋與 hook 自身錯誤事件，依 uuid 去重。"""
    warnings: list[str] = []
    files = transcript_files(projects_dir, main_repo)
    per_hook: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    min_ts: dt.datetime | None = None
    bad_lines = 0

    def note(
        name: str, kind: str, ts: dt.datetime, session: str, sample: str, cmd: str = ""
    ) -> None:
        s = per_hook.setdefault(
            name,
            {
                "block": 0,
                "error": 0,
                "no_stderr": 0,
                "sessions": set(),
                "last": None,
                "sample": None,
                "versions": {},
            },
        )
        s[kind] += 1
        s["sessions"].add(session)
        stamp = iso(ts)
        s["last"] = max(filter(None, [s["last"], stamp]))
        silent = kind == "block" and "No stderr output" in sample
        if silent:
            s["no_stderr"] += 1
        s["sample"] = s["sample"] or " ".join(sample.split())[:200]
        # plugin hook 的路徑帶版本（…/plugins/cache/<marketplace>/<plugin>/<version>/…）。
        # 修正合併後，長壽 session 仍會跑舊版快取，所以依版本分開計數。
        m = PLUGIN_VERSION.search(cmd)
        if m:
            v = s["versions"].setdefault(m.group(1), {"block": 0, "no_stderr": 0, "last": None})
            v["block"] += kind == "block"
            v["no_stderr"] += silent
            v["last"] = max(filter(None, [v["last"], stamp]))

    for f in files:
        for line in _read_lines(Path(f), warnings, "transcript"):
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                bad_lines += 1
                continue
            if not isinstance(ev, dict):
                bad_lines += 1
                continue
            ts = parse_ts(ev.get("timestamp"))
            if ts is None:
                continue
            min_ts = ts if min_ts is None or ts < min_ts else min_ts
            if ts < since:
                continue
            uid = ev.get("uuid")
            if uid:
                if uid in seen:
                    continue
                seen.add(uid)
            session = ev.get("sessionId") or "?"
            if ev.get("type") == "user":
                content = (ev.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    text = _tool_result_text(block).strip()
                    if " hook error: [" not in text[:200]:
                        continue
                    for seg in HOOK_ERR_SPLIT.split(text):
                        m = HOOK_ERR_HDR.match(seg.strip())
                        if m:
                            note(
                                hook_name_from_command(m.group(3)),
                                "block",
                                ts,
                                session,
                                m.group(4),
                                m.group(3),
                            )
            elif ev.get("type") == "attachment":
                att = ev.get("attachment") or {}
                kind = att.get("type")
                if kind == "hook_blocking_error":
                    be = att.get("blockingError") or {}
                    note(
                        hook_name_from_command(be.get("command", "")),
                        "block",
                        ts,
                        session,
                        str(be.get("blockingError", "")),
                        be.get("command", ""),
                    )
                elif kind == "hook_non_blocking_error":
                    note(
                        hook_name_from_command(att.get("command", "")),
                        "error",
                        ts,
                        session,
                        f"exit={att.get('exitCode')} {att.get('stderr') or ''}",
                        att.get("command", ""),
                    )
    for s in per_hook.values():
        s["sessions"] = len(s["sessions"])
    if not files:
        warnings.append(
            f"transcript：{projects_dir} 下找不到 {project_slug(main_repo)} 的 transcript"
        )
    if bad_lines:
        warnings.append(f"transcript：略過 {bad_lines} 行格式錯誤的紀錄")
    return {
        "files": len(files),
        "earliest": iso(min_ts) if min_ts else None,
        "hooks": per_hook,
    }, warnings


# ---------------------------------------------------------------------------
# collect：rules 成本與機械化候選
# ---------------------------------------------------------------------------


def parse_paths_frontmatter(text: str) -> list[str] | None:
    """回傳 frontmatter 的 paths 清單；沒有 frontmatter 或沒有 paths 回 None（代表每次載入）。"""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    fm = text[3:end]
    # 用 [ \t]* 而非 \s*：\s 會吃掉換行，把下一行的 `- "**"` 誤當成 inline 值
    m = re.search(r"^paths:[ \t]*(.*)$", fm, re.M)
    if not m:
        return None
    inline = m.group(1).strip()
    if inline:
        return [p.strip().strip("\"'") for p in inline.strip("[]").split(",") if p.strip()]
    items = []
    for line in fm[m.end() :].splitlines():
        mm = re.match(r"^\s*-\s*(.+)$", line)
        if not mm:
            if line.strip():
                break
            continue
        items.append(mm.group(1).strip().strip("\"'"))
    return items


def split_sections(text: str) -> list[tuple[str, int, str]]:
    """以 ## / ### 標題切段，並把「行首粗體」的段落視為子段，回傳 (標題, 起始行號, 內文)。

    有些 rule 檔以 `**V1 — ...**` 這種粗體段落當條目，只按標題切會把十幾條併成一個 2 萬字的候選。
    """
    sections: list[tuple[str, int, str]] = []
    buf: list[str] = []
    current_title, current_line = "(檔頭)", 1
    for i, line in enumerate(text.splitlines(), start=1):
        bold = re.match(r"^\*\*([^*]{3,80})\*\*", line)
        if re.match(r"^#{2,3} ", line) or bold:
            if buf:
                sections.append((current_title, current_line, "\n".join(buf)))
            title = bold.group(1).strip() if bold else line.lstrip("#").strip()
            current_title, current_line, buf = title, i, [line]
        else:
            buf.append(line)
    if buf:
        sections.append((current_title, current_line, "\n".join(buf)))
    return sections


def collect_rules(repo: Path, guard_names: set[str]) -> dict[str, Any]:
    """量測每個 rule 檔的字元數與載入範圍，並對每次必載的檔案逐段打機械化候選分數。

    分數只是排序用的啟發式：祈使句數 × min(反引號字面值數, 10)；語意判斷交給 skill 流程中的 LLM。
    段落若點名了已存在的 hook／gate script，標為 already_gated：多半可縮成一行指標。
    每個候選的 anchor 是「檔案#段落標題」（同檔同名標題依出現順序加 (2)、(3)），
    不含行號，前文增刪行不會讓週對週追蹤斷掉；行號只留作顯示用的位置。
    """
    rules_dir = repo / ".claude" / "rules"
    files: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    targets = sorted(rules_dir.glob("*.md")) if rules_dir.is_dir() else []
    for p in targets:
        text = p.read_text(encoding="utf-8")
        paths = parse_paths_frontmatter(text)
        always = paths is None or any(x in ("**", "**/*") for x in paths)
        rel = str(p.relative_to(repo))
        files.append({"file": rel, "chars": len(text), "always_loaded": always, "paths": paths})
        if not always:
            continue
        seen_titles: collections.Counter[str] = collections.Counter()
        for title, line, body in split_sections(text):
            seen_titles[title] += 1
            n = seen_titles[title]
            anchor = f"{rel}#{title}" if n == 1 else f"{rel}#{title} ({n})"
            imperative = len(IMPERATIVE.findall(body))
            literals = len(BACKTICK.findall(body))
            gated = sorted(g for g in guard_names if g in body)
            score = imperative * min(literals, 10)
            if score == 0 and not gated:
                continue
            candidates.append(
                {
                    "file": rel,
                    "anchor": anchor,
                    "line": line,
                    "section": title,
                    "chars": len(body),
                    "imperative": imperative,
                    "literals": literals,
                    "score": score,
                    "already_gated": gated,
                }
            )
    claude_md = repo / "CLAUDE.md"
    root_chars = len(claude_md.read_text(encoding="utf-8")) if claude_md.is_file() else 0
    always_chars = sum(f["chars"] for f in files if f["always_loaded"]) + root_chars
    candidates.sort(key=lambda c: (-len(c["already_gated"]), -c["score"], -c["chars"]))
    return {
        "files": files,
        "claude_md_chars": root_chars,
        "always_loaded_chars": always_chars,
        "candidates": candidates[:40],
    }


# ---------------------------------------------------------------------------
# collect：CI gate
# ---------------------------------------------------------------------------


def workflow_steps(text: str) -> list[dict[str, Any]]:
    """用純文字掃描找出 workflow 裡的 step，回傳 [{name, run, block}]（只收有 run: 的 step）。

    沒寫 name: 的 step，GitHub 顯示為「Run <run 的第一行>」，這裡照同樣規則推出名稱。
    """
    lines = text.splitlines()
    steps = []
    i = 0
    while i < len(lines):
        m = STEP_START.match(lines[i])
        if not m or m.group(2) not in STEP_KEYS:
            i += 1
            continue
        indent = len(m.group(1))
        block = [" " * (indent + 2) + f"{m.group(2)}: {m.group(3)}"]
        j = i + 1
        while j < len(lines):
            line = lines[j]
            if line.strip() and len(line) - len(line.lstrip()) <= indent:
                break
            block.append(line)
            j += 1
        keys: dict[str, str] = {}
        run_lines: list[str] = []
        in_run = False
        for b in block:
            km = re.match(rf"^\s{{{indent + 2}}}([A-Za-z_][\w-]*)\s*:\s*(.*)$", b)
            if km:
                keys[km.group(1)] = km.group(2).strip()
                in_run = km.group(1) == "run"
                if in_run and km.group(2).strip() not in ("|", ">", "|-", ">-", "|+", ">+"):
                    run_lines.append(km.group(2).strip())
            elif in_run and b.strip():
                run_lines.append(b.strip())
        if "run" in keys:
            name = keys.get("name", "").strip().strip("\"'")
            if not name:
                name = "Run " + (run_lines[0] if run_lines else "")
            steps.append({"name": name, "run": "\n".join(run_lines), "block": "\n".join(block)})
        i = j
    return steps


def collect_gate_inventory(repo: Path) -> tuple[dict[str, Any], list[str], list[str]]:
    """列出 gate script、是否接進 .github/workflows，以及在 CI 中呼叫它的 step 名稱（ci_steps）。

    ci_steps 為空但 wired_in_ci 為真，代表 CI 失敗無法歸因到這支 gate，本週不判定 gate-silent。
    回傳 (inventory, warnings, notes)。
    """
    warnings: list[str] = []
    notes: list[str] = []
    gates = []
    harness = repo / "scripts" / "harness"
    workflows = repo / ".github" / "workflows"
    wf_texts: list[str] = []
    if workflows.is_dir():
        for p in sorted(workflows.glob("*.y*ml")):
            try:
                wf_texts.append(p.read_text(encoding="utf-8"))
            except OSError as e:
                warnings.append(f"CI gate：{p} 讀取失敗（{e}）")
    wf_text = "\n".join(wf_texts)
    steps = [s for t in wf_texts for s in workflow_steps(t)]
    if harness.is_dir():
        for p in sorted(harness.iterdir()):
            if not p.is_file() or not GATE_NAME.match(p.name):
                continue
            log = run_cmd(
                ["git", "log", "--diff-filter=A", "--format=%as", "--", str(p.relative_to(repo))],
                repo,
            )
            if log.returncode != 0:
                warnings.append(
                    f"CI gate：{p.name} 的上線日期讀取失敗（{log.stderr.strip()[:200]}），"
                    "不判定是否上線夠久"
                )
            added = log.stdout.split() if log.returncode == 0 else []
            ci_steps = sorted(
                {s["name"] for s in steps if p.name in s["run"] and "${{" not in s["name"]}
            )
            wired = p.name in wf_text
            if wired and not ci_steps:
                notes.append(
                    f"CI gate：{p.name} 出現在 workflow，"
                    "但找不到以 run: 呼叫它且名稱可比對的 step，"
                    "CI 失敗無法歸因，不判定 gate-silent"
                )
            gates.append(
                {
                    "script": p.name,
                    "wired_in_ci": wired,
                    "ci_steps": ci_steps,
                    "added": added[-1] if added else None,
                }
            )
    return {"gates": gates}, warnings, notes


def _decode_stream(text: str) -> list[Any]:
    """解析 `gh api --paginate --jq` 每頁一個 JSON 值、前後相接的輸出。"""
    dec = json.JSONDecoder()
    out = []
    i = 0
    while i < len(text):
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break
        value, i = dec.raw_decode(text, i)
        out.append(value)
    return out


def _fetch_jobs(repo: Path, slug: str, run_id: int) -> list[dict[str, Any]] | None:
    """分頁讀完一個 run 的所有 jobs；讀取失敗或筆數與 total_count 不符回 None（不可寫進快取）。"""
    r = run_cmd(
        [
            "gh",
            "api",
            "--paginate",
            f"repos/{slug}/actions/runs/{run_id}/jobs?per_page=100",
            "--jq",
            "{total_count, jobs: [.jobs[] | {name, conclusion, "
            "steps: [(.steps // [])[] | {name, conclusion}]}]}",
        ],
        repo,
    )
    if r.returncode != 0:
        return None
    try:
        pages = _decode_stream(r.stdout)
    except json.JSONDecodeError:
        return None
    if not pages:
        return None
    jobs = [j for page in pages for j in page.get("jobs", [])]
    if len(jobs) != pages[0].get("total_count"):
        return None
    return jobs


def collect_ci_failures(
    repo: Path, since: dt.datetime, cache_path: Path | None = None
) -> tuple[dict[str, Any], list[str]]:
    """以 gh api 抓 since 之後失敗的 workflow run，再取每個 run 的 failed job 與 failed step。

    回傳的 complete 明確表示量測是否完整：gh repo view 失敗、任一 runs 頁讀取失敗或格式錯、
    撞到 RUNS_MAX_PAGES 上限、任一 run 的 jobs 讀不完整，都是 complete=False。
    已結束 run 的完整 jobs 結果不會再變，所以存進 cache_path，下週只抓新的 run；
    不完整的結果不寫進快取。jobs 以 8 路平行讀取（純讀取）。
    """
    from concurrent.futures import ThreadPoolExecutor

    warnings: list[str] = []
    empty: dict[str, Any] = {"runs": 0, "jobs": {}, "complete": False}
    who = run_cmd(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], repo)
    if who.returncode != 0 or not who.stdout.strip():
        return empty, [f"CI：gh repo view 失敗（{who.stderr.strip()[:200]}），CI 未量測"]
    slug = who.stdout.strip()
    runs: list[dict[str, Any]] = []
    complete = True
    for page in range(1, RUNS_MAX_PAGES + 1):
        r = run_cmd(
            [
                "gh",
                "api",
                "-X",
                "GET",
                f"repos/{slug}/actions/runs",
                "-f",
                f"created=>={since:%Y-%m-%d}",
                "-f",
                "status=failure",
                "-f",
                f"per_page={RUNS_PER_PAGE}",
                "-f",
                f"page={page}",
            ],
            repo,
        )
        if r.returncode != 0:
            warnings.append(f"CI：runs 第 {page} 頁讀取失敗（{r.stderr.strip()[:200]}），CI 未量測")
            complete = False
            break
        try:
            batch = json.loads(r.stdout).get("workflow_runs", [])
        except (json.JSONDecodeError, AttributeError):
            warnings.append(f"CI：runs 第 {page} 頁不是預期的 JSON，CI 未量測")
            complete = False
            break
        runs.extend(batch)
        if len(batch) < RUNS_PER_PAGE:
            break
    else:
        warnings.append(
            f"CI：failed runs 達 {RUNS_MAX_PAGES * RUNS_PER_PAGE} 筆上限，"
            "較早的失敗未計入，CI 未量測"
        )
        complete = False
    cache: dict[str, Any] = {}
    if cache_path and cache_path.is_file():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            warnings.append(f"CI：快取 {cache_path} 無法讀取或格式錯誤，本次全部重抓")
            cache = {}
    missing = [run["id"] for run in runs if str(run["id"]) not in cache]
    failed_jobs = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = pool.map(lambda i: _fetch_jobs(repo, slug, i), missing)
        for run_id, result in zip(missing, results, strict=True):
            if result is None:
                failed_jobs += 1
            else:
                cache[str(run_id)] = result
    if failed_jobs:
        warnings.append(f"CI：{failed_jobs} 個 run 的 jobs 讀取失敗或不完整，CI 未量測")
        complete = False
    if cache_path:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            warnings.append(f"CI：快取 {cache_path} 寫入失敗（{e}），下週會全部重抓")
    jobs: dict[str, dict[str, Any]] = {}
    for run in runs:
        for job in cache.get(str(run["id"]), []):
            if job.get("conclusion") != "failure":
                continue
            steps = [s["name"] for s in job.get("steps", []) if s.get("conclusion") == "failure"]
            key = f"{run.get('name')} / {job.get('name')}"
            s = jobs.setdefault(
                key,
                {"failures": 0, "branches": set(), "steps": collections.Counter(), "last": None},
            )
            s["failures"] += 1
            s["branches"].add(run.get("head_branch") or "?")
            s["steps"].update(steps or ["(no failed step)"])
            s["last"] = max(filter(None, [s["last"], run.get("created_at")]))
    for s in jobs.values():
        s["branches"] = len(s["branches"])
        # 不截斷：gate 歸因要看到每個 failed step，截掉的 step 會被誤判成 0 失敗
        s["steps"] = dict(s["steps"].most_common())
    return {"runs": len(runs), "jobs": jobs, "complete": complete}, warnings


# ---------------------------------------------------------------------------
# 建議
# ---------------------------------------------------------------------------


def evaluation_scope(snap: dict[str, Any]) -> dict[str, Any]:
    """本週哪些建議類型的資料完整、能下結論。

    diff 用它區分「上週的建議本週不成立（resolved）」與「本週量不到（unmeasured）」：
    不在 kinds 內、或 id 列在 unevaluated_ids 的建議，本週消失不代表已解除。
    """
    ev = snap["hooks"]["events"]
    inv = snap["hooks"]["inventory"]
    events_ok = ev.get("files", 0) > 0
    covers = events_ok and bool(ev.get("covers_window"))
    inv_ok = bool(inv.get("complete", True))
    trans_ok = snap["hooks"]["transcript"].get("files", 0) > 0
    ci_ok = bool(snap["ci"]["measured"])
    kinds = set(STATIC_KINDS)
    if inv_ok:
        kinds.add("hook-unregistered")
    if covers and inv_ok:
        kinds |= {"hook-no-data", "hook-low-signal", "hook-insurance-idle"}
    if events_ok:
        kinds |= {"hook-error", "hook-slow"}
    if trans_ok:
        kinds |= {"hook-stale-plugin", "hook-silent-block"}
    if ci_ok:
        kinds |= {"gate-silent", "gate-noisy"}
    unevaluated = sorted(
        f"gate-silent:{g['script']}"
        for g in snap["ci"]["inventory"]["gates"]
        if g["wired_in_ci"] and not g.get("ci_steps")
    )
    return {"kinds": sorted(kinds), "unevaluated_ids": unevaluated}


def build_recommendations(snap: dict[str, Any], th: argparse.Namespace) -> list[dict[str, Any]]:
    """依門檻產生建議。每條有穩定 id，下週用來判斷 persisting／resolved。

    只產生 evaluation_scope 判定為可量測的類型，確保「沒產生」與「量不到」可以區分。
    """
    recs: list[dict[str, Any]] = []
    scope = evaluation_scope(snap)
    kinds = set(scope["kinds"])
    unevaluated = set(scope["unevaluated_ids"])

    def add(
        kind: str,
        target: str,
        bucket: str,
        evidence: dict[str, Any],
        suggestion: str,
        location: str | None = None,
    ) -> None:
        rid = f"{kind}:{target}"
        if kind not in kinds or rid in unevaluated:
            return
        recs.append(
            {
                "id": rid,
                "kind": kind,
                "target": target,
                "location": location or target,
                "bucket": bucket,
                "evidence": evidence,
                "suggestion": suggestion,
            }
        )

    inv = snap["hooks"]["inventory"]
    events = snap["hooks"]["events"]["hooks"]
    trans = snap["hooks"]["transcript"]["hooks"]
    slow_p95 = (
        max(th.slow_p95_ms, 2000)
        if snap["hooks"]["events"].get("resolution") == "second"
        else th.slow_p95_ms
    )

    for name in inv["unregistered"]:
        add(
            "hook-unregistered",
            name,
            "修正",
            {},
            f"`.claude/hooks/{name}` 存在但 settings.json／settings.local.json 都沒註冊，"
            "永遠不會觸發：註冊或刪除",
        )

    for name in sorted(inv["registered"]):
        if name.startswith("inline:"):
            continue
        ev = events.get(name)
        tr = trans.get(name, {})
        signal = (ev or {}).get("block", 0) + (ev or {}).get("warn", 0) + tr.get("block", 0)
        if ev is None:
            add(
                "hook-no-data",
                name,
                "修正",
                {},
                "hook-events 沒有任何呼叫紀錄：matcher 從未命中，或沒有經過 run-hook.sh",
            )
            continue
        if ev["calls"] >= th.min_calls and signal == 0:
            if is_insurance(name):
                add(
                    "hook-insurance-idle",
                    name,
                    "保留",
                    {"calls": ev["calls"], "total_ms": ev["total_ms"]},
                    "保險型 hook 本期 0 攔截：保留，確認 `.claude/hooks/tests/` 有 self-test "
                    "且 CI 有跑",
                )
            else:
                add(
                    "hook-low-signal",
                    name,
                    "退役或改寫",
                    {"calls": ev["calls"], "total_ms": ev["total_ms"]},
                    "本期 0 攔截／0 警告：評估退役，或改成只在 CI 跑的 gate 以省下每次呼叫的時間",
                )
        if ev["calls"] >= 3 and ev["error_rate"] >= th.error_rate:
            add(
                "hook-error",
                name,
                "修正",
                {
                    "calls": ev["calls"],
                    "error": ev["error"],
                    "error_rate": ev["error_rate"],
                    "sample": ev["error_sample"],
                },
                "hook 自身出錯（非政策攔截）比例過高：修 script 或其前提（cwd、依賴工具）",
            )
        if ev["p95_ms"] >= slow_p95 or ev["total_ms"] >= th.slow_total_ms:
            add(
                "hook-slow",
                name,
                "退役或改寫",
                {"p95_ms": ev["p95_ms"], "total_ms": ev["total_ms"], "calls": ev["calls"]},
                "耗時高：縮小 matcher、加早期 exit，或改 async／移到 CI",
            )

    for name, tr in trans.items():
        if name.startswith("inline:"):
            continue
        versions = tr.get("versions") or {}
        if len(versions) > 1:
            latest = max(versions, key=version_key)
            stale = {v: d["block"] for v, d in versions.items() if v != latest}
            add(
                "hook-stale-plugin",
                name,
                "修正",
                {"latest": latest, "stale_blocks": stale},
                "期間內有 session 仍在跑舊版 plugin 快取：修正合併不等於生效，"
                "重啟長壽 session 或更新 plugin",
            )
        # 有版本資訊時只看最新版，避免已修好的舊版紀錄讓 silent-block 誤報
        basis = versions[max(versions, key=version_key)] if versions else tr
        if basis.get("block", 0) and basis.get("no_stderr", 0) / basis["block"] >= 0.5:
            add(
                "hook-silent-block",
                name,
                "修正",
                {"block": basis["block"], "no_stderr": basis["no_stderr"]},
                "過半阻擋沒有任何 stderr：agent 看不到被擋原因，把 block reason 寫到 stderr",
            )

    gates = snap["ci"]["inventory"]["gates"]
    jobs = snap["ci"]["failures"]["jobs"]
    since_gate = dt.date.fromisoformat(snap["window"]["gate_since"][:10])
    for g in gates:
        if not g["wired_in_ci"]:
            add(
                "gate-unwired",
                g["script"],
                "修正",
                {},
                f"`scripts/harness/{g['script']}` 沒有出現在 .github/workflows："
                "只在 pre-commit 跑，CI 看不到",
            )
            continue
        stem = GATE_AFFIX.sub("", g["script"]).casefold()
        step_names = {s.casefold() for s in g.get("ci_steps", [])}
        hits = 0
        for key, j in jobs.items():
            if stem in key.casefold():
                hits += j["failures"]
                continue
            hits += sum(
                n
                for s, n in j["steps"].items()
                if s.casefold() in step_names or stem in s.casefold()
            )
        old_enough = g["added"] and dt.date.fromisoformat(g["added"]) <= since_gate
        if hits == 0 and old_enough:
            add(
                "gate-silent",
                g["script"],
                "退役或改寫",
                {"added": g["added"], "ci_steps": g.get("ci_steps", [])},
                f"上線超過 {th.gate_days} 天且期間 0 次失敗：確認它守的失效仍可能發生；"
                "不可能發生就退役，可能發生就補一個會紅的 canary 證明它還活著",
            )
    # 以 step 為單位：一個 job 常同時跑多支 gate（各自一個 step），job 層級看不出是哪一支在吵
    ignore = re.compile(th.ignore_jobs) if th.ignore_jobs else None
    for key, j in jobs.items():
        if ignore and ignore.search(key):
            continue
        for step, n in j["steps"].items():
            if n >= th.noisy_failures:
                add(
                    "gate-noisy",
                    f"{key} / {step}",
                    "退役或改寫",
                    {"failures": n, "job_failures": j["failures"], "branches": j["branches"]},
                    "失敗次數高：判斷是「抓到真問題」還是「忘了跑某指令」。後者改成 pre-commit "
                    "自動產生或 CI 自動修正，並把對應的人工步驟從 rule 移除",
                )

    rules = snap["rules"]
    for f in rules["files"]:
        if f["always_loaded"] and f["chars"] >= th.heavy_rule_chars:
            add(
                "rule-heavy",
                f["file"],
                "減量",
                {"chars": f["chars"]},
                "每次必載且篇幅大：事故敘事移到 docs 或 git history，只留規則一句＋事故出處；"
                "或收窄 `paths:`",
            )
    for c in rules["candidates"][: th.max_rule_candidates]:
        # id 用「檔案#段落標題」，不含行號；行號只放在 location 供人打開原文
        target = c["anchor"]
        location = f"{c['file']}:{c['line']}"
        if c["already_gated"]:
            add(
                "rule-already-gated",
                target,
                "減量",
                {"section": c["section"], "chars": c["chars"], "gates": c["already_gated"]},
                "段落點名的 hook／gate 已存在：確認機械檢查涵蓋段落所述，是的話縮成一行指標",
                location,
            )
        elif c["score"] >= th.min_rule_score:
            add(
                "rule-mechanize-candidate",
                target,
                "減量",
                {"section": c["section"], "chars": c["chars"], "score": c["score"]},
                "祈使句配字面值多，可能可以機械判定：由 LLM 判讀能否寫成 hook／gate 及誤判率",
                location,
            )
    return recs


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


def week_relation(prev_label: str, curr_label: str) -> str:
    """回傳 next（prev 正好是 curr 的前一個 ISO 週）、same（同一週）或 gap（其他，含無法解析）。"""
    try:
        pm = WEEK_LABEL.fullmatch(prev_label)
        cm = WEEK_LABEL.fullmatch(curr_label)
        if not pm or not cm:
            return "gap"
        p = dt.date.fromisocalendar(int(pm.group(1)), int(pm.group(2)), 1)
        c = dt.date.fromisocalendar(int(cm.group(1)), int(cm.group(2)), 1)
    except ValueError:
        return "gap"
    days = (c - p).days
    if days == 7:
        return "next"
    if days == 0:
        return "same"
    return "gap"


def diff_snapshots(
    prev: dict[str, Any] | None, curr: dict[str, Any], escalate_weeks: int
) -> dict[str, Any]:
    """比對建議與關鍵指標。

    - 本週有、上週有：persisting。上週快照正好是前一個 ISO 週才累加週數；同一週不累加；
      中間有缺週則週數重新從 1 起算並標記 week_gap。
    - 本週有、上週沒有：new。
    - 上週有、本週沒有：該類型本週可判定才算 resolved；量不到則標 unmeasured，週數原樣帶到
      curr["carried"]，下週仍能接續，不會被當成已解除。
    - 週數達 escalate_weeks 升級為 owner 裁決。
    本函式會把 weeks 寫回 curr 的建議、把 carried 寫進 curr，由 report 存回快照。
    """
    prev_recs: dict[str, dict[str, Any]] = {}
    relation = None
    if prev is not None:
        for r in prev.get("recommendations", []) + prev.get("carried", []):
            prev_recs[r["id"]] = r
        relation = week_relation(
            prev.get("window", {}).get("label", ""), curr.get("window", {}).get("label", "")
        )
    # 本週快照沒有 evaluation 時保守處理：一律視為量不到，不宣告任何建議已解除
    scope = curr.get("evaluation") or {"kinds": [], "unevaluated_ids": []}
    kinds = set(scope.get("kinds", []))
    unevaluated = set(scope.get("unevaluated_ids", []))
    curr_recs = {r["id"]: r for r in curr["recommendations"]}
    statuses = []
    for rid, rec in curr_recs.items():
        status, weeks = "new", 1
        if rid in prev_recs and relation != "gap":
            prev_weeks = int(prev_recs[rid].get("weeks") or 1)
            status = "persisting"
            weeks = prev_weeks + 1 if relation == "next" else prev_weeks
        rec["weeks"] = weeks
        statuses.append(
            {"id": rid, "status": status, "weeks": weeks, "escalate": weeks >= escalate_weeks}
        )
    carried = []
    for rid, prec in prev_recs.items():
        if rid in curr_recs:
            continue
        kind = prec.get("kind") or rid.split(":", 1)[0]
        weeks = int(prec.get("weeks") or 1)
        if kind in kinds and rid not in unevaluated:
            statuses.append({"id": rid, "status": "resolved", "weeks": weeks, "escalate": False})
        else:
            statuses.append({"id": rid, "status": "unmeasured", "weeks": weeks, "escalate": False})
            carried.append({**prec, "weeks": weeks})
    curr["carried"] = carried

    def metric(s: dict[str, Any] | None, key: str) -> int | None:
        return None if s is None else s.get("metrics", {}).get(key)

    deltas = {}
    for key in curr["metrics"]:
        before, after = metric(prev, key), curr["metrics"][key]
        deltas[key] = {
            "prev": before,
            "curr": after,
            "delta": None if before is None or after is None else after - before,
        }
    week_gap = None
    if relation == "gap" and prev is not None:
        week_gap = {
            "prev": prev.get("window", {}).get("label"),
            "curr": curr.get("window", {}).get("label"),
        }
    return {"statuses": statuses, "metrics": deltas, "week_gap": week_gap}


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

BUCKET_ORDER = ["修正", "減量", "退役或改寫", "保留"]


def render_report(snap: dict[str, Any], delta: dict[str, Any]) -> str:
    w = snap["window"]
    lines = [f"# Harness 每週盤點 — {snap['repo_name']} {w['label']}", ""]
    lines.append(
        f"- 期間：{w['since'][:10]} ~ {w['until'][:10]}；CI gate 觀察期自 {w['gate_since'][:10]}"
    )
    if not snap["ci"]["measured"]:
        lines.append("- **CI 未量測**：CI 相關指標與 gate-silent／gate-noisy 本週不判定")
    if snap["warnings"]:
        lines.append("- **量測不完整**（資料源讀取失敗或未涵蓋觀察期）：")
        lines.extend(f"  - {x}" for x in snap["warnings"])
    if snap.get("notes"):
        lines.append("- 說明：")
        lines.extend(f"  - {x}" for x in snap["notes"])
    if delta.get("week_gap"):
        g = delta["week_gap"]
        lines.append(
            f"- **週次不相鄰**：上次快照是 {g['prev']}，本週是 {g['curr']}，持續週數重新從 1 起算"
        )
    lines += ["", "## 關鍵指標", "", "| 指標 | 上週 | 本週 | 變化 |", "|---|---:|---:|---:|"]
    for key, d in delta["metrics"].items():
        prev = "-" if d["prev"] is None else d["prev"]
        curr = "未量測" if d["curr"] is None else d["curr"]
        change = "-" if d["delta"] is None else f"{d['delta']:+d}"
        lines.append(f"| {key} | {prev} | {curr} | {change} |")

    status_by_id = {s["id"]: s for s in delta["statuses"]}
    escalated = [s for s in delta["statuses"] if s["escalate"]]
    lines += ["", "## 需要 owner 裁決（同一建議連續未處理）", ""]
    if escalated:
        for s in escalated:
            lines.append(f"- `{s['id']}`：已連續 {s['weeks']} 週")
    else:
        lines.append("- 無")

    lines += ["", "## 上週建議的處理結果（閉環檢驗）", ""]
    resolved = [s for s in delta["statuses"] if s["status"] == "resolved"]
    if resolved:
        lines.extend(f"- ✅ `{s['id']}`：本週已不成立" for s in resolved)
    else:
        lines.append("- 無已解除的建議")

    unmeasured = [s for s in delta["statuses"] if s["status"] == "unmeasured"]
    if unmeasured:
        lines += ["", "## 本週量不到的上週建議（不視為已解除）", ""]
        lines.extend(
            f"- `{s['id']}`：本週資料不足以判定，週數維持第 {s['weeks']} 週" for s in unmeasured
        )

    for bucket in BUCKET_ORDER:
        recs = [r for r in snap["recommendations"] if r["bucket"] == bucket]
        if not recs:
            continue
        lines += [
            "",
            f"## {bucket}（{len(recs)}）",
            "",
            "| 狀態 | 對象 | 類型 | 證據 | 建議 |",
            "|---|---|---|---|---|",
        ]
        for r in recs:
            st = status_by_id.get(r["id"], {})
            tag = "新" if st.get("status") == "new" else f"第 {st.get('weeks', 1)} 週"
            ev = "；".join(f"{k}={v}" for k, v in r["evidence"].items() if k != "sample")
            where = r.get("location") or r["target"]
            lines.append(
                f"| {tag} | `{where}` | {r['kind']} | {ev.replace('|', '/')} | {r['suggestion']} |"
            )

    lines += [
        "",
        "## hook 明細（本期）",
        "",
        "| hook | 呼叫 | block | warn | error | p95 ms | total ms |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, s in sorted(snap["hooks"]["events"]["hooks"].items(), key=lambda x: -x[1]["calls"]):
        lines.append(
            f"| {name} | {s['calls']} | {s['block']} | {s['warn']} | {s['error']} | "
            f"{s['p95_ms']} | {s['total_ms']} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def git_repo_root(path: Path) -> tuple[Path, Path, str] | None:
    """回傳 (checkout 根目錄, 主 repo 根目錄, repo 名稱)。

    在 worktree 內執行時，--show-toplevel 是 worktree 本身；transcript slug 與 repo 名稱
    必須取主 repo（--git-common-dir 的上一層），紀錄與快照才會對到同一個 repo。
    """
    top = run_cmd(["git", "rev-parse", "--show-toplevel"], path)
    common = run_cmd(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], path)
    if top.returncode != 0 or common.returncode != 0:
        return None
    main_repo = Path(common.stdout.strip()).parent
    return Path(top.stdout.strip()), main_repo, main_repo.name


def cmd_collect(args: argparse.Namespace) -> int:
    resolved = git_repo_root(Path(args.repo))
    if resolved is None:
        print(f"[FAIL] {args.repo} 不是 git repo", file=sys.stderr)
        return 2
    repo, main_repo, repo_name = resolved
    now = dt.datetime.now(dt.UTC) if args.now is None else parse_ts(args.now)
    if now is None:
        print(f"[FAIL] --now 格式錯誤：{args.now}", file=sys.stderr)
        return 2
    since = now - dt.timedelta(days=args.days)
    gate_since = now - dt.timedelta(days=args.gate_days)
    warnings: list[str] = []
    notes: list[str] = []

    inventory, w, n = collect_hook_inventory(repo)
    warnings += w
    notes += n
    events, w, n = collect_hook_events(Path(args.events_dir).expanduser(), repo_name, since, now)
    warnings += w
    notes += n
    transcript, w = collect_transcript_blocks(
        Path(args.projects_dir).expanduser(), main_repo, since
    )
    warnings += w
    gate_inv, w, n = collect_gate_inventory(repo)
    warnings += w
    notes += n
    guard_names = set(inventory["on_disk"]) | {g["script"] for g in gate_inv["gates"]}
    rules = collect_rules(repo, guard_names)
    if args.no_ci:
        failures: dict[str, Any] = {"runs": 0, "jobs": {}, "complete": False}
        notes.append("CI：依 --no-ci 略過，CI 未量測；gate-silent／gate-noisy 本週不判定")
    else:
        cache = Path(args.ci_cache).expanduser() if args.ci_cache else None
        failures, w = collect_ci_failures(repo, gate_since, cache)
        warnings += w
    ci_measured = bool(failures["complete"])

    iso_year, iso_week, _ = now.isocalendar()
    snap: dict[str, Any] = {
        "version": SNAPSHOT_VERSION,
        "repo": str(repo),
        "main_repo": str(main_repo),
        "repo_name": repo_name,
        "window": {
            "label": f"{iso_year}-W{iso_week:02d}",
            "since": since.isoformat(),
            "until": now.isoformat(),
            "gate_since": gate_since.isoformat(),
        },
        "warnings": warnings,
        "notes": notes,
        "hooks": {"inventory": inventory, "events": events, "transcript": transcript},
        "rules": rules,
        "ci": {"inventory": gate_inv, "failures": failures, "measured": ci_measured},
    }
    ev_hooks = events["hooks"].values()
    snap["metrics"] = {
        "always_loaded_chars": rules["always_loaded_chars"],
        "registered_hooks": len(inventory["registered"]),
        "hook_calls": sum(s["calls"] for s in ev_hooks),
        "hook_blocks": sum(s["block"] for s in ev_hooks),
        "hook_errors": sum(s["error"] for s in ev_hooks),
        "hook_total_ms": sum(s["total_ms"] for s in ev_hooks),
        # CI 未量測時記 None，報告顯示「未量測」且不算變化，避免把 0 當成真的沒失敗
        "ci_gate_failures": (
            sum(j["failures"] for j in failures["jobs"].values()) if ci_measured else None
        ),
    }
    snap["evaluation"] = evaluation_scope(snap)
    snap["recommendations"] = build_recommendations(snap, args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(out),
                "recommendations": len(snap["recommendations"]),
                "ci_measured": ci_measured,
                "warnings": warnings,
                "notes": notes,
            },
            ensure_ascii=False,
        )
    )
    return 3 if warnings else 0


def load_snapshot(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"快照不存在：{p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != SNAPSHOT_VERSION:
        version = data.get("version") if isinstance(data, dict) else None
        raise ValueError(f"快照版本不符：{p} 是 {version}，需要 {SNAPSHOT_VERSION}")
    return data


def find_prev_snapshot(snapshot: Path) -> Path | None:
    """在本週快照同目錄找檔名排序在它之前的最後一份 snapshot-YYYY-Www.json；沒有回 None。

    目錄讀取失敗會拋 OSError，由呼叫端 fail loud，不可當成「第一次執行」。
    """
    candidates = sorted(
        p
        for p in snapshot.parent.iterdir()
        if SNAPSHOT_NAME.fullmatch(p.name) and p.name < snapshot.name
    )
    return candidates[-1] if candidates else None


def resolve_prev(args: argparse.Namespace) -> tuple[str | None, str]:
    """回傳 (上週快照路徑, 狀態)。狀態：explicit／found／none。"""
    if args.prev != "auto":
        return (args.prev or None), ("explicit" if args.prev else "none")
    found = find_prev_snapshot(Path(args.snapshot))
    return (str(found), "found") if found else (None, "none")


def lesson_key(rec_id: str) -> str:
    """Mycelium key 只收英數、底線、連字號；中文標題會被洗成連字號，所以附上 id 雜湊避免撞 key。"""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", rec_id).strip("-")[:60]
    digest = hashlib.sha256(rec_id.encode("utf-8")).hexdigest()[:8]
    return f"harness-weekly-{slug}-{digest}"


def cmd_report(args: argparse.Namespace) -> int:
    try:
        prev_path, prev_status = resolve_prev(args)
        curr = load_snapshot(args.snapshot)
        prev = load_snapshot(prev_path)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2
    assert curr is not None
    delta = diff_snapshots(prev, curr, args.escalate_weeks)
    # 把累計週數與 carried 寫回本週快照，下週的 persisting 判定才能接續
    Path(args.snapshot).write_text(
        json.dumps(curr, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    Path(args.out).write_text(render_report(curr, delta), encoding="utf-8")
    lessons = [
        {
            "key": lesson_key(r["id"]),
            "type": "operational",
            "project": curr["repo_name"],
            "bucket": r["bucket"],
            "weeks": r["weeks"],
            "insight": f"{snap_label(curr)} {r['kind']} {r.get('location') or r['target']}："
            f"{r['suggestion']}",
        }
        for r in curr["recommendations"]
        if r["bucket"] != "保留"
    ]
    Path(args.lessons_out).write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in lessons) + ("\n" if lessons else ""),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report": args.out,
                "lessons": args.lessons_out,
                "lesson_count": len(lessons),
                "prev": prev_path,
                "prev_status": prev_status,
                "week_gap": delta["week_gap"],
                "escalated": [s["id"] for s in delta["statuses"] if s["escalate"]],
            },
            ensure_ascii=False,
        )
    )
    return 0


def snap_label(snap: dict[str, Any]) -> str:
    return f"[{snap['repo_name']} {snap['window']['label']}]"


def cmd_diff(args: argparse.Namespace) -> int:
    try:
        prev_path, _ = resolve_prev(args)
        prev = load_snapshot(prev_path)
        curr = load_snapshot(args.snapshot)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2
    assert curr is not None
    print(json.dumps(diff_snapshots(prev, curr, args.escalate_weeks), ensure_ascii=False, indent=2))
    return 0


def cmd_write_lessons(args: argparse.Namespace) -> int:
    """逐行（序列）呼叫 `mycelium lessons add --skip-if-exists`。

    以 list args 呼叫、不經 shell，insight 裡的反引號與 $() 都是字面值。
    任一行失敗（格式錯、非零 exit、逾時、找不到 mycelium）都印 [FAIL] 到 stderr，最後 exit 1。
    """
    try:
        raw = Path(args.lessons).read_text(encoding="utf-8")
    except OSError as e:
        print(f"[FAIL] lesson 檔無法讀取：{e}", file=sys.stderr)
        return 2
    exclude = set(args.exclude or [])
    written, skipped, failed = 0, 0, []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            key, ltype, insight = item["key"], item["type"], item["insight"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"[FAIL] 第 {lineno} 行格式錯誤：{e}", file=sys.stderr)
            failed.append(f"line {lineno}")
            continue
        if key in exclude:
            skipped += 1
            continue
        cmd = [
            args.mycelium,
            "lessons",
            "add",
            "--type",
            str(ltype),
            "--key",
            str(key),
            "--insight",
            str(insight),
            "--confidence",
            str(LESSON_CONFIDENCE),
            "--source",
            LESSON_SOURCE,
            "--skill",
            LESSON_SKILL,
            "--skip-if-exists",
        ]
        if item.get("project"):
            cmd += ["--project", str(item["project"])]
        try:
            r = subprocess.run(  # nosec B603
                cmd, capture_output=True, text=True, check=False, timeout=CMD_TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired:
            print(f"[FAIL] {key}：mycelium 逾時（{CMD_TIMEOUT_SECONDS} 秒）", file=sys.stderr)
            failed.append(key)
            continue
        except OSError as e:
            print(f"[FAIL] {key}：無法執行 {args.mycelium}（{e}）", file=sys.stderr)
            failed.append(key)
            continue
        if r.returncode != 0:
            print(
                f"[FAIL] {key}：mycelium exit {r.returncode}：{r.stderr.strip()[:300]}",
                file=sys.stderr,
            )
            failed.append(key)
            continue
        written += 1
    print(
        json.dumps({"written": written, "excluded": skipped, "failed": failed}, ensure_ascii=False)
    )
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Harness 每週盤點")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("collect", help="量測並輸出本週快照")
    c.add_argument("--repo", default=".", help="目標 repo（worktree 亦可）")
    c.add_argument("--out", required=True, help="快照輸出路徑（.json）")
    c.add_argument("--days", type=int, default=7, help="hook 觀察期（天）")
    c.add_argument("--gate-days", type=int, default=90, help="CI gate 觀察期（天）")
    c.add_argument("--events-dir", default="~/.claude/hook-events")
    c.add_argument("--projects-dir", default="~/.claude/projects")
    c.add_argument("--no-ci", action="store_true", help="略過 gh api 的 CI 量測")
    c.add_argument(
        "--ci-cache", default=None, help="failed run 的 jobs 快取檔（.json），下週只抓新 run"
    )
    c.add_argument("--now", default=None, help="測試用：指定現在時間（ISO 8601）")
    c.add_argument("--min-calls", type=int, default=20, help="低訊號判定的最少呼叫次數")
    c.add_argument("--error-rate", type=float, default=0.05)
    c.add_argument("--slow-p95-ms", type=int, default=1000)
    c.add_argument("--slow-total-ms", type=int, default=60000)
    c.add_argument("--noisy-failures", type=int, default=20)
    c.add_argument(
        "--ignore-jobs",
        default=r"/ CI Status$|ci-status",
        help="不計入高噪判定的 job（regex）；預設排除彙總所有 job 結果的 rollup job",
    )
    c.add_argument("--heavy-rule-chars", type=int, default=8000)
    c.add_argument("--min-rule-score", type=int, default=12)
    c.add_argument("--max-rule-candidates", type=int, default=10)
    c.set_defaults(func=cmd_collect)

    for name, fn, help_text in (
        ("diff", cmd_diff, "比對兩份快照"),
        ("report", cmd_report, "輸出報告"),
    ):
        s = sub.add_parser(name, help=help_text)
        s.add_argument("--snapshot", required=True, help="本週快照")
        s.add_argument(
            "--prev",
            default=None,
            help="上週快照；auto 代表在本週快照同目錄找前一份（找不到視為第一次執行）",
        )
        s.add_argument("--escalate-weeks", type=int, default=3)
        if name == "report":
            s.add_argument("--out", required=True, help="報告輸出路徑（.md）")
            s.add_argument("--lessons-out", required=True, help="Mycelium lesson 候選（.jsonl）")
        s.set_defaults(func=fn)

    wl = sub.add_parser("write-lessons", help="把 lesson 候選逐行寫進 Mycelium")
    wl.add_argument("--lessons", required=True, help="report 產出的 lessons-*.jsonl")
    wl.add_argument(
        "--exclude", action="append", default=[], help="不寫入的 key（可重複；LLM 判為維持的條目）"
    )
    wl.add_argument("--mycelium", default="mycelium", help="mycelium 執行檔（預設取 PATH）")
    wl.set_defaults(func=cmd_write_lessons)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "collect":
        args.gate_days = max(args.gate_days, args.days)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

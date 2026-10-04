#!/usr/bin/env python3
"""Harness 每週盤點：量測 rule／hook／CI gate 的成本與有效性，產出快照、週對週比對與報告。

子命令：
  collect        讀取各資料源，輸出本週 JSON 快照（含建議清單與本週可判定的建議類型）
  diff           比對上週與本週快照，標出每條建議是 new／persisting／resolved／unmeasured
  report         把快照（與可選的上週快照）寫成繁中 markdown 報告與 lesson 候選
  weekly         collect + report --prev auto 一次跑完，輸出依 ISO 週命名（給排程器無人值守用）
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
  0  完成且沒有 warnings；可能帶 notes（說明文字，例如秒級計時、--no-ci、gate 無法歸因）。
     notes 不影響 exit code，但可能伴隨本週不判定的建議類型（例如 --no-ci 時 gate-silent／
     gate-noisy 不判定），判定範圍一律以快照的 evaluation 為準
  2  參數或環境錯誤（不是 git repo、--now 格式錯）
  3  完成，但有資料源讀取失敗、缺漏或未涵蓋觀察期（warnings）；受影響的建議類型本週不判定
Exit code（diff／report）：0 完成；2 快照不存在、格式或版本不符、--prev auto 無法讀取目錄
  或走訪到壞 JSON 的快照（--prev auto 遇到版本不符的舊快照會略過並往前找，不算錯誤；
  stdout 的 prev_status 會註明）
  report 會把累計週數與 carried 寫回 --snapshot 指定的本週快照，下週才能接續；
  上週快照沒有 carried（只跑過 collect）時持續中的建議週數重設為 1，報告與 diff 的
  prev_collect_only 會標明

來源完整性：每個資料來源的 collector 回傳 source = {complete, errors}，complete 預設不完整，
目錄列舉、每個檔案讀取、每一行解析全部成功才為 True。evaluation_scope 只信 source：缺漏或
型別不符一律當量不到。上週建議要判 resolved，除了類型可判定，還要本週觀察到該對象的正向證據
（resolution_evidence）。
Exit code（weekly）：collect 回 2 或其他非 0/3 值時原樣回傳、不產報告；report 失敗回傳 report
  的值；否則回傳 collect 的值（0 或 3，3 表示量測不完整但報告已產出；
  帶 --incomplete-ok 時 3 改回 0）
Exit code（write-lessons）：0 全部寫入或依 --skip-if-exists 略過；1 有任一筆失敗、
  寫入結果無法確認，或 --exclude 的 key 不在 lesson 檔內（此時一筆都不寫）；
  2 lesson 檔不存在或無法讀取
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import re
import subprocess  # nosec B404
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# v3：判定語意改變（來源完整性改為白名單、resolved 需要正向證據、歸因只接受精確身分）。
# v2 的 resolved 結論本身不可信，所以不寫遷移：版本不符的舊快照會被略過，週數從 1 起算
SNAPSHOT_VERSION = 3

# CI jobs 快取格式版本；舊版（未標版本）快取可能含不完整的結果，一律忽略重抓
CI_CACHE_SCHEMA = 2

# 產生 hook 建議的最少呼叫數，也是「判定已解除」所需的最少觀察數；兩者共用同一個門檻，
# 才不會出現「剛好夠產生、卻不夠解除」的灰色地帶
HOOK_MIN_CALLS = 3

# transcript 類建議要判定，觀察期內至少要有這麼多筆事件
TRANSCRIPT_MIN_EVENTS = 3

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

# rule 類建議都只依賴 rules 來源；來源不完整時整類不判定
RULE_CANDIDATE_KINDS = ("rule-already-gated", "rule-mechanize-candidate")
RULE_KINDS = frozenset({"rule-heavy", *RULE_CANDIDATE_KINDS})

# mycelium `lessons add --skip-if-exists` 略過既有 key 時寫到 stderr 的訊息
# （tasks/mycelium/cli.py 的 lessons add；exit 0、stdout 空白）；
# 實際寫入時 stdout 是 `id=... trusted=...`
MYCELIUM_SKIP_MARKER = "依 --skip-if-exists 略過寫入"
MYCELIUM_WRITTEN = re.compile(r"^id=\S+", re.M)


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


def scan_dir(path: Path, errors: list[str], label: str) -> list[os.DirEntry[str]]:
    """列出 path 的直接子項（依名稱排序）；所有資料來源的目錄列舉都走這裡。

    目錄不存在（含路徑中有一段不是目錄）回空串列，不算錯誤，由呼叫端決定「沒有」要不要警告；
    其他列舉失敗（權限、I/O 錯誤）記進 errors 並回空串列。不用 `Path.glob`、未防護的
    `iterdir`：它們在列不出來時要嘛靜默回空、要嘛直接拋例外，兩者都會讓「讀不到」被當成
    「沒有」。
    """
    try:
        with os.scandir(path) as it:
            return sorted(it, key=lambda e: e.name)
    except (FileNotFoundError, NotADirectoryError):
        return []
    except OSError as e:
        errors.append(f"{label}：{path} 無法列出（{e}）")
        return []


def make_source(errors: list[str]) -> dict[str, Any]:
    """collector 回報的來源記錄。complete 只在 errors 為空時為 True：預設不完整，由 collector
    在最後一步依「沒有任何失敗」才升為完整，而不是先假設完整、再逐項扣掉。"""
    return {"complete": not errors, "errors": list(errors)}


def source_ok(section: Any) -> bool:
    """section["source"] 是否是完整的來源記錄。

    記錄缺漏、型別不符、complete 不是 True（含 "true"、1 等 truthy 值）、或 errors 有內容，
    一律視為不完整：舊快照與手寫測試資料缺欄位時，往「量不到」的方向解讀。
    """
    if not isinstance(section, dict):
        return False
    src = section.get("source")
    return isinstance(src, dict) and src.get("complete") is True and not src.get("errors")


def _read_lines(path: Path, errors: list[str], label: str) -> Iterator[str]:
    """逐行讀檔；開檔或讀取失敗記進 errors（讀取失敗屬於量測不完整），不中斷整體量測。"""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            yield from fh
    except OSError as e:
        errors.append(f"{label}：{path} 讀取失敗（{e}）")


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

    inventory["source"] 記錄這份清單是否完整：settings 檔、hooks 目錄列舉、每支 hook script
    任一讀取失敗都使它不完整（script 讀不到會讓「被誰引用」的判斷缺資料，進而產生假的
    hook-unregistered）。
    """
    errors: list[str] = []
    notes = [
        "hook 清單：只檢查 repo 的 settings.json 與 settings.local.json，"
        "未檢查使用者層 ~/.claude/settings.json"
    ]
    registered: dict[str, dict[str, Any]] = {}
    read_files = []
    for fname in ("settings.json", "settings.local.json"):
        settings = repo / ".claude" / fname
        try:
            text = settings.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except (OSError, UnicodeDecodeError) as e:
            errors.append(f"hook 清單：{settings} 讀取失敗（{e}），本週不判定未註冊與沒資料")
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            errors.append(f"hook 清單：{settings} 格式錯誤（{e}），本週不判定未註冊與沒資料")
            continue
        if not isinstance(data, dict):
            errors.append(f"hook 清單：{settings} 不是 JSON 物件，本週不判定未註冊與沒資料")
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
    for entry in scan_dir(hooks_dir, errors, "hook 清單"):
        p = Path(entry.path)
        if entry.is_file() and p.suffix in (".sh", ".py") and p.name not in WRAPPERS:
            on_disk.append(p.name)
            try:
                texts[p.name] = p.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                errors.append(f"hook 清單：{p} 讀取失敗（{e}）")
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
            "source": make_source(errors),
        },
        list(errors),
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


def hook_event_files(events_dir: Path, repo_name: str, errors: list[str]) -> list[Path]:
    """只收 `<repo>-YYYY-MM.jsonl`；`<repo>-other-YYYY-MM.jsonl` 屬於另一個 repo，不可混入。

    目錄列不出來記進 errors（不是「沒有紀錄檔」）；目錄不存在則回空串列。
    """
    pattern = re.compile(re.escape(repo_name) + r"-\d{4}-\d{2}\.jsonl")
    return [
        Path(e.path)
        for e in scan_dir(events_dir, errors, "hook-events")
        if pattern.fullmatch(e.name) and e.is_file()
    ]


def collect_hook_events(
    events_dir: Path, repo_name: str, since: dt.datetime, now: dt.datetime
) -> tuple[dict[str, Any], list[str], list[str]]:
    """彙總 run-hook.sh 的 JSONL 紀錄：每支 hook 的呼叫次數、各 outcome 次數與耗時。

    同時判定紀錄是否涵蓋整個觀察期（covers_window）：最早一筆 <= since、觀察期內至少一筆、
    且最新一筆距 now 不超過 EVENTS_MAX_STALENESS。回傳 (events, warnings, notes)。

    covers_window 與 source 是兩件事：covers_window 問「紀錄涵蓋的時間夠不夠」，source 問
    「讀取有沒有失敗」——目錄列不出來、任一檔讀不到、有格式錯誤行，都使 source 不完整。
    """
    warnings: list[str] = []
    errors: list[str] = []
    notes: list[str] = []
    files = hook_event_files(events_dir, repo_name, errors)
    per_hook: dict[str, dict[str, Any]] = {}
    durations: dict[str, list[int]] = collections.defaultdict(list)
    bad_lines = 0
    earliest: dt.datetime | None = None
    latest: dt.datetime | None = None
    in_window = 0
    for f in files:
        for line in _read_lines(f, errors, "hook-events"):
            if not line.strip():
                continue
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
            "慢 hook 的 p95 門檻改為 max(--slow-p95-ms, 2000)ms"
        )
    if not files:
        warnings.append(
            f"hook-events：{events_dir} 找不到 {repo_name}-YYYY-MM.jsonl；run-hook.sh 尚未產生紀錄"
            "（需要含執行紀錄的 run-hook.sh 版本），執行率與耗時無法量測"
        )
    if bad_lines:
        errors.append(f"hook-events：略過 {bad_lines} 行格式錯誤或無時間戳的紀錄")
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
            "source": make_source(errors),
        },
        errors + warnings,
        notes,
    )


# ---------------------------------------------------------------------------
# collect：transcript（涵蓋 plugin hook；保留期約 30 天）
# ---------------------------------------------------------------------------


def project_slug(repo: Path) -> str:
    """Claude Code 以「路徑中每個非英數字元換成 -」命名 ~/.claude/projects 下的目錄。"""
    return re.sub(r"[^A-Za-z0-9]", "-", str(repo.resolve()))


def transcript_files(projects_dir: Path, main_repo: Path, errors: list[str]) -> list[str]:
    """收主 repo 與其 worktree（<slug>--claude-worktrees-*）的 transcript。

    同前綴的其他 repo（如 yibi-mvp-foo）排除在外。目錄列舉失敗（projects 目錄或任一層子目錄）
    記進 errors：`os.walk` 預設把目錄錯誤靜默丟掉，少掉的檔案會被當成「沒有 transcript」。
    """
    slug = project_slug(main_repo)
    out: list[str] = []

    def on_walk_error(e: OSError) -> None:
        errors.append(f"transcript：{e.filename} 無法列出（{e}）")

    for entry in scan_dir(projects_dir, errors, "transcript"):
        name = entry.name
        if entry.is_dir() and (name == slug or name.startswith(slug + "--claude-worktrees-")):
            for root, _dirs, fnames in os.walk(entry.path, onerror=on_walk_error):
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
    """從 transcript 抽出 hook 阻擋與 hook 自身錯誤事件，依 uuid 去重。

    回傳的 in_window（觀察期內有時間戳的事件數）讓 evaluation_scope 判斷 transcript 類建議
    本週能不能下結論：檔案存在但觀察期內事件太少，不能把上週的建議判成已解除。
    source 記錄讀取是否完整：目錄列不出來、任一檔讀不到、有被截斷或格式錯誤的行都使它不完整；
    read_failures 只是其中「讀不到的檔案數」，供人閱讀。
    """
    warnings: list[str] = []
    errors: list[str] = []
    files = transcript_files(projects_dir, main_repo, errors)
    per_hook: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    min_ts: dt.datetime | None = None
    bad_lines = 0
    in_window = 0
    file_errors: list[str] = []

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
        for line in _read_lines(Path(f), file_errors, "transcript"):
            if not line.strip():
                continue
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
            in_window += 1
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
    elif in_window == 0:
        warnings.append(
            f"transcript：找到 {len(files)} 個檔案，但觀察期內（{iso(since)} 之後）沒有任何事件；"
            "舊版 plugin 與無 stderr 阻擋本週不判定"
        )
    errors += file_errors
    if bad_lines:
        errors.append(f"transcript：略過 {bad_lines} 行格式錯誤（可能被截斷）的紀錄")
    return {
        "files": len(files),
        "earliest": iso(min_ts) if min_ts else None,
        "in_window": in_window,
        "read_failures": len(file_errors),
        "hooks": per_hook,
        "source": make_source(errors),
    }, errors + warnings


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


def collect_rules(repo: Path, guard_names: set[str]) -> tuple[dict[str, Any], list[str]]:
    """量測每個 rule 檔的字元數與載入範圍，並對每次必載的檔案逐段打機械化候選分數。

    分數只是排序用的啟發式：祈使句數 × min(反引號字面值數, 10)；語意判斷交給 skill 流程中的 LLM。
    段落若點名了已存在的 hook／gate script，標為 already_gated：多半可縮成一行指標。
    每個候選的 anchor 是「檔案#段落標題」（同檔同名標題依出現順序加 (2)、(3)），
    不含行號，前文增刪行不會讓週對週追蹤斷掉；行號只留作顯示用的位置。
    候選不在這裡截斷：全部排序後存進快照，由 evaluation_scope 把排名在
    --max-rule-candidates 之外的列為本週不判定，避免被截掉的候選被當成已解除。
    讀取失敗的 rule 檔列在 unreadable（供人閱讀）；rules 目錄列不出來或任一檔讀不到，
    source 都不完整，rule 類建議整類本週不判定（寧可多報 unmeasured，也不可誤報 resolved）。
    回傳 (rules, warnings)。
    """
    errors: list[str] = []
    rules_dir = repo / ".claude" / "rules"
    files: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    unreadable: list[str] = []
    targets = [
        Path(e.path)
        for e in scan_dir(rules_dir, errors, "rules")
        if e.name.endswith(".md") and e.is_file()
    ]
    for p in targets:
        rel = str(p.relative_to(repo))
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            errors.append(f"rules：{p} 讀取失敗（{e}），rule 類建議本週不判定")
            unreadable.append(rel)
            continue
        paths = parse_paths_frontmatter(text)
        always = paths is None or any(x in ("**", "**/*") for x in paths)
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
    root_chars: int | None = 0
    if claude_md.is_file():
        try:
            root_chars = len(claude_md.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as e:
            errors.append(f"rules：{claude_md} 讀取失敗（{e}），必載字元本週未量測")
            root_chars = None
    always_chars = (
        sum(f["chars"] for f in files if f["always_loaded"]) + root_chars
        if root_chars is not None and not unreadable
        else None
    )
    candidates.sort(key=lambda c: (-len(c["already_gated"]), -c["score"], -c["chars"], c["anchor"]))
    return {
        "files": files,
        "claude_md_chars": root_chars,
        "always_loaded_chars": always_chars,
        "candidates": candidates,
        "unreadable": unreadable,
        "source": make_source(errors),
    }, list(errors)


# ---------------------------------------------------------------------------
# collect：CI gate
# ---------------------------------------------------------------------------


BLOCK_SCALAR = re.compile(r"^[|>][+-]?\d?[+-]?(?:\s+#.*)?$")


def yaml_scalar(value: str) -> str | None:
    """把單行 YAML 值還原成字串：去掉引號與行尾註解（空白後的 `#`）。

    只處理 plain 與單行的單／雙引號字串；其他形狀（跨行引號、flow 集合、anchor、alias、tag、
    引號後還有非註解內容）回傳 None，代表「看不懂」，呼叫端不可拿它當成可比對的名稱。
    雙引號字串只解碼 `\\"`、`\\\\`、`\\/` 三種跳脫；其他跳脫序列（`\\n`、`\\t`、`\\xNN`…）這裡
    不完整解碼，回傳 None 而不是部分字串——部分字串拿去比對，等於比對一個不存在的名稱。
    """
    v = value.strip()
    if not v or v.startswith("#"):
        return ""
    if v[0] in "\"'":
        quote = v[0]
        i, out = 1, []
        while i < len(v):
            c = v[i]
            if quote == "'" and c == "'":
                if v[i + 1 : i + 2] == "'":  # '' 是單引號字串裡的跳脫
                    out.append("'")
                    i += 2
                    continue
                break
            if quote == '"' and c == "\\" and i + 1 < len(v):
                if v[i + 1] not in '"\\/':
                    return None
                out.append(v[i + 1])
                i += 2
                continue
            if quote == '"' and c == '"':
                break
            out.append(c)
            i += 1
        else:
            return None  # 引號沒有在同一行結束
        rest = v[i + 1 :]
        if rest.strip() and not re.match(r"^\s+#", rest):
            return None
        return "".join(out)
    if v[0] in "[{&*!|>%@`":
        return None
    m = re.search(r"\s#", v)
    return (v[: m.start()] if m else v).strip()


def workflow_steps(text: str) -> list[dict[str, Any]]:
    """用純文字掃描找出 workflow 裡的 step，回傳 [{name, run, block}]。

    沒有 run: 的 step（例如 uses:）run 為空字串；它們仍要列出，gate 歸因才看得到同名的 step。
    沒寫 name: 的 step，GitHub 顯示為「Run <run 的第一行>」，這裡照同樣規則推出名稱。
    name 與單行 run 會去掉引號與 YAML 行尾註解；看不懂的形狀（見 yaml_scalar）name 或 run
    記為 None，gate 歸因時視為無法歸因，不可據此判定 0 失敗。
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
        run_ok = True
        in_run = False
        in_name = False
        name_multiline = False
        for b in block:
            km = re.match(rf"^\s{{{indent + 2}}}([A-Za-z_][\w-]*)\s*:\s*(.*)$", b)
            if km:
                keys[km.group(1)] = km.group(2).strip()
                in_run = km.group(1) == "run"
                in_name = km.group(1) == "name"
                if not in_run:
                    continue
                raw = km.group(2).strip()
                if BLOCK_SCALAR.match(raw):
                    continue
                single = yaml_scalar(raw)
                if single is None:
                    run_ok = False
                    run_lines.append(raw)
                elif single:
                    run_lines.append(single)
            elif in_run and b.strip():
                run_lines.append(b.strip())
            elif in_name and b.strip() and not b.strip().startswith("#"):
                name_multiline = True  # plain scalar 換行續寫：第一行不是完整名稱
        run_text = "\n".join(run_lines)
        name: str | None = None if name_multiline else yaml_scalar(keys.get("name", ""))
        if name == "":
            if "run" in keys:
                name = ("Run " + run_lines[0]) if run_lines and run_ok else None
            else:
                uses = yaml_scalar(keys.get("uses", ""))
                name = f"Run {uses}" if uses else None
        steps.append({"name": name, "run": run_text if run_ok else None, "block": "\n".join(block)})
        i = j
    return steps


def collect_gate_inventory(repo: Path) -> tuple[dict[str, Any], list[str], list[str]]:
    """列出 gate script、是否接進 .github/workflows，以及在 CI 中呼叫它的 step 名稱（ci_steps）。

    歸因只接受精確身分（見 build_recommendations）：CI 失敗的 step 名稱必須與呼叫這支 gate
    的 step 名稱完全相同。名稱在所有 workflow 檔內必須唯一指向這支 gate，所以 workflow 檔名、
    job、step 三者的身分由「step 名稱不重複」一併確立。
    attributable 為假代表 CI 失敗無法可靠歸因到這支 gate，本週不判定 gate-silent，原因有：
    找不到以 run: 呼叫它的 step、呼叫它的 step 名稱或 run 看不懂、同一個 workflow 檔內有 step
    名稱含 `${{ }}` 運算式或看不懂（跳脫序列、多行 plain scalar），或它的 step 名稱也被另一個
    「沒有呼叫它」的 step 使用（同名 step 的失敗分不出是誰）。
    gate 的 workflows 是呼叫它的 step 所在的 workflow 檔名，供 CI 活動量（gate 的 job 本週有沒有
    跑）查詢。上線日期用 `git log --follow`（改名不歸零）；shallow clone 或無法判斷時為 None。
    source 記錄 workflows 與 scripts/harness 目錄列舉、每個 workflow 檔讀取是否完整。
    回傳 (inventory, warnings, notes)。
    """
    errors: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    gates = []
    harness = repo / "scripts" / "harness"
    workflows = repo / ".github" / "workflows"
    wf_files: list[tuple[str, str]] = []
    for entry in scan_dir(workflows, errors, "CI gate"):
        if not entry.name.endswith((".yml", ".yaml")) or not entry.is_file():
            continue
        try:
            wf_files.append((entry.name, Path(entry.path).read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError) as e:
            errors.append(
                f"CI gate：{entry.path} 讀取失敗（{e}），gate-unwired／gate-silent 本週不判定"
            )
    wf_text = "\n".join(text for _, text in wf_files)
    steps: list[dict[str, Any]] = []
    for fname, text in wf_files:
        for step in workflow_steps(text):
            steps.append({**step, "file": fname})
    shallow = _is_shallow(repo)
    if shallow is None:
        warnings.append(
            "CI gate：無法判斷是否為 shallow clone，gate 上線日期未知，gate-silent 不判定"
        )
    elif shallow:
        notes.append(
            "CI gate：這是 shallow clone，歷史不完整，gate 上線日期未知，gate-silent 不判定"
        )
    for entry in scan_dir(harness, errors, "CI gate"):
        if not entry.is_file() or not GATE_NAME.match(entry.name):
            continue
        p = Path(entry.path)
        added: list[str] = []
        if shallow is False:
            log = run_cmd(
                [
                    "git",
                    "log",
                    "--follow",
                    "--diff-filter=A",
                    "--format=%as",
                    "--",
                    str(p.relative_to(repo)),
                ],
                repo,
            )
            if log.returncode != 0:
                warnings.append(
                    f"CI gate：{p.name} 的上線日期讀取失敗（{log.stderr.strip()[:200]}），"
                    "gate-silent 本週不判定"
                )
            else:
                added = log.stdout.split()
        wired = p.name in wf_text
        reason = _gate_attribution_problem(p.name, steps)
        invoking = [s for s in steps if s["run"] is not None and p.name in s["run"]]
        ci_steps = sorted({s["name"] for s in invoking if s["name"]})
        if wired and reason:
            notes.append(f"CI gate：{p.name} {reason}，CI 失敗無法歸因，不判定 gate-silent")
        gates.append(
            {
                "script": p.name,
                "wired_in_ci": wired,
                "ci_steps": ci_steps,
                "workflows": sorted({s["file"] for s in invoking}),
                "attributable": reason is None,
                "added": added[-1] if added else None,
            }
        )
    return {"gates": gates, "source": make_source(errors)}, errors + warnings, notes


def _is_shallow(repo: Path) -> bool | None:
    """repo 是不是 shallow clone；指令失敗或輸出不是 true／false 時無法判斷，回 None。"""
    r = run_cmd(["git", "rev-parse", "--is-shallow-repository"], repo)
    answer = r.stdout.strip() if r.returncode == 0 else ""
    if answer == "true":
        return True
    if answer == "false":
        return False
    return None


def _gate_attribution_problem(script: str, steps: list[dict[str, Any]]) -> str | None:
    """回傳這支 gate 的 CI 失敗為什麼無法歸因；可以歸因時回 None。"""
    related = [s for s in steps if script in s["block"]]
    if any(s["run"] is None or s["name"] is None for s in related):
        return "的 step 名稱或 run 是看不懂的 YAML 形狀"
    invoking = [s for s in related if script in s["run"]]
    if not invoking:
        return "出現在 workflow，但找不到以 run: 呼叫它的 step"
    names = {s["name"] for s in invoking}
    if any("${{" in n for n in names):
        return "的 step 名稱含 `${{ }}` 運算式，執行期名稱無法比對"
    files = {s["file"] for s in invoking}
    for s in steps:
        if s["file"] not in files:
            continue
        # 同一個 workflow 檔內任何 step 的名稱含運算式或看不懂，執行期名稱都可能與這支 gate 的
        # step 同名，分不出失敗是誰的
        if s["name"] is None:
            return "所在 workflow 有 step 名稱看不懂（跳脫序列、多行 plain scalar 等）"
        if "${{" in s["name"]:
            return "所在 workflow 有 step 名稱含 `${{ }}` 運算式，執行期名稱無法比對"
    folded = {n.casefold() for n in names}
    for s in steps:
        same_name = s["name"] is not None and s["name"].casefold() in folded
        if same_name and (s["run"] is None or script not in s["run"]):
            return f"的 step 名稱「{s['name']}」也被另一個沒有呼叫它的 step 使用"
    return None


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


def unmeasured_ci(reason: str) -> dict[str, Any]:
    """CI 沒有量到時的 failures 結構（--no-ci、gh repo view 失敗）：source 與 activity 都不完整。"""
    return {
        "runs": 0,
        "jobs": {},
        "source": make_source([reason]),
        "activity": {"workflows": {}, "source": make_source([reason])},
    }


def collect_workflow_activity(
    repo: Path, slug: str, files: list[str], since: dt.datetime
) -> tuple[dict[str, Any], list[str]]:
    """每個 workflow 檔在 since 之後的 run 總數（任何結論），作為 gate-silent 的觀察證據。

    只有失敗的 run 被列舉過，「0 次失敗」分不出「全部成功」與「根本沒跑」；這份活動量補上後者。
    這是 workflow 層級的證據，不是 job 層級：workflow 有跑但 gate 所在的 job 被 `if:` 略過時，
    仍會被當成有觀察到（已知殘餘風險；job 層級要為每個成功的 run 都抓一次 jobs，成本過高）。
    回傳 (activity, warnings)；任一檔查詢失敗或回應形狀不符，activity 的 source 就不完整。
    """
    errors: list[str] = []
    counts: dict[str, int] = {}
    for name in sorted(set(files)):
        r = run_cmd(
            [
                "gh",
                "api",
                "-X",
                "GET",
                f"repos/{slug}/actions/workflows/{name}/runs",
                "-f",
                f"created=>={since:%Y-%m-%d}",
                "-f",
                "per_page=1",
            ],
            repo,
        )
        if r.returncode != 0:
            errors.append(f"CI：workflow {name} 的 run 數讀取失敗（{r.stderr.strip()[:200]}）")
            continue
        try:
            total = json.loads(r.stdout)["total_count"]
        except (json.JSONDecodeError, TypeError, KeyError):
            errors.append(f"CI：workflow {name} 的 run 數回應不是預期的 JSON（缺 total_count）")
            continue
        if not isinstance(total, int) or isinstance(total, bool):
            errors.append(f"CI：workflow {name} 的 total_count 不是整數")
            continue
        counts[name] = total
    return {"workflows": counts, "source": make_source(errors)}, errors


def collect_ci_failures(
    repo: Path,
    since: dt.datetime,
    cache_path: Path | None = None,
    workflow_files: list[str] | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """以 gh api 抓 since 之後失敗的 workflow run，再取每個 run 的 failed job 與 failed step。

    回傳的 source 明確表示量測是否完整：gh repo view 失敗、任一 runs 頁讀取失敗、回應缺
    workflow_runs 或 total_count、列到的筆數與 total_count 不符、撞到 RUNS_MAX_PAGES 上限、
    任一 run 的 jobs 讀不完整，都是不完整。
    已結束 run 的完整 jobs 結果不會再變，所以存進 cache_path（格式 {"schema", "runs"}），
    下週只抓新的 run；不完整的結果不寫進快取，schema 不符的舊快取整份忽略。
    jobs 以 8 路平行讀取（純讀取）。workflow_files 是 gate 所在的 workflow 檔名，回傳的
    activity 記錄它們在觀察期內的 run 數（activity 的完整性不影響 source）。
    回傳 (failures, warnings, notes)。
    """
    from concurrent.futures import ThreadPoolExecutor

    warnings: list[str] = []
    errors: list[str] = []
    notes: list[str] = []

    def fail(message: str) -> None:
        warnings.append(message)
        errors.append(message)

    who = run_cmd(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], repo)
    if who.returncode != 0 or not who.stdout.strip():
        message = f"CI：gh repo view 失敗（{who.stderr.strip()[:200]}），CI 未量測"
        return unmeasured_ci(message), [message], notes
    slug = who.stdout.strip()
    runs: list[dict[str, Any]] = []
    declared_total: int | None = None
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
            fail(f"CI：runs 第 {page} 頁讀取失敗（{r.stderr.strip()[:200]}），CI 未量測")
            break
        try:
            body = json.loads(r.stdout)
            batch = body["workflow_runs"]
            total = body["total_count"]
        except (json.JSONDecodeError, TypeError, KeyError):
            fail(
                f"CI：runs 第 {page} 頁不是預期的 JSON（缺 workflow_runs 或 total_count），"
                "CI 未量測"
            )
            break
        if not isinstance(batch, list) or not isinstance(total, int) or isinstance(total, bool):
            fail(f"CI：runs 第 {page} 頁的 workflow_runs 或 total_count 型別不符，CI 未量測")
            break
        declared_total = total if declared_total is None else declared_total
        runs.extend(batch)
        if len(batch) < RUNS_PER_PAGE:
            break
    else:
        fail(
            f"CI：failed runs 達 {RUNS_MAX_PAGES * RUNS_PER_PAGE} 筆上限，"
            "較早的失敗未計入，CI 未量測"
        )
    if not errors and declared_total is not None and len(runs) != declared_total:
        fail(f"CI：列到 {len(runs)} 筆 failed run，但 total_count 是 {declared_total}，CI 未量測")
    cache: dict[str, Any] = {}
    if cache_path and cache_path.is_file():
        try:
            loaded = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            warnings.append(f"CI：快取 {cache_path} 無法讀取或格式錯誤，本次全部重抓")
            loaded = None
        if (
            isinstance(loaded, dict)
            and loaded.get("schema") == CI_CACHE_SCHEMA
            and isinstance(loaded.get("runs"), dict)
        ):
            cache = loaded["runs"]
        elif loaded is not None:
            # 舊版快取沒有完整性保證（可能存了分頁沒讀完的 jobs），不可沿用
            notes.append(
                f"CI：快取 {cache_path} 是舊版或未標版本的格式（需要 schema {CI_CACHE_SCHEMA}），"
                "已忽略並全部重抓"
            )
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
        fail(f"CI：{failed_jobs} 個 run 的 jobs 讀取失敗或不完整，CI 未量測")
    if cache_path:
        if not errors:
            # runs 清單完整時才清掉觀察期外的舊 run；清單不完整時不知道哪些還會用到
            current = {str(run["id"]) for run in runs}
            cache = {k: v for k, v in cache.items() if k in current}
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"schema": CI_CACHE_SCHEMA, "runs": cache}
            cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
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
            s["last"] = max(filter(None, [s["last"], run.get("created_at")]), default=None)
    for s in jobs.values():
        s["branches"] = len(s["branches"])
        # 不截斷：gate 歸因要看到每個 failed step，截掉的 step 會被誤判成 0 失敗
        s["steps"] = dict(s["steps"].most_common())
    activity, activity_warnings = collect_workflow_activity(repo, slug, workflow_files or [], since)
    warnings += activity_warnings
    failures = {
        "runs": len(runs),
        "jobs": jobs,
        "source": make_source(errors),
        "activity": activity,
    }
    return failures, warnings, notes


# ---------------------------------------------------------------------------
# 建議
# ---------------------------------------------------------------------------


def evaluation_scope(
    snap: dict[str, Any], max_rule_candidates: int | None = None
) -> dict[str, Any]:
    """本週哪些建議類型的資料完整、能下結論。

    diff 用它區分「上週的建議本週不成立（resolved）」與「本週量不到（unmeasured）」：
    不在 kinds 內、或 id 列在 unevaluated_ids／以 unevaluated_prefixes 任一項開頭的建議，
    本週消失不代表已解除。

    白名單：一個類型預設不在 kinds 內，依賴的每個來源都要「明確證明自己完整」才加入。
    來源的 source 記錄缺漏、型別不符、complete 不是 True、或 errors 有內容，一律視為量不到
    （舊快照、手寫測試資料缺欄位時往保守方向解讀）；ci.measured 缺漏同樣視為量不到，不拋例外。

    - rule 類：rules 來源完整（任何一檔讀不到、目錄列不出來都不完整）
    - gate-unwired：workflows 與 gate 清單的來源完整
    - hook-unregistered：hook 清單完整
    - hook-no-data／low-signal／insurance-idle／error／slow：hook 清單與 hook-events 來源都完整，
      且紀錄涵蓋觀察期（covers_window：最早一筆 <= 起點、觀察期內有紀錄、最新一筆夠新）
    - transcript 類：來源完整，且觀察期內至少 TRANSCRIPT_MIN_EVENTS 筆事件
    - gate-noisy：CI 完整量到
    - gate-silent：CI 完整量到、gate 清單完整；個別 gate 無法歸因、上線日期未知時列入
      unevaluated_ids
    - rule 候選：排名在 max_rule_candidates 之外時不判定

    「這個對象本週有沒有被觀察到」是逐對象的證據，由 diff_snapshots 的 resolution_evidence 負責。
    """
    inv = _section(snap, "hooks", "inventory")
    ev = _section(snap, "hooks", "events")
    tr = _section(snap, "hooks", "transcript")
    ci = _section(snap, "ci")
    gate_inv = _section(snap, "ci", "inventory")
    rules = _section(snap, "rules")
    inv_ok = source_ok(inv)
    covers = source_ok(ev) and _count(ev.get("files")) > 0 and bool(ev.get("covers_window"))
    trans_ok = (
        source_ok(tr)
        and _count(tr.get("files")) > 0
        and _count(tr.get("in_window")) >= TRANSCRIPT_MIN_EVENTS
    )
    ci_ok = ci.get("measured") is True
    gates_ok = source_ok(gate_inv)
    kinds: set[str] = set()
    if source_ok(rules):
        kinds |= RULE_KINDS
    if gates_ok:
        kinds.add("gate-unwired")
    if inv_ok:
        kinds.add("hook-unregistered")
    if covers and inv_ok:
        kinds |= {
            "hook-no-data",
            "hook-low-signal",
            "hook-insurance-idle",
            "hook-error",
            "hook-slow",
        }
    if trans_ok:
        kinds |= {"hook-stale-plugin", "hook-silent-block"}
    if ci_ok:
        kinds.add("gate-noisy")
        if gates_ok:
            kinds.add("gate-silent")
    unevaluated = {
        f"gate-silent:{g['script']}"
        for g in gate_inv.get("gates") or []
        if isinstance(g, dict)
        and g.get("wired_in_ci")
        and (not g.get("ci_steps") or not g.get("attributable", False) or not g.get("added"))
    }
    if max_rule_candidates is not None:
        for c in (rules.get("candidates") or [])[max_rule_candidates:]:
            unevaluated |= {f"{k}:{c['anchor']}" for k in RULE_CANDIDATE_KINDS}
    return {
        "kinds": sorted(kinds),
        "unevaluated_ids": sorted(unevaluated),
        "unevaluated_prefixes": [],
    }


def _section(node: Any, *path: str) -> dict[str, Any]:
    """沿著 path 取出巢狀 dict；任何一層缺漏或不是 dict 回空 dict（缺漏當成「沒有資料」）。"""
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


def _count(value: Any) -> int:
    """快照裡的計數欄位；缺漏或型別不符（含 bool）當成 0，不拋例外。"""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def is_unevaluated(rid: str, scope: dict[str, Any]) -> bool:
    """rid 是否被 scope 標為本週不判定（完整 id 或前綴）。"""
    if rid in set(scope.get("unevaluated_ids") or []):
        return True
    return any(rid.startswith(p) for p in scope.get("unevaluated_prefixes") or [])


def build_recommendations(snap: dict[str, Any], th: argparse.Namespace) -> list[dict[str, Any]]:
    """依門檻產生建議。每條有穩定 id，下週用來判斷 persisting／resolved。

    只產生 evaluation_scope 判定為可量測的類型，確保「沒產生」與「量不到」可以區分。
    """
    recs: list[dict[str, Any]] = []
    scope = evaluation_scope(snap, th.max_rule_candidates)
    kinds = set(scope["kinds"])

    def add(
        kind: str,
        target: str,
        bucket: str,
        evidence: dict[str, Any],
        suggestion: str,
        location: str | None = None,
    ) -> None:
        rid = f"{kind}:{target}"
        if kind not in kinds or is_unevaluated(rid, scope):
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
        if ev["calls"] >= HOOK_MIN_CALLS and ev["error_rate"] >= th.error_rate:
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
        # 只接受精確身分：失敗的 step 名稱必須與呼叫這支 gate 的 step 名稱完全相同（不分大小寫）。
        # 無法歸因的 gate（名稱含運算式、多行、與別的 step 同名…）已由 evaluation_scope 列為
        # 不判定，所以剩下的 gate 其 step 名稱在所有 workflow 內唯一指向它。不再用 gate 檔名字根
        # 去比對 job 或 step 名稱：別的 job 名稱剛好含同一個字根，不是這支 gate 的失敗
        step_names = {s.casefold() for s in g.get("ci_steps", [])}
        hits = sum(
            n for j in jobs.values() for s, n in j["steps"].items() if s.casefold() in step_names
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
    # 排名在上限之外的候選由 evaluation_scope 列為不判定（不是已解除）
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


def _hook_calls(curr: dict[str, Any], name: str) -> int:
    """本週 hook-events 裡這支 hook 的呼叫次數；沒有這支 hook 的項目就是 0。"""
    stats = _section(curr, "hooks", "events", "hooks").get(name)
    return _count(stats.get("calls")) if isinstance(stats, dict) else 0


def _hook_gone(curr: dict[str, Any], name: str) -> bool:
    """這支 hook 已不在「完整」的 hook 註冊清單裡：物件不存在，上週針對它的建議自然不成立。"""
    inv = _section(curr, "hooks", "inventory")
    return source_ok(inv) and name not in (inv.get("registered") or {})


def _gate_state(curr: dict[str, Any], script: str) -> tuple[bool, bool]:
    """(gate 已不存在或已不在 CI, gate 所在的 workflow 在觀察期內有跑過)。

    gate 清單不完整時兩者都是 False：既不能說它不存在，也不能說它有跑。
    """
    gate_inv = _section(curr, "ci", "inventory")
    if not source_ok(gate_inv):
        return False, False
    matches = [g for g in gate_inv.get("gates") or [] if isinstance(g, dict)]
    matches = [g for g in matches if g.get("script") == script]
    wired = [g for g in matches if g.get("wired_in_ci")]
    activity = _section(curr, "ci", "failures", "activity")
    if not wired or not source_ok(activity):
        return not wired, False
    runs = activity.get("workflows")
    runs = runs if isinstance(runs, dict) else {}
    ran = any(_count(runs.get(f)) >= 1 for g in wired for f in g.get("workflows") or [])
    return False, ran


def resolution_evidence(kind: str, target: str, curr: dict[str, Any]) -> bool:
    """上週有、本週沒有的建議，除了「類型可判定」外，是否有本週觀察到的正向證據證明它已解除。

    「沒有出現」不是證據：hook 本週只被呼叫 2 次、或根本沒被呼叫，建議消失只是沒有樣本。
    - hook-error／hook-slow：本週呼叫數 >= HOOK_MIN_CALLS，或這支 hook 已從完整的註冊清單消失
    - hook-silent-block：本週呼叫數 >= HOOK_MIN_CALLS。對象常是 plugin hook，repo 的註冊清單
      看不到它，所以不能拿「不在清單」當證據；plugin hook 因此可能長期維持 unmeasured
    - gate-silent：gate 已不存在或已不在 CI，或它所在的 workflow 在觀察期內至少跑過 1 次
    其他類型只需要來源完整（evaluation_scope 已處理），沒有逐對象的額外證據。
    """
    if kind in ("hook-error", "hook-slow"):
        return _hook_calls(curr, target) >= HOOK_MIN_CALLS or _hook_gone(curr, target)
    if kind == "hook-silent-block":
        return _hook_calls(curr, target) >= HOOK_MIN_CALLS
    if kind == "gate-silent":
        gone, ran = _gate_state(curr, target)
        return gone or ran
    return True


def diff_snapshots(
    prev: dict[str, Any] | None, curr: dict[str, Any], escalate_weeks: int
) -> dict[str, Any]:
    """比對建議與關鍵指標。

    - 本週有、上週有，且上週快照是前一個 ISO 週：persisting，週數 +1；同一週重跑：persisting，
      週數不變。
    - 本週有、上週沒有，或上週快照與本週之間有缺週（week_gap）：new，週數從 1 起算
      （缺週代表中間沒人檢查，連續週數已中斷）。
    - 上週有、本週沒有：該類型本週可判定、且有正向證據（resolution_evidence）才算 resolved；
      否則標 unmeasured 並帶到 curr["carried"]。相鄰週或同週時週數原樣保留（不累加）；
      有缺週時週數重設為 1 並標 streak_reset，避免跨缺口接續累加而誤升級。
    - 上週快照沒有 carried（只跑過 collect、沒經過 report，建議也沒有累計週數）：持續中的建議
      （persisting 與 unmeasured）週數無從接續，一律重設為 1 並標 streak_reset，且回傳
      prev_collect_only，讓報告寫出原因，而不是靜默把週數歸零。
    - 週數達 escalate_weeks 升級為 owner 裁決。
    本函式會把 weeks 寫回 curr 的建議、把 carried 寫進 curr，由 report 存回快照。
    """
    prev_recs: dict[str, dict[str, Any]] = {}
    relation = None
    collect_only = False
    if prev is not None:
        collect_only = not isinstance(prev.get("carried"), list)
        for r in prev.get("recommendations", []) + (prev.get("carried") or []):
            prev_recs[r["id"]] = r
        relation = week_relation(
            prev.get("window", {}).get("label", ""), curr.get("window", {}).get("label", "")
        )
    # 本週快照沒有 evaluation 時保守處理：一律視為量不到，不宣告任何建議已解除
    scope = curr.get("evaluation") or {"kinds": [], "unevaluated_ids": []}
    kinds = set(scope.get("kinds", []))
    curr_recs = {r["id"]: r for r in curr["recommendations"]}
    statuses = []
    for rid, rec in curr_recs.items():
        status, weeks, reset = "new", 1, False
        if rid in prev_recs and relation != "gap":
            prev_weeks = int(prev_recs[rid].get("weeks") or 1)
            status = "persisting"
            weeks = prev_weeks + 1 if relation == "next" else prev_weeks
            if collect_only:
                weeks, reset = 1, True
        rec["weeks"] = weeks
        entry = {"id": rid, "status": status, "weeks": weeks, "escalate": weeks >= escalate_weeks}
        if reset:
            entry["streak_reset"] = True
            entry["streak_reset_reason"] = "previous-collect-only"
        statuses.append(entry)
    carried = []
    for rid, prec in prev_recs.items():
        if rid in curr_recs:
            continue
        kind = prec.get("kind") or rid.split(":", 1)[0]
        target = rid.split(":", 1)[1] if ":" in rid else rid
        weeks = int(prec.get("weeks") or 1)
        if (
            kind in kinds
            and not is_unevaluated(rid, scope)
            and resolution_evidence(kind, target, curr)
        ):
            statuses.append({"id": rid, "status": "resolved", "weeks": weeks, "escalate": False})
            continue
        gap = relation == "gap"
        reset = gap or collect_only
        if reset:
            weeks = 1
        status = {"id": rid, "status": "unmeasured", "weeks": weeks, "escalate": False}
        if reset:
            status["streak_reset"] = True
            status["streak_reset_reason"] = "week-gap" if gap else "previous-collect-only"
        statuses.append(status)
        carried.append({**prec, "weeks": weeks, "streak_reset": reset})
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
    return {
        "statuses": statuses,
        "metrics": deltas,
        "week_gap": week_gap,
        "prev_collect_only": collect_only,
    }


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
            f"- **週次不相鄰**：上次快照是 {g['prev']}，本週是 {g['curr']}，"
            "持續週數（含本週量不到而保留的建議）重新從 1 起算"
        )
    if delta.get("prev_collect_only"):
        lines.append(
            "- **上週快照只跑過 collect、沒有經過 report**（沒有 carried 與累計週數）："
            "持續中的建議週數重新從 1 起算"
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
        reasons = {
            "week-gap": "且與上次快照之間有缺週，週數重設為第 1 週",
            "previous-collect-only": "且上次快照只跑過 collect、沒有累計週數，週數重設為第 1 週",
        }
        lines.extend(
            f"- `{s['id']}`：本週資料不足以判定，"
            + (
                reasons.get(s.get("streak_reset_reason", ""), "週數重設為第 1 週")
                if s.get("streak_reset")
                else f"週數維持第 {s['weeks']} 週"
            )
            for s in unmeasured
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
    rules, w = collect_rules(repo, guard_names)
    warnings += w
    if args.no_ci:
        failures: dict[str, Any] = unmeasured_ci("CI：依 --no-ci 略過，CI 未量測")
        notes.append("CI：依 --no-ci 略過，CI 未量測；gate-silent／gate-noisy 本週不判定")
    else:
        cache = Path(args.ci_cache).expanduser() if args.ci_cache else None
        workflow_files = sorted({f for g in gate_inv["gates"] for f in g.get("workflows", [])})
        failures, w, n = collect_ci_failures(repo, gate_since, cache, workflow_files)
        warnings += w
        notes += n
    ci_measured = source_ok(failures)

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
    snap["evaluation"] = evaluation_scope(snap, args.max_rule_candidates)
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


class SnapshotVersionError(ValueError):
    """快照可讀、是 JSON 物件，但版本不是 SNAPSHOT_VERSION。"""


def load_snapshot(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"快照不存在：{p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"快照格式錯誤：{p} 不是 JSON 物件")
    if data.get("version") != SNAPSHOT_VERSION:
        raise SnapshotVersionError(
            f"快照版本不符：{p} 是 {data.get('version')}，需要 {SNAPSHOT_VERSION}"
        )
    return data


def find_prev_snapshots(snapshot: Path) -> list[Path]:
    """在本週快照同目錄找檔名排序在它之前的 snapshot-YYYY-Www.json，由新到舊。

    目錄讀取失敗會拋 OSError，由呼叫端 fail loud，不可當成「第一次執行」。
    """
    return sorted(
        (
            p
            for p in snapshot.parent.iterdir()
            if SNAPSHOT_NAME.fullmatch(p.name) and p.name < snapshot.name
        ),
        reverse=True,
    )


def resolve_prev(
    args: argparse.Namespace,
) -> tuple[dict[str, Any] | None, str | None, str, list[str]]:
    """回傳 (上週快照, 路徑, 狀態, 因版本不符而略過的快照)。

    狀態：explicit（--prev 指定）／none（沒有上週快照）／found（--prev auto 找到）／
    found_after_skip、none_after_skip（--prev auto 略過了版本不符的舊快照後找到／沒找到）。
    --prev 明確指定的快照版本不符仍然 fail loud；只有 auto 會略過，因為使用者沒有點名那一份。
    """
    if args.prev != "auto":
        return (
            load_snapshot(args.prev),
            (args.prev or None),
            ("explicit" if args.prev else "none"),
            [],
        )
    skipped: list[str] = []
    for p in find_prev_snapshots(Path(args.snapshot)):
        try:
            data = load_snapshot(p)
        except SnapshotVersionError:
            skipped.append(str(p))
            continue
        return data, str(p), ("found_after_skip" if skipped else "found"), skipped
    return None, None, ("none_after_skip" if skipped else "none"), skipped


def lesson_key(rec_id: str) -> str:
    """Mycelium key 只收英數、底線、連字號；中文標題會被洗成連字號，所以附上 id 雜湊避免撞 key。"""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", rec_id).strip("-")[:60]
    digest = hashlib.sha256(rec_id.encode("utf-8")).hexdigest()[:8]
    return f"harness-weekly-{slug}-{digest}"


def cmd_report(args: argparse.Namespace) -> int:
    try:
        curr = load_snapshot(args.snapshot)
        prev, prev_path, prev_status, skipped = resolve_prev(args)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2
    assert curr is not None
    for p in skipped:
        print(f"[WARN] --prev auto 略過版本不符的快照：{p}", file=sys.stderr)
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
                "skipped_incompatible": skipped,
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
        curr = load_snapshot(args.snapshot)
        prev, _, prev_status, skipped = resolve_prev(args)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2
    assert curr is not None
    for p in skipped:
        print(f"[WARN] --prev auto 略過版本不符的快照：{p}", file=sys.stderr)
    delta = diff_snapshots(prev, curr, args.escalate_weeks)
    delta["prev_status"] = prev_status
    print(json.dumps(delta, ensure_ascii=False, indent=2))
    return 0


def cmd_write_lessons(args: argparse.Namespace) -> int:
    """逐行（序列）呼叫 `mycelium lessons add --skip-if-exists`。

    以 list args 呼叫、不經 shell，insight 裡的反引號與 $() 都是字面值。
    寫入前先檢查每個 --exclude 都對得到 lesson 檔裡的 key；對不到代表判讀結果與檔案不一致
    （打錯字或拿錯週），一筆都不寫，印 [FAIL] 並 exit 1。
    每筆依 mycelium 的輸出分成 written（stdout 有 `id=`）與 skipped_existing（stderr 有
    MYCELIUM_SKIP_MARKER）；兩者都沒有代表結果無法確認，記為失敗。
    任一行失敗（格式錯、非零 exit、逾時、找不到 mycelium、結果無法確認）都印 [FAIL] 到 stderr，
    最後 exit 1。
    """
    try:
        raw = Path(args.lessons).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"[FAIL] lesson 檔無法讀取：{e}", file=sys.stderr)
        return 2
    exclude = set(args.exclude or [])
    items: list[tuple[int, dict[str, Any] | None, str | None]] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            _ = (item["key"], item["type"], item["insight"])
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            items.append((lineno, None, str(e)))
            continue
        items.append((lineno, item, None))
    known = {str(it["key"]) for _, it, _ in items if it is not None}
    unknown = sorted(exclude - known)
    if unknown:
        print(
            f"[FAIL] --exclude 的 key 不在 lesson 檔內：{', '.join(unknown)}；未寫入任何 lesson",
            file=sys.stderr,
        )
        return 1
    written, skipped_existing, excluded, failed = 0, 0, 0, []
    for lineno, item, error in items:
        if item is None:
            print(f"[FAIL] 第 {lineno} 行格式錯誤：{error}", file=sys.stderr)
            failed.append(f"line {lineno}")
            continue
        key, ltype, insight = item["key"], item["type"], item["insight"]
        if key in exclude:
            excluded += 1
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
        if MYCELIUM_SKIP_MARKER in (r.stderr or ""):
            skipped_existing += 1
        elif MYCELIUM_WRITTEN.search(r.stdout or ""):
            written += 1
        else:
            print(
                f"[FAIL] {key}：mycelium exit 0 但輸出無法確認是否寫入"
                f"（stdout={(r.stdout or '').strip()[:200]!r}）",
                file=sys.stderr,
            )
            failed.append(key)
    print(
        json.dumps(
            {
                "written": written,
                "skipped_existing": skipped_existing,
                "excluded": excluded,
                "failed": failed,
            },
            ensure_ascii=False,
        )
    )
    return 1 if failed else 0


def cmd_weekly(args: argparse.Namespace) -> int:
    """collect → report --prev auto 一次跑完，輸出依 ISO 週命名，供排程器無人值守呼叫。

    scheduler 的 command 是固定參數陣列、不能算日期，所以檔名與上週快照都由這裡決定。
    預設輸出到「主 repo」的 .runtime/harness-review/（不是 worktree），讓排程與手動執行共用
    同一份快照歷史，週對週比對才接得上。

    Exit code：collect 的 2（參數／環境錯誤）或其他非 0/3 值原樣回傳且不產報告；
    report 失敗回傳 report 的值；否則回傳 collect 的值（3 = 量測不完整，但報告已產出）。
    """
    resolved = git_repo_root(Path(args.repo))
    if resolved is None:
        print(f"[FAIL] {args.repo} 不是 git repo", file=sys.stderr)
        return 2
    _, main_repo, _ = resolved
    now = dt.datetime.now(dt.UTC) if args.now is None else parse_ts(args.now)
    if now is None:
        print(f"[FAIL] --now 格式錯誤：{args.now}", file=sys.stderr)
        return 2
    iso_year, iso_week, _ = now.isocalendar()
    week = f"{iso_year}-W{iso_week:02d}"
    out_dir = (
        Path(args.out_dir).expanduser()
        if args.out_dir
        else main_repo / ".runtime" / "harness-review"
    )
    snapshot = out_dir / f"snapshot-{week}.json"
    report = out_dir / f"report-{week}.md"
    lessons = out_dir / f"lessons-{week}.jsonl"

    gitignored = _output_gitignored(main_repo, out_dir)
    if gitignored is False:
        print(
            f"[WARN] {out_dir} 未被 .gitignore 排除，快照與報告會出現在 git status",
            file=sys.stderr,
        )

    collect_ns = argparse.Namespace(**vars(args))
    collect_ns.out = str(snapshot)
    # 檔名與快照內的週必須出自同一次時鐘讀取；collect 自己再讀一次，跨過週界時兩者會不一致
    collect_ns.now = now.isoformat()
    if not args.no_ci and not args.ci_cache:
        collect_ns.ci_cache = str(out_dir / "ci-jobs-cache.json")
    collect_rc = cmd_collect(collect_ns)
    if collect_rc not in (0, 3):
        return collect_rc

    report_ns = argparse.Namespace(
        snapshot=str(snapshot),
        prev="auto",
        escalate_weeks=args.escalate_weeks,
        out=str(report),
        lessons_out=str(lessons),
    )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report_rc = cmd_report(report_ns)
    if report_rc != 0:
        return report_rc
    report_summary = json.loads(buf.getvalue().strip().splitlines()[-1])
    snap = json.loads(snapshot.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "week": week,
                "snapshot": str(snapshot),
                "report": str(report),
                "lessons": str(lessons),
                "collect_rc": collect_rc,
                # --incomplete-ok 會把 3 改成 0，scheduler 只看得到 exit code；這兩個欄位讓
                # 排程 log 仍看得出量測不完整（例如 gh 授權失效時 ci_measured 一直是 false）
                "warning_count": len(snap.get("warnings", [])),
                "ci_measured": bool(snap.get("ci", {}).get("measured")),
                "output_gitignored": gitignored,
                "prev": report_summary.get("prev"),
                "prev_status": report_summary.get("prev_status"),
                "lesson_count": report_summary.get("lesson_count"),
                "escalated": report_summary.get("escalated"),
            },
            ensure_ascii=False,
        )
    )
    # yibi-stack scheduler 只把 exit 0 記為成功；量測不完整（3）是常態（例如 CI 有 run 還在跑），
    # 排程時用 --incomplete-ok 避免每週都顯示 failed。warnings 仍完整留在快照、報告與上面的 stdout。
    if collect_rc == 3 and args.incomplete_ok:
        return 0
    return collect_rc


def _output_gitignored(main_repo: Path, out_dir: Path) -> bool | None:
    """輸出目錄是否被目標 repo 的 .gitignore 排除。

    不在 repo 內回 None（與 git 無關）；git check-ignore 出錯（exit 128 等）也回 None，
    不猜測。
    """
    try:
        rel = out_dir.resolve().relative_to(main_repo.resolve())
    except ValueError:
        return None
    r = run_cmd(["git", "check-ignore", "-q", str(rel / "snapshot.json")], main_repo)
    if r.returncode == 0:
        return True
    if r.returncode == 1:
        return False
    return None


def _add_collect_args(c: argparse.ArgumentParser) -> None:
    """collect 與 weekly 共用的量測參數（不含輸出路徑）。"""
    c.add_argument("--repo", default=".", help="目標 repo（worktree 亦可）")
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Harness 每週盤點")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("collect", help="量測並輸出本週快照")
    _add_collect_args(c)
    c.add_argument("--out", required=True, help="快照輸出路徑（.json）")
    c.set_defaults(func=cmd_collect)

    w = sub.add_parser("weekly", help="collect + report 一次跑完，輸出依 ISO 週命名（給排程器用）")
    _add_collect_args(w)
    w.add_argument(
        "--out-dir",
        default=None,
        help="輸出目錄；預設為主 repo 的 .runtime/harness-review/",
    )
    w.add_argument("--escalate-weeks", type=int, default=3)
    w.add_argument(
        "--incomplete-ok",
        action="store_true",
        help="量測不完整（collect exit 3）時回 0；給只把 0 當成功的排程器用，warnings 仍寫進報告",
    )
    w.set_defaults(func=cmd_weekly)

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
    if args.command in ("collect", "weekly"):
        args.gate_days = max(args.gate_days, args.days)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

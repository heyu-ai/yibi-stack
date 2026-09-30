#!/usr/bin/env python3
"""Harness 每週盤點：量測 rule／hook／CI gate 的成本與有效性，產出快照、週對週比對與報告。

子命令：
  collect  讀取各資料源，輸出本週 JSON 快照（含建議清單）
  diff     比對上週與本週快照，標出每條建議是 new／persisting／resolved
  report   把快照（與可選的上週快照）寫成繁中 markdown 報告

資料源（全部唯讀）：
  - <repo>/.claude/settings.json 與 .claude/hooks/：hook 註冊清單
  - ~/.claude/hook-events/<repo>-YYYY-MM.jsonl：run-hook.sh 的每次呼叫紀錄
  - ~/.claude/projects/<slug>*/**/*.jsonl：Claude Code transcript
    （含 plugin hook 阻擋，保留約 30 天）
  - <repo>/.claude/rules/*.md、CLAUDE.md：每次必載的 context 成本
  - gh api：CI failed run 與 failed job／step（可用 --no-ci 略過）

Exit code：
  0  完成，所有資料源都讀到
  2  參數或環境錯誤（不是 git repo、快照檔不存在或格式錯）
  3  完成但有資料源讀取失敗；快照的 warnings 欄位列出哪些，報告會標示「量測不完整」
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SNAPSHOT_VERSION = 1

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


def version_key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


# ---------------------------------------------------------------------------
# 共用
# ---------------------------------------------------------------------------


def parse_ts(value: str | None) -> dt.datetime | None:
    """解析 ISO 8601 時間戳；格式錯誤回 None，由呼叫端決定是否計入。"""
    if not value:
        return None
    try:
        ts = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=dt.UTC)


def run_cmd(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """在目標 repo 的 cwd 執行外部指令（不依賴本 script 所在目錄）。"""
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)


def hook_name_from_command(cmd: str) -> str:
    """從 hook 指令字串推出 hook 名稱。

    run-hook.sh launcher 形狀取其後的 script 名；直接呼叫 script 取 basename；
    其餘（inline 指令）回傳 inline:<前 40 字>。
    """
    tokens = [t for t in SCRIPT_TOKEN.findall(cmd or "") if t not in WRAPPERS]
    if tokens:
        return tokens[-1]
    return "inline:" + " ".join((cmd or "").split())[:40]


def is_insurance(hook: str) -> bool:
    return hook.startswith(INSURANCE_PREFIXES)


# ---------------------------------------------------------------------------
# collect：hook 清單
# ---------------------------------------------------------------------------


def collect_hook_inventory(repo: Path) -> dict[str, Any]:
    """讀 settings.json 的 hook 註冊，並找出 .claude/hooks/ 內有檔案但沒註冊的 script。"""
    settings = repo / ".claude" / "settings.json"
    registered: dict[str, dict[str, Any]] = {}
    if settings.is_file():
        data = json.loads(settings.read_text(encoding="utf-8"))
        for event, groups in (data.get("hooks") or {}).items():
            for group in groups:
                for hook in group.get("hooks", []):
                    name = hook_name_from_command(hook.get("command", ""))
                    if name.startswith("inline:") and hook.get("statusMessage"):
                        name = "inline:" + hook["statusMessage"].rstrip(".")
                    entry = registered.setdefault(
                        name, {"events": [], "matchers": [], "async": False}
                    )
                    entry["events"].append(event)
                    entry["matchers"].append(group.get("matcher", ""))
                    entry["async"] = entry["async"] or bool(hook.get("async"))
    hooks_dir = repo / ".claude" / "hooks"
    on_disk = []
    if hooks_dir.is_dir():
        for p in sorted(hooks_dir.iterdir()):
            if p.is_file() and p.suffix in (".sh", ".py") and p.name not in WRAPPERS:
                on_disk.append(p.name)
    # 被其他 hook import 的共用模組（如 *_common.py）不是 hook，不算未註冊
    unregistered = [n for n in on_disk if n not in registered and "common" not in n]
    return {"registered": registered, "on_disk": on_disk, "unregistered": unregistered}


# ---------------------------------------------------------------------------
# collect：hook-events（run-hook.sh 紀錄）
# ---------------------------------------------------------------------------


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


def collect_hook_events(
    events_dir: Path, repo_name: str, since: dt.datetime
) -> tuple[dict[str, Any], list[str]]:
    """彙總 run-hook.sh 的 JSONL 紀錄：每支 hook 的呼叫次數、各 outcome 次數與耗時。"""
    warnings: list[str] = []
    files = sorted(glob.glob(str(events_dir / f"{repo_name}-*.jsonl")))
    per_hook: dict[str, dict[str, Any]] = {}
    durations: dict[str, list[int]] = collections.defaultdict(list)
    bad_lines = 0
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    bad_lines += 1
                    continue
                ts = parse_ts(ev.get("ts"))
                if ts is None:
                    bad_lines += 1
                    continue
                if ts < since:
                    continue
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
                    s["last_block"] = max(filter(None, [s["last_block"], ev["ts"]]))
                if outcome == "error":
                    s["last_error"] = max(filter(None, [s["last_error"], ev["ts"]]))
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
        warnings.append(
            "hook-events：耗時只有秒級解析度（bash 3.2），1000ms 讀值代表 0–2 秒，"
            "慢 hook 判定改用 p95 ≥ 2000ms"
        )
    if not files:
        warnings.append(
            f"hook-events：{events_dir} 找不到 {repo_name}-*.jsonl；run-hook.sh 尚未產生紀錄"
            "（需要含執行紀錄的 run-hook.sh 版本），執行率與耗時無法量測"
        )
    if bad_lines:
        warnings.append(f"hook-events：略過 {bad_lines} 行格式錯誤或無時間戳的紀錄")
    return {
        "files": len(files),
        "hooks": per_hook,
        "resolution": resolution,
        "earliest": earliest_iso(events_dir, repo_name),
    }, warnings


def earliest_iso(events_dir: Path, repo_name: str) -> str | None:
    """最早一筆紀錄的時間，用來判斷紀錄是否涵蓋整個觀察期。"""
    files = sorted(glob.glob(str(events_dir / f"{repo_name}-*.jsonl")))
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    ts = parse_ts(json.loads(line).get("ts"))
                except json.JSONDecodeError:
                    continue
                if ts:
                    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


# ---------------------------------------------------------------------------
# collect：transcript（涵蓋 plugin hook；保留期約 30 天）
# ---------------------------------------------------------------------------


def project_slug(repo: Path) -> str:
    """Claude Code 以「路徑中 / 與 . 換成 -」命名 ~/.claude/projects 下的目錄。"""
    return re.sub(r"[/.]", "-", str(repo.resolve()))


def transcript_files(projects_dir: Path, repo: Path) -> list[str]:
    slug = project_slug(repo)
    out = []
    for d in glob.glob(str(projects_dir / (slug + "*"))):
        name = os.path.basename(d)
        # 只收本 repo 與其 worktree，排除同前綴的其他 repo（如 yibi-mvp-foo）
        if name == slug or name.startswith(slug + "--claude-worktrees-"):
            out.extend(glob.glob(os.path.join(d, "**", "*.jsonl"), recursive=True))
    return sorted(out)


def _tool_result_text(block: dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(x.get("text", "") for x in content if isinstance(x, dict))
    return ""


def collect_transcript_blocks(
    projects_dir: Path, repo: Path, since: dt.datetime
) -> tuple[dict[str, Any], list[str]]:
    """從 transcript 抽出 hook 阻擋與 hook 自身錯誤事件，依 uuid 去重。"""
    warnings: list[str] = []
    files = transcript_files(projects_dir, repo)
    per_hook: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    min_ts: dt.datetime | None = None

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
        iso = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        s["last"] = max(filter(None, [s["last"], iso]))
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
            v["last"] = max(filter(None, [v["last"], iso]))

    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
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
        warnings.append(f"transcript：{projects_dir} 下找不到 {project_slug(repo)} 的 transcript")
    return {
        "files": len(files),
        "earliest": min_ts.strftime("%Y-%m-%dT%H:%M:%SZ") if min_ts else None,
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
    current_title, current_line, buf = "(檔頭)", 1, []
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

    分數只是排序用的啟發式（祈使句數 × 反引號字面值數），語意判斷交給 skill 流程中的 LLM。
    段落若點名了已存在的 hook／gate script，標為 already_gated：多半可縮成一行指標。
    """
    rules_dir = repo / ".claude" / "rules"
    files = []
    candidates = []
    targets = sorted(rules_dir.glob("*.md")) if rules_dir.is_dir() else []
    for p in targets:
        text = p.read_text(encoding="utf-8")
        paths = parse_paths_frontmatter(text)
        always = paths is None or any(x in ("**", "**/*") for x in paths)
        rel = str(p.relative_to(repo))
        files.append({"file": rel, "chars": len(text), "always_loaded": always, "paths": paths})
        if not always:
            continue
        for title, line, body in split_sections(text):
            imperative = len(IMPERATIVE.findall(body))
            literals = len(BACKTICK.findall(body))
            gated = sorted(g for g in guard_names if g in body)
            score = imperative * min(literals, 10)
            if score == 0 and not gated:
                continue
            candidates.append(
                {
                    "file": rel,
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


def collect_gate_inventory(repo: Path) -> dict[str, Any]:
    """列出 gate script 並檢查是否接進 .github/workflows（只在 pre-commit 的 gate CI 看不到）。"""
    gates = []
    harness = repo / "scripts" / "harness"
    workflows = repo / ".github" / "workflows"
    wf_text = ""
    if workflows.is_dir():
        wf_text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(workflows.glob("*.y*ml")))
    if harness.is_dir():
        for p in sorted(harness.iterdir()):
            if not p.is_file() or not re.match(r"(rule-gate-|ci-check-).*\.(py|sh)$", p.name):
                continue
            added = run_cmd(
                ["git", "log", "--diff-filter=A", "--format=%as", "--", str(p.relative_to(repo))],
                repo,
            ).stdout.split()
            gates.append(
                {
                    "script": p.name,
                    "wired_in_ci": p.name in wf_text,
                    "added": added[-1] if added else None,
                }
            )
    return {"gates": gates}


def _fetch_jobs(repo: Path, slug: str, run_id: int) -> list[dict[str, Any]] | None:
    r = run_cmd(
        [
            "gh",
            "api",
            f"repos/{slug}/actions/runs/{run_id}/jobs",
            "--jq",
            "[.jobs[] | {name, conclusion, steps: [.steps[] | {name, conclusion}]}]",
        ],
        repo,
    )
    if r.returncode != 0:
        return None
    return json.loads(r.stdout or "[]")


def collect_ci_failures(
    repo: Path, since: dt.datetime, cache_path: Path | None = None
) -> tuple[dict[str, Any], list[str]]:
    """以 gh api 抓 since 之後失敗的 workflow run，再取每個 run 的 failed job 與 failed step。

    runs 端點每次查詢最多 1000 筆；撞到上限時回報 warning，不假裝完整。
    已結束 run 的 jobs 結果不會再變，所以存進 cache_path，下週只抓新的 run；jobs 以 8 路平行
    讀取（純讀取，沒有平行寫入的靜默失敗問題）。
    """
    from concurrent.futures import ThreadPoolExecutor

    warnings: list[str] = []
    who = run_cmd(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], repo)
    if who.returncode != 0 or not who.stdout.strip():
        return {"runs": 0, "jobs": {}}, [
            f"CI：gh repo view 失敗（{who.stderr.strip()[:200]}），略過 CI 量測"
        ]
    slug = who.stdout.strip()
    runs: list[dict[str, Any]] = []
    for page in range(1, 11):
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
                "per_page=100",
                "-f",
                f"page={page}",
            ],
            repo,
        )
        if r.returncode != 0:
            warnings.append(
                f"CI：runs 第 {page} 頁讀取失敗（{r.stderr.strip()[:200]}），結果不完整"
            )
            break
        batch = json.loads(r.stdout).get("workflow_runs", [])
        runs.extend(batch)
        if len(batch) < 100:
            break
    else:
        warnings.append("CI：failed runs 達 1000 筆上限，較早的失敗未計入")
    cache: dict[str, Any] = {}
    if cache_path and cache_path.is_file():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            warnings.append(f"CI：快取 {cache_path} 格式錯誤，本次全部重抓")
    missing = [run["id"] for run in runs if str(run["id"]) not in cache]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = pool.map(lambda i: _fetch_jobs(repo, slug, i), missing)
        for run_id, result in zip(missing, results, strict=True):
            if result is None:
                warnings.append(f"CI：run {run_id} 的 jobs 讀取失敗")
            else:
                cache[str(run_id)] = result
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
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
        s["steps"] = dict(s["steps"].most_common(10))
    return {"runs": len(runs), "jobs": jobs}, warnings


# ---------------------------------------------------------------------------
# 建議
# ---------------------------------------------------------------------------


def build_recommendations(snap: dict[str, Any], th: argparse.Namespace) -> list[dict[str, Any]]:
    """依門檻產生建議。每條有穩定 id，下週用來判斷 persisting／resolved。"""
    recs: list[dict[str, Any]] = []

    def add(kind: str, target: str, bucket: str, evidence: dict[str, Any], suggestion: str) -> None:
        recs.append(
            {
                "id": f"{kind}:{target}",
                "kind": kind,
                "target": target,
                "bucket": bucket,
                "evidence": evidence,
                "suggestion": suggestion,
            }
        )

    inv = snap["hooks"]["inventory"]
    events = snap["hooks"]["events"]["hooks"]
    trans = snap["hooks"]["transcript"]["hooks"]
    # 紀錄沒涵蓋整個觀察期時，「沒資料」「0 攔截」只代表還沒輪到，不下結論
    have_events = snap["hooks"]["events"]["files"] > 0 and snap["hooks"]["events"].get(
        "covers_window", False
    )
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
            f"`.claude/hooks/{name}` 存在但 settings.json 沒註冊，永遠不會觸發：註冊或刪除",
        )

    for name in sorted(inv["registered"]):
        if name.startswith("inline:"):
            continue
        ev = events.get(name)
        tr = trans.get(name, {})
        signal = (ev or {}).get("block", 0) + (ev or {}).get("warn", 0) + tr.get("block", 0)
        if have_events and ev is None:
            add(
                "hook-no-data",
                name,
                "修正",
                {},
                "hook-events 沒有任何呼叫紀錄：matcher 從未命中，或沒有經過 run-hook.sh",
            )
            continue
        if have_events and ev and ev["calls"] >= th.min_calls and signal == 0:
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
        if ev and ev["calls"] >= 3 and ev["error_rate"] >= th.error_rate:
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
        if ev and (ev["p95_ms"] >= slow_p95 or ev["total_ms"] >= th.slow_total_ms):
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
    ci_measured = snap["ci"]["measured"]
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
        if not ci_measured:
            continue
        stem = re.sub(r"^(rule-gate-|ci-check-)|\.(py|sh)$", "", g["script"])
        hits = sum(
            j["failures"]
            for k, j in jobs.items()
            if stem in k.lower() or any(stem in s.lower() for s in j["steps"])
        )
        old_enough = g["added"] and dt.date.fromisoformat(g["added"]) <= since_gate
        if hits == 0 and old_enough:
            add(
                "gate-silent",
                g["script"],
                "退役或改寫",
                {"added": g["added"]},
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
        target = f"{c['file']}:{c['line']}"
        if c["already_gated"]:
            add(
                "rule-already-gated",
                target,
                "減量",
                {"section": c["section"], "chars": c["chars"], "gates": c["already_gated"]},
                "段落點名的 hook／gate 已存在：確認機械檢查涵蓋段落所述，是的話縮成一行指標",
            )
        elif c["score"] >= th.min_rule_score:
            add(
                "rule-mechanize-candidate",
                target,
                "減量",
                {"section": c["section"], "chars": c["chars"], "score": c["score"]},
                "祈使句配字面值多，可能可以機械判定：由 LLM 判讀能否寫成 hook／gate 及誤判率",
            )
    return recs


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


def diff_snapshots(
    prev: dict[str, Any] | None, curr: dict[str, Any], escalate_weeks: int
) -> dict[str, Any]:
    """比對建議與關鍵指標。persisting 的建議累計週數，達門檻即升級為 owner 裁決。"""
    prev_recs = {r["id"]: r for r in (prev or {}).get("recommendations", [])}
    curr_recs = {r["id"]: r for r in curr["recommendations"]}
    statuses = []
    for rid, rec in curr_recs.items():
        weeks = prev_recs[rid].get("weeks", 1) + 1 if rid in prev_recs else 1
        rec["weeks"] = weeks
        statuses.append(
            {
                "id": rid,
                "status": "persisting" if rid in prev_recs else "new",
                "weeks": weeks,
                "escalate": weeks >= escalate_weeks,
            }
        )
    for rid in prev_recs:
        if rid not in curr_recs:
            statuses.append(
                {
                    "id": rid,
                    "status": "resolved",
                    "weeks": prev_recs[rid].get("weeks", 1),
                    "escalate": False,
                }
            )

    def metric(s: dict[str, Any] | None, key: str) -> int | None:
        return None if s is None else s.get("metrics", {}).get(key)

    deltas = {}
    for key in curr["metrics"]:
        before, after = metric(prev, key), curr["metrics"][key]
        deltas[key] = {
            "prev": before,
            "curr": after,
            "delta": None if before is None else after - before,
        }
    return {"statuses": statuses, "metrics": deltas}


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
    if snap["warnings"]:
        lines.append("- **量測不完整**：")
        lines.extend(f"  - {x}" for x in snap["warnings"])
    lines += ["", "## 關鍵指標", "", "| 指標 | 上週 | 本週 | 變化 |", "|---|---:|---:|---:|"]
    for key, d in delta["metrics"].items():
        prev = "-" if d["prev"] is None else d["prev"]
        change = "-" if d["delta"] is None else f"{d['delta']:+d}"
        lines.append(f"| {key} | {prev} | {d['curr']} | {change} |")

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
            lines.append(
                f"| {tag} | `{r['target']}` | {r['kind']} | {ev.replace('|', '/')} "
                f"| {r['suggestion']} |"
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


def git_repo_root(path: Path) -> tuple[Path, str] | None:
    """回傳 (repo 根目錄, repo 名稱)。worktree 的名稱取主 repo，讓紀錄與快照對到同一個 repo。"""
    top = run_cmd(["git", "rev-parse", "--show-toplevel"], path)
    common = run_cmd(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], path)
    if top.returncode != 0 or common.returncode != 0:
        return None
    return Path(top.stdout.strip()), Path(common.stdout.strip()).parent.name


def cmd_collect(args: argparse.Namespace) -> int:
    resolved = git_repo_root(Path(args.repo))
    if resolved is None:
        print(f"[FAIL] {args.repo} 不是 git repo", file=sys.stderr)
        return 2
    repo, repo_name = resolved
    now = dt.datetime.now(dt.UTC) if args.now is None else parse_ts(args.now)
    if now is None:
        print(f"[FAIL] --now 格式錯誤：{args.now}", file=sys.stderr)
        return 2
    since = now - dt.timedelta(days=args.days)
    gate_since = now - dt.timedelta(days=args.gate_days)
    warnings: list[str] = []

    inventory = collect_hook_inventory(repo)
    events, w = collect_hook_events(Path(args.events_dir).expanduser(), repo_name, since)
    warnings += w
    earliest = parse_ts(events.get("earliest"))
    # 容許 20% 缺口：紀錄最早一筆落在觀察期開頭附近即視為涵蓋
    events["covers_window"] = bool(
        earliest and earliest <= since + dt.timedelta(days=args.days * 0.2)
    )
    if events["files"] and not events["covers_window"]:
        warnings.append(
            f"hook-events：紀錄最早只到 {events['earliest']}，未涵蓋 {args.days} 天觀察期；"
            "本期不產出「沒資料」「低訊號」建議"
        )
    transcript, w = collect_transcript_blocks(Path(args.projects_dir).expanduser(), repo, since)
    warnings += w
    gate_inv = collect_gate_inventory(repo)
    guard_names = set(inventory["on_disk"]) | {g["script"] for g in gate_inv["gates"]}
    rules = collect_rules(repo, guard_names)
    if args.no_ci:
        failures, ci_measured = {"runs": 0, "jobs": {}}, False
    else:
        cache = Path(args.ci_cache).expanduser() if args.ci_cache else None
        failures, w = collect_ci_failures(repo, gate_since, cache)
        warnings += w
        ci_measured = not any(x.startswith("CI：gh repo view") for x in w)

    iso_year, iso_week, _ = now.isocalendar()
    snap: dict[str, Any] = {
        "version": SNAPSHOT_VERSION,
        "repo": str(repo),
        "repo_name": repo_name,
        "window": {
            "label": f"{iso_year}-W{iso_week:02d}",
            "since": since.isoformat(),
            "until": now.isoformat(),
            "gate_since": gate_since.isoformat(),
        },
        "warnings": warnings,
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
        "ci_gate_failures": sum(j["failures"] for j in failures["jobs"].values()),
    }
    snap["recommendations"] = build_recommendations(snap, args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(out),
                "recommendations": len(snap["recommendations"]),
                "warnings": warnings,
            },
            ensure_ascii=False,
        )
    )
    return 3 if warnings else 0


def load_snapshot(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"快照不存在：{p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("version") != SNAPSHOT_VERSION:
        raise ValueError(f"快照版本不符：{p} 是 {data.get('version')}，需要 {SNAPSHOT_VERSION}")
    return data


def cmd_report(args: argparse.Namespace) -> int:
    try:
        curr = load_snapshot(args.snapshot)
        prev = load_snapshot(args.prev)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2
    assert curr is not None
    delta = diff_snapshots(prev, curr, args.escalate_weeks)
    # 把累計週數寫回本週快照，下週的 persisting 判定才能接續
    Path(args.snapshot).write_text(
        json.dumps(curr, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    Path(args.out).write_text(render_report(curr, delta), encoding="utf-8")
    lessons = [
        {
            "key": "harness-weekly-" + re.sub(r"[^A-Za-z0-9_-]+", "-", r["id"]).strip("-")[:80],
            "type": "operational",
            "bucket": r["bucket"],
            "weeks": r["weeks"],
            "insight": f"{snap_label(curr)} {r['kind']} {r['target']}：{r['suggestion']}",
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
        prev = load_snapshot(args.prev)
        curr = load_snapshot(args.snapshot)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2
    assert curr is not None
    print(json.dumps(diff_snapshots(prev, curr, args.escalate_weeks), ensure_ascii=False, indent=2))
    return 0


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
        s.add_argument("--prev", default=None, help="上週快照（第一次執行可省略）")
        s.add_argument("--escalate-weeks", type=int, default=3)
        if name == "report":
            s.add_argument("--out", required=True, help="報告輸出路徑（.md）")
            s.add_argument("--lessons-out", required=True, help="Mycelium lesson 候選（.jsonl）")
        s.set_defaults(func=fn)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "collect":
        args.gate_days = max(args.gate_days, args.days)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

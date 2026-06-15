#!/usr/bin/env python3
"""Lint：make-install 全域 skill（scope: global）不得 dispatch 本 repo plugin agent。

背景——本 repo 有兩條分發管道：

1. `make install`：掃 repo-root `skills/*/SKILL.md`，`scope: global` 者 symlink 到
   `~/.agents/skills/`（全域、跨專案），但只帶 SKILL.md，**不帶 plugin agents**。
2. `claude plugin install`：帶整個 plugin（skills + agents + commands）。

若一個 `scope: global` skill dispatch 一個「本 repo plugin」的 subagent（如 `sdd:*`），
在「裝了 skill 沒裝 plugin」的專案就會找不到該 agent。修法是把這類 skill 改為
plugin-only（移除 repo-root symlink），讓它與 agents 同管道分發。

本 lint 守住此不變式：掃 repo-root `skills/*/SKILL.md`，對 `scope: global` 者偵測
`subagent_type` dispatch；若 namespace 屬本 repo plugin → FAIL。外部 plugin agent
（如 `pr-review-toolkit`）放行——降級無法讓外部 plugin 同行，改以 runtime gate + 文件化處理。

偵測只認 `subagent_type:` / `subagent_type=` token（純文件提及不算 dispatch，避免誤報）。

Usage:
  python3 scripts/lint_skill_scope.py

Exit code:
  0 -> 無違規
  1 -> 有違規（global skill dispatch 本 repo plugin agent）
  2 -> 設定錯誤（marketplace.json / skills 目錄缺失或格式錯誤）
"""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
SKILLS_DIR = REPO_ROOT / "skills"

# subagent_type: <ns>:<agent>  或  subagent_type=<ns>:<agent>
_DISPATCH_RE = re.compile(
    r"subagent_type\s*[:=]\s*[\"']?([a-z0-9][a-z0-9_-]*):([a-z0-9][a-z0-9_-]*)",
    re.IGNORECASE,
)


def load_own_plugins(marketplace_path: Path) -> set[str]:
    """從 marketplace.json 讀本 repo 自有 plugin 名單（plugins[].name）。"""
    data = json.loads(marketplace_path.read_text(encoding="utf-8"))
    plugins = data.get("plugins", [])
    return {p["name"] for p in plugins if isinstance(p, dict) and p.get("name")}


def parse_scope(text: str) -> str | None:
    """取 SKILL.md frontmatter 第一個 scope: 值；無 frontmatter 回傳 None。"""
    body = text.lstrip()
    if not body.startswith("---"):
        return None
    end = body.find("\n---", 3)
    front = body[:end] if end != -1 else body
    m = re.search(r"^scope:\s*([A-Za-z]+)", front, re.MULTILINE)
    return m.group(1) if m else None


def find_own_dispatches(text: str, own_plugins: set[str]) -> list[tuple[str, str, int]]:
    """回傳 [(ns, agent, line_no), ...]，只含 namespace 屬 own_plugins 者。"""
    out: list[tuple[str, str, int]] = []
    for m in _DISPATCH_RE.finditer(text):
        ns = m.group(1).lower()
        if ns in own_plugins:
            line_no = text[: m.start()].count("\n") + 1
            out.append((ns, m.group(2), line_no))
    return out


def iter_global_skill_files(skills_dir: Path) -> "list[tuple[str, Path]]":
    """列出 repo-root skills/*/SKILL.md（follow symlink dir）。"""
    found: list[tuple[str, Path]] = []
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():  # is_dir() follows symlink-to-dir
            continue
        skill_md = entry / "SKILL.md"
        if skill_md.is_file():
            found.append((entry.name, skill_md))
    return found


def main() -> int:
    try:
        own = load_own_plugins(MARKETPLACE)
    except OSError as e:
        print(f"[FAIL] 無法讀取 {MARKETPLACE}：{e}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"[FAIL] {MARKETPLACE} 格式錯誤：{e}", file=sys.stderr)
        return 2
    if not own:
        print(f"[FAIL] {MARKETPLACE} 未列出任何 plugin name", file=sys.stderr)
        return 2
    if not SKILLS_DIR.is_dir():
        print(f"[FAIL] 找不到 skills 目錄：{SKILLS_DIR}", file=sys.stderr)
        return 2

    violations: list[str] = []
    checked = 0
    for skill_name, skill_md in iter_global_skill_files(SKILLS_DIR):
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError as e:
            print(f"[WARN] 無法讀取 skills/{skill_name}/SKILL.md：{e}", file=sys.stderr)
            continue
        if parse_scope(text) != "global":
            continue
        checked += 1
        for ns, agent, line_no in find_own_dispatches(text, own):
            violations.append(
                f"  skills/{skill_name}/SKILL.md:{line_no}: "
                f"scope: global skill dispatch 本 repo plugin agent '{ns}:{agent}'"
            )

    if violations:
        print(
            f"[FAIL] scope: global skill 不得 dispatch 本 repo plugin agent"
            f"（{len(violations)} 個違規）：",
            file=sys.stderr,
        )
        for v in violations:
            print(v, file=sys.stderr)
        print(
            "\n修法：把該 skill 改為 plugin-only——移除 repo-root skills/<name> symlink、"
            "frontmatter scope 改 project，讓它與 agents 同管道（claude plugin install）分發。\n"
            "外部 plugin agent（非本 repo，如 pr-review-toolkit）則維持 global + runtime gate"
            " + 文件化。\n"
            "詳見 .claude/rules/11-skill-authoring.md「Skill scope 與 plugin agent 依賴一致性」。",
            file=sys.stderr,
        )
        return 1

    print(f"[OK] 已檢查 {checked} 個 scope: global skill，無本 repo plugin-agent 依賴違規")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Lint：settings JSON 的 `permissions.allow` 不得含 rule 16 的 Red Flag pattern。

rule 16（`.claude/rules/16-allowlist-hygiene.md`）列出永久 allow 後會放行危險指令的 pattern。
這些 pattern 大多是在權限對話框按「don't ask again」時寫進 settings 的，寫入當下沒有人審查；
本 lint 在 commit 時把它們找出來。

偵測項目（只看 `Bash(...)` 規則，只掃 allow，不掃 deny——deny 裡的寬 pattern 是正確用法）：

- RF1 中間 wildcard：`*` 不在結尾，會跨過任意參數（`Bash(git -C * status)`）
- RF2 verb 層級 wildcard：多子指令工具整個放行（`Bash(git *)`），或 rule 16 規定永遠不放行的
  `rm` / `curl` / `wget` / `rg`
- RF3 變數展開或變數賦值前綴（`$VAR`、`PATH=... git *`）
- RF5 redirect 或 pipe 搭配 wildcard（`Bash(* > *)`、`Bash(* | sh)`）

RF4（網路工具與 URL 限制）併入 RF2 的永不放行清單。

Usage:
  python3 scripts/lint_allowlist.py [--fail] [settings.json ...]
  不帶檔案時檢查 `.claude/settings.json`。

Exit code:
  0 -> 無違規，或有違規但未帶 --fail（advisory 模式，警告寫 stderr）
  1 -> 帶 --fail 且有違規
  2 -> 設定錯誤（檔案讀不到、JSON 壞掉、permissions.allow 不是 list）
"""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILES = [REPO_ROOT / ".claude" / "settings.json"]

# 子指令眾多、整個放行就等於放行破壞性子指令的工具
_BROAD_VERBS = frozenset(
    {
        "git", "npm", "npx", "pnpm", "yarn", "uv", "pip", "pip3", "make", "docker", "kubectl",
        "gh", "brew", "cargo", "terraform", "aws", "gcloud", "bash", "sh", "zsh", "python",
        "python3", "node", "sudo", "env",
    }
)  # fmt: skip
# rule 16：永遠不得 allow-list（任何參數形式都算）
_NEVER_ALLOW = frozenset({"rm", "curl", "wget", "rg"})

_DESCRIPTIONS = {
    "RF1": "中間 wildcard：* 會跨過任意參數與旗標",
    "RF2": "verb 層級 wildcard，或 rule 16 規定永不放行的指令",
    "RF3": "變數展開或賦值前綴：放行範圍取決於執行期的值",
    "RF5": "redirect／pipe 搭配 wildcard：等於放行任意寫檔或任意執行",
}

_TRAILING_WILDCARD = re.compile(r"(:\*|\s\*|\*)$")
_VERB_WILDCARD = re.compile(r"^(\S+?)(:\*|\s+\*)$")


def check_entry(entry: str) -> list[str]:
    """回傳這條 allow 規則命中的 Red Flag 代碼（RF1/RF2/RF3/RF5），沒有就回空 list。"""
    if not (entry.startswith("Bash(") and entry.endswith(")")):
        return []
    inner = entry[len("Bash(") : -1].strip()
    if not inner:
        return []
    flags: list[str] = []

    body = _TRAILING_WILDCARD.sub("", inner)
    if "*" in body:
        flags.append("RF1")

    first = inner.split()[0]
    verb = first.split(":", 1)[0]
    verb_wildcard = _VERB_WILDCARD.match(inner)
    if verb in _NEVER_ALLOW or (verb_wildcard and verb_wildcard.group(1) in _BROAD_VERBS):
        flags.append("RF2")

    if "$" in inner or "=" in first:
        flags.append("RF3")

    if ("*" in inner) and (">" in inner or "|" in inner):
        flags.append("RF5")
    return flags


def lint_settings(text: str) -> list[tuple[str, list[str]]]:
    """回傳 [(allow 規則, [Red Flag 代碼, ...]), ...]。

    JSON 壞掉或結構不對時 raise ValueError：設定錯誤不能被當成「沒有違規」。
    """
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("settings 頂層不是 JSON object")
    permissions = data.get("permissions") or {}
    if not isinstance(permissions, dict):
        raise ValueError("permissions 不是 JSON object")
    allow = permissions.get("allow") or []
    if not isinstance(allow, list):
        raise ValueError("permissions.allow 不是 list")
    findings: list[tuple[str, list[str]]] = []
    for entry in allow:
        if isinstance(entry, str):
            flags = check_entry(entry)
            if flags:
                findings.append((entry, flags))
    return findings


def main(argv: list[str]) -> int:
    fail_mode = "--fail" in argv
    files = [Path(a) for a in argv if a != "--fail"] or DEFAULT_FILES
    total = 0
    for path in files:
        try:
            findings = lint_settings(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"[FAIL] {path}：無法檢查 permissions.allow（{e}）", file=sys.stderr)
            return 2
        for entry, flags in findings:
            total += 1
            reasons = "；".join(f"{f} {_DESCRIPTIONS[f]}" for f in flags)
            print(f"[WARN] {path}: {entry} -- {reasons}", file=sys.stderr)
    if total:
        print(
            f"[WARN] {total} 條 allow 規則命中 rule 16 Red Flag；"
            "改寫方式見 .claude/rules/16-allowlist-hygiene.md「Safe Pattern Examples」",
            file=sys.stderr,
        )
        return 1 if fail_mode else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

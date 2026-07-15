#!/usr/bin/env python3
"""PreToolUse hook: 攔截會刪到 git 追蹤檔的 `rm -rf <dir>`。

Exit codes:
  0 -> 放行
  2 -> 攔截，並把 stdout 訊息顯示給使用者

原因：`git status --porcelain` 只列「有變更」的檔案——乾淨的追蹤檔完全不出現，
      `ls` 則看得到檔案但看不到追蹤狀態。兩者都無法回答「這個目錄裡有沒有
      追蹤內容」，於是「status 只有 ?? → 整個 rm -rf」這個推論會刪掉追蹤檔。
      唯一能回答的是 `git ls-files`（見 rule 15）。

判斷方式：對每個存在的目標目錄執行 `git -C <target> ls-files`。用 `-C <target>`
      而非從 cwd 跑，是因為目標可能位於另一個 linked worktree——那裡有自己的
      index，從主 repo 查會誤判為「無追蹤檔」而放行（PR #214 實際踩過）。

Known limitations (static analysis; determined bypass is possible):
  - 只攔遞迴刪除（rm -r/-rf/-fr/-R…）；非遞迴 `rm <tracked-file>` 不攔
  - 目標含變數或 glob（`rm -rf "$VAR"`、`rm -rf build/*`）無法靜態解析，放行
  - ENV=val rm ... 的賦值前綴未剝除
  - `git` 的 shell alias 不展開
  - find -delete / xargs rm 等其他刪除路徑不在此 hook 範圍
"""

import json
import os
import re
import shlex
import subprocess  # nosec B404
import sys

_BLOCK_MSG = """\
BLOCKED: `rm -rf {target}` 會刪到 {count} 個 git 追蹤檔！

其中包含：
{sample}
原因：`git status` 乾淨或只顯示 ?? 不代表這裡沒有追蹤檔——它只列「有變更」的
      檔案，乾淨的追蹤檔不會出現；`ls` 也看不出追蹤狀態。

先確認範圍：
  git -C {target} ls-files

若確實要刪除這些追蹤檔，用 git 讓刪除進入索引：
  git rm -r {target}

若只想清掉未追蹤的產物，改用：
  git clean -nd {target}    # 先 dry-run 看會刪什麼
  git clean -fd {target}

（見 .claude/rules/15-irreversible-operations.md
  「`git status --porcelain` Is Not a Tracked-File Listing」）
"""

# 遞迴旗標：-r / -R / --recursive，以及 -rf / -fr / -Rf 等合併短旗標
_RECURSIVE_RE = re.compile(r"^-[a-zA-Z]*[rR][a-zA-Z]*$")

# 靜態無法解析的目標：變數展開、command substitution、glob
_UNRESOLVABLE_RE = re.compile(r"[$*?\[]|`")

_MAX_SAMPLE = 5


def _is_recursive(tokens: list[str]) -> bool:
    """tokens 裡是否有遞迴旗標（含 --recursive 與合併短旗標）。"""
    for t in tokens:
        if t == "--recursive":
            return True
        if t.startswith("--"):
            continue
        if _RECURSIVE_RE.match(t):
            return True
    return False


def _rm_targets(tokens: list[str]) -> list[str]:
    """取出 `rm` 的位置參數（跳過旗標；`--` 之後全部視為目標）。"""
    targets: list[str] = []
    seen_ddash = False
    for t in tokens[1:]:  # tokens[0] == "rm"
        if seen_ddash:
            targets.append(t)
            continue
        if t == "--":
            seen_ddash = True
            continue
        if t.startswith("-"):
            continue
        targets.append(t)
    return targets


def _tracked_files(target: str, cwd: str) -> list[str]:
    """回傳 target 目錄底下被 git 追蹤的檔案；非 git repo 或查詢失敗回空 list。

    用 `git -C <target>` 讓查詢落在「target 所屬的那個 worktree」的 index，
    而非呼叫端 cwd 的 index。
    """
    path = target if os.path.isabs(target) else os.path.join(cwd, target)
    if not os.path.isdir(path):
        return []
    try:
        result = subprocess.run(  # nosec B603
            ["git", "-C", path, "ls-files"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def main() -> None:
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    if not isinstance(data, dict):
        sys.exit(0)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    raw_input = data.get("tool_input")
    if not isinstance(raw_input, dict):
        sys.exit(0)

    cmd = raw_input.get("command")
    if not isinstance(cmd, str) or "rm" not in cmd:
        sys.exit(0)

    cwd = data.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()

    for part in re.split(r"&&|\|\||[;\n]", cmd):
        stripped = part.strip().lstrip("(").strip()
        if not re.match(r"rm\b", stripped):
            continue

        try:
            tokens = shlex.split(stripped)
        except ValueError:
            continue

        if not tokens or tokens[0] != "rm":
            continue
        if not _is_recursive(tokens):
            continue

        for target in _rm_targets(tokens):
            if _UNRESOLVABLE_RE.search(target):
                continue
            tracked = _tracked_files(target, cwd)
            if not tracked:
                continue
            sample = "".join(f"  {f}\n" for f in tracked[:_MAX_SAMPLE])
            if len(tracked) > _MAX_SAMPLE:
                sample += f"  ...（共 {len(tracked)} 個）\n"
            print(_BLOCK_MSG.format(target=target, count=len(tracked), sample=sample))
            sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()

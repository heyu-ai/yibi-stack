#!/usr/bin/env python3
"""protect-push 保護 4：攔截「推到 PR 已 merged/closed 的分支」。

<!-- verified: incident PR#449 --> <!-- verified: probe -->

為什麼需要機械 guard，而不是再寫一條規則：這個失誤已是同族第 4 次，且 2026-07-07 的教訓
`pr-cycle-deep-mid-review-merge-recurrence` 當時就寫下「push 前仍無 PR state 自動檢查，所以
會一直復發」，兩個多月後仍未實作，然後在 PR #449 的 session 再次發生（誤以為 #448 仍是
draft，打算把修正 push 進去）。既有教訓 `process-doc-layer-failing-twice-upgrade-to-guard`
的判準是：同一紀律失守第二次就該升級為機械強制。

那次是幸運的 fail-loud：遠端分支剛好被 rebase 過，push 以 non-fast-forward 被拒。**若分支沒被
改動，push 會成功、exit 0，而那個 commit 對已 merged 的 PR 毫無作用**，沒有任何訊號。這個
guard 補的就是那個靜默路徑。

判定（`decide`）：以「有沒有 open PR」為準，不是「有沒有 merged PR」——分支被重用時（舊 PR
merged、新 PR open）push 有去處，必須放行。

fail-open 是刻意的，且逐條具名（推到已 merged 分支會浪費工作但不具破壞性，擋住所有離線 push
的代價更大）。以下情況一律放行：
  1. 環境變數 `PROTECT_PUSH_SKIP_PR_STATE=1`（逃生口）
  2. PATH 上沒有 `gh`
  3. `gh` 非零退出（未登入、離線、非 GitHub remote）或逾時
  4. `gh` 輸出無法解析成 JSON 陣列
  5. 指令裡沒有可靜態解析的 push 目標（變數展開、glob、刪除 refspec）
  6. 目標分支查無 PR，或存在 open PR

退出碼：0 放行；2 攔截（訊息走 stdout，符合 Claude Code PreToolUse 約定）。
**絕不回傳其他非零值**：`.claude/settings.json` 對本 hook 註冊的是 `... || exit 2`，任何非零
都會被當成攔截，所以未預期的錯誤必須自行吞掉並回 0。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # nosec B404
import sys

_GH_TIMEOUT_SECS = 8
# 需要 argument 的 flag：解析 positional 時要連同它的值一起跳過
_ARG_OPTS = {"-o", "--push-option", "--receive-pack", "--exec", "--repo", "-d", "--delete"}
# 無法靜態解析的目標：shell 展開（$VAR / backtick）或 glob
_UNRESOLVABLE = re.compile(r"[$`*?]")
# 不推送分支內容的 flag：出現時不 fallback 到 current_branch
_NO_BRANCH_PUSH_FLAGS = {"--tags", "--all", "--mirror", "-d", "--delete"}
# 環境變數賦值前綴（與 protect-push.sh 的 _env_re 同步）
_ENV_PREFIX = re.compile(r"^(?:\w+=(?:[^\s'\"]+|'[^']*'|\"[^\"]*\")\s+)*")


def _strip_ref_prefix(name: str) -> str:
    return name[len("refs/heads/") :] if name.startswith("refs/heads/") else name


def push_targets(cmd: str, current_branch: str | None) -> list[str]:
    """回傳這條指令會推到的遠端分支名清單（無法解析者略過）。

    `git push origin A:B` 推的是 **B**；這正是既有保護 3 直接放行的形式。
    """
    targets: list[str] = []
    for part in re.split(r"&&|\|\||[;|\n]", cmd):
        stripped = part.strip().lstrip("(").strip()
        # strip env-variable assignment prefixes（與 protect-push.sh 的 _env_re 同步）
        stripped = _ENV_PREFIX.sub("", stripped)
        if not re.match(r"git\s+push\b", stripped):
            continue
        tokens = stripped.split()
        # --delete / -d 在 _ARG_OPTS 裡，會連同下一個 token（分支名）一起跳過
        positional: list[str] = []
        has_no_branch_push_flag = False
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token.startswith("-"):
                if token in _NO_BRANCH_PUSH_FLAGS:
                    has_no_branch_push_flag = True
                i += 2 if ("=" not in token and token in _ARG_OPTS) else 1
                continue
            positional.append(token)
            i += 1
        # positional = [git, push, [remote], [refspec...]]
        refspecs = positional[3:]
        if not refspecs:
            if current_branch and not has_no_branch_push_flag:
                targets.append(current_branch)
            continue
        for refspec in refspecs:
            if _UNRESOLVABLE.search(refspec):
                continue
            # strip force-push prefix（Git refspec 的 `+` 前綴是 force marker，不是分支名的一部分）
            refspec = refspec.lstrip("+")
            if ":" in refspec:
                src, dest = refspec.rsplit(":", 1)
                # `git push origin :branch` 是刪除遠端分支，不是推內容，不在守備範圍
                if not src.strip():
                    continue
            else:
                dest = refspec
            dest = _strip_ref_prefix(dest.strip())
            if not dest:
                continue
            if dest == "HEAD":
                if current_branch:
                    targets.append(current_branch)
                continue
            targets.append(dest)
    return targets


def decide(prs: list[dict]) -> str:
    """`block` 當且僅當「有已結束的 PR 且沒有任何 open PR」。"""
    if not prs:
        return "allow"
    states = {str(pr.get("state", "")).upper() for pr in prs}
    if "OPEN" in states:
        return "allow"
    return "block" if states & {"MERGED", "CLOSED"} else "allow"


def current_branch() -> str | None:
    try:
        proc = subprocess.run(  # nosec B603 B607
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=_GH_TIMEOUT_SECS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    name = proc.stdout.strip()
    return name if proc.returncode == 0 and name and name != "HEAD" else None


def query_prs(branch: str) -> list[dict] | None:
    """回傳該 head 分支的 PR 清單；無法判定時回 None（呼叫端據此放行）。"""
    if shutil.which("gh") is None:
        return None
    try:
        proc = subprocess.run(  # nosec B603 B607
            [
                "gh", "pr", "list",
                "--head", branch,
                "--state", "all",
                "--limit", "20",
                "--json", "number,state",
            ],
            capture_output=True,
            text=True,
            timeout=_GH_TIMEOUT_SECS,
            check=False,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def main(stdin_text: str | None = None) -> int:
    if os.environ.get("PROTECT_PUSH_SKIP_PR_STATE") == "1":
        return 0
    cmd = sys.stdin.read() if stdin_text is None else stdin_text
    if not cmd.strip():
        return 0

    branches = push_targets(cmd, current_branch())
    for branch in dict.fromkeys(branches):  # 去重並保持順序
        prs = query_prs(branch)
        if prs is None or decide(prs) != "block":
            continue
        finished = [pr for pr in prs if str(pr.get("state", "")).upper() in {"MERGED", "CLOSED"}]
        numbers = ", ".join(f"#{pr.get('number')} ({pr.get('state')})" for pr in finished)
        print(f"BLOCKED: 分支 '{branch}' 的 PR 已結束：{numbers}")
        print("")
        print("推上去的 commit 不會進入那個 PR，也不會到 main，而且不會有任何錯誤訊息。")
        print("請確認目前狀態後再決定：")
        print("  gh pr view <n> --json state,mergedAt   # 先查 PR 真實狀態")
        print("  git fetch origin main                  # 再從最新 main 另開分支")
        print("")
        print("若確定要推（例如刻意保留分支內容），設 PROTECT_PUSH_SKIP_PR_STATE=1 再執行。")
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - 見 docstring：非預期錯誤必須放行，不可變成攔截
        sys.exit(0)

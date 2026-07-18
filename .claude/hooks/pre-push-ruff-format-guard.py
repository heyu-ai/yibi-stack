#!/usr/bin/env python3
"""PreToolUse hook: push 前擋下「已 commit 但從沒跑過 ruff format」的 Python 檔。

姊妹 hook `pre-push-tree-drift-guard.py` 擋的是**已格式化但沒 commit**（push 前工作區
有未 commit 的 tracked 改動）。本 hook 補的是**另一半、且它抓不到**的缺口：內容**已經
進 commit、但當初從沒跑過 ruff format**——此時 `git diff` 乾淨，tree-drift-guard 放行，
CI 端 `pre-commit run --all-files` 的 ruff-format 卻必然紅（就地改檔 → files were modified）。

這條路徑的成因（實例 yibi-stack PR #272，及其前身 PR #239 / #207 的同類復發）：

    fresh `git worktree add` 的 worktree 裡 commit **不觸發** pre-commit hook
    -> 未 ruff format 的新 .py 直接進 commit -> 本地看起來乾淨 -> push -> CI 紅

被動記錄（CLAUDE.md gotcha、typed lesson）已證明攔不住反覆復發，故改由本 hook 在 push
這個 CI-gate 時間點主動阻擋：對 repo 跑 `ruff format --check`（比照 CI 的 --all-files），
有任何檔案會被重格式化就 block。

Exit code:
  0 -> 放行（非 push、非 git repo、ruff 不可用、或全部已格式化——一律 fail-open）
  2 -> 攔截（有 .py 尚未 ruff format）並顯示清單與出路

規則來源：~/.claude/CLAUDE.md「Verification Before Claiming Done」、
         .claude/rules/13「make ci before git add silently skips brand-new files」
"""

import json
import os
import re
import shlex
import subprocess  # nosec B404
import sys

_GIT_ENV_KEYS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")

# 測試 seam：黑盒測試在 tmp_path git repo（無 uv project）裡跑，`uv run ruff` 無法解析
# 專案。設此 env 可覆寫整條 ruff 指令，讓測試注入 PATH 上的真 ruff 直接掃 tmp repo
# （用真 ruff 而非 mock，契合姊妹 hook 的測試哲學）。production 不設它，一律走
# 專案 pinned 的 `uv run ruff`（版本與 CI 的 pre-commit ruff-format 一致，避免 PATH 上
# 某個版本相異的 ruff 判讀與 CI 分歧）。
_RUFF_CMD_ENV = "PRE_PUSH_RUFF_GUARD_CMD"
_DEFAULT_RUFF_CMD = ["uv", "run", "ruff", "format", "--check", "."]

# 與 pre-push-tree-drift-guard 同一威脅模型：防的是「意外把未格式化的 commit push 出去」，
# 不是對抗使用者刻意繞過自己的 guard。故只需辨識常見 git 指令形狀（inline env / sudo /
# 指令串），exotic wrapper 落到放行分支即可。
_GIT_COMMAND = re.compile(
    r"(?:^|[;&|(]|\n)\s*"
    r"(?:(?:env\s+)?(?:[A-Za-z_]\w*=\S+\s+)*|sudo\s+)"
    r"git\b(?P<args>[^;&|\n]*)",
    re.MULTILINE,
)
# push 前允許出現的、不影響「這是不是一個 push」判斷的全域選項（帶值者一併吃掉其值）。
_GLOBAL_FLAGS = {
    "--bare",
    "--no-pager",
    "--paginate",
    "--no-optional-locks",
    "--literal-pathspecs",
    "--glob-pathspecs",
    "--noglob-pathspecs",
    "--icase-pathspecs",
    "--no-replace-objects",
    "-p",
}
_GLOBAL_OPTIONS_WITH_VALUE = {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--exec-path",
    "--config-env",
    "--super-prefix",
}


_UNRESOLVABLE_PATH = re.compile(r"['\"$`~()]")


def _push_c_paths(args: str) -> list[str] | None:
    """單一 git 指令：是 push 就回傳它所有 -C 值（可能空 list），否則回傳 None。

    先吃掉全域 flag / 帶值選項，第一個非 option token 才是 subcommand；只有它等於 push
    才算數（其後參數即使出現 'push' 字樣也不是 push 指令）。無法靜態解析（引號未閉合、
    push 前有非白名單 option）時回傳 None（當成非 push → fail-open 放行；本 guard 是格式
    便利檢查，不像姊妹 hook 需要 fail-closed）。
    """
    try:
        tokens = shlex.split(args, posix=True)
    except ValueError:
        return None
    paths: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("-"):
            return paths if token.rstrip(")") == "push" else None
        if token in _GLOBAL_FLAGS:
            index += 1
            continue
        option, separator, inline_value = token.partition("=")
        if option in _GLOBAL_OPTIONS_WITH_VALUE:
            if separator:
                value = inline_value
            else:
                index += 1
                if index >= len(tokens):
                    return None
                value = tokens[index]
            if option == "-C":
                paths.append(value)
            index += 1
            continue
        # push 前出現非白名單 option：無法確定，當成非 push（fail-open）。
        return None
    return None


def _resolve_cwd(paths: list[str], base_cwd: str) -> str | None:
    """依 Git 的 -C 累積語意解析目標 cwd；含 shell 展開 / 引號的路徑無法靜態解析回傳 None。

    每個相對 -C 相對於前一個位置；絕對路徑重置 base。無法解析時回傳 None → 呼叫端
    fail-open 放行（本 guard 是格式便利檢查，靜態不確定時不擋）。
    """
    if any(_UNRESOLVABLE_PATH.search(path) for path in paths):
        return None
    cwd = os.path.realpath(base_cwd)
    for path in paths:
        cwd = os.path.realpath(os.path.join(cwd, path))
    return cwd


def _push_target_cwds(command: str, base_cwd: str) -> list[str]:
    """回傳指令串中每個 push 對應的目標 cwd（已套用 -C）；無 push 回傳空 list。"""
    targets: list[str] = []
    for match in _GIT_COMMAND.finditer(command):
        paths = _push_c_paths(match.group("args"))
        if paths is None:
            continue
        cwd = _resolve_cwd(paths, base_cwd)
        if cwd is not None:
            targets.append(cwd)
    return targets


def _repo_root(base_cwd: str) -> str | None:
    """回傳 base_cwd 所在 repo（或 worktree）的 toplevel；非 git 目錄回傳 None。

    清掉 GIT_DIR/GIT_WORK_TREE 等 selector，避免 hook 執行環境（可能繼承自 git hook 情境）
    把解析導向別的 repo（見 rule 13「GIT_DIR / GIT_WORK_TREE Override」）。
    """
    env = os.environ.copy()
    for key in _GIT_ENV_KEYS:
        env.pop(key, None)
    env["LC_ALL"] = "C"
    try:
        result = subprocess.run(  # nosec B603 B607
            ["git", "rev-parse", "--show-toplevel"],
            cwd=base_cwd,
            env=env,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return root or None


def _unformatted_files(root: str) -> list[str] | None:
    """對 repo 跑 `ruff format --check`，回傳會被重格式化的檔案清單。

    回傳 None 代表無法判斷（ruff 不可用 / 執行失敗）——呼叫端據此 fail-open 放行。
    比照 CI 的 pre-commit --all-files 掃全 repo：ruff 極快，且 CI 本就會對全樹判紅，
    只掃 diff 反而會漏掉「push 進來的 commit 讓別處檔案失格」的少見情形。
    """
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    override = env.get(_RUFF_CMD_ENV)
    if override:
        try:
            cmd = shlex.split(override)
        except ValueError:
            return None
        if not cmd:
            return None
    else:
        cmd = _DEFAULT_RUFF_CMD
    try:
        result = subprocess.run(  # nosec B603 B607
            cmd,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode == 0:
        return []  # 全部已格式化
    # ruff --check 對「會重格式化」回傳 1，並在 stdout 印 `Would reformat: <path>`。
    # 其他非 0（例如 2 = 用法錯誤 / ruff 不存在於 uv 環境）無法判定 -> fail-open。
    lines = [ln for ln in result.stdout.splitlines() if ln.startswith("Would reformat:")]
    if result.returncode == 1 and lines:
        return [ln.partition("Would reformat:")[2].strip() for ln in lines]
    return None


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if data.get("tool_name") != "Bash":
        sys.exit(0)
    command = data.get("tool_input", {}).get("command", "")
    if not isinstance(command, str):
        sys.exit(0)

    base_cwd = data.get("cwd")
    if not isinstance(base_cwd, str) or not base_cwd:
        base_cwd = os.getcwd()

    targets = _push_target_cwds(command, base_cwd)
    if not targets:
        sys.exit(0)  # 非 push 指令

    unformatted: list[str] = []
    for target in targets:
        root = _repo_root(target)
        if root is None:
            continue  # 非 git 目錄不屬本 guard 範圍
        found = _unformatted_files(root)
        if found:  # None（無法判斷）或 []（全乾淨）都跳過
            unformatted = found
            break
    if not unformatted:
        sys.exit(0)

    listed = "\n".join(f"    {f}" for f in unformatted)
    print(
        "[BLOCKED] 有已 commit 但未經 ruff format 的 Python 檔，push 出去 CI 必紅\n"
        "\n"
        f"{listed}\n"
        "\n"
        "這些檔的內容已經在 commit 裡，但從沒跑過 ruff format。工作區是乾淨的，\n"
        "所以 tree-drift-guard 放行——但 CI 的 pre-commit（--all-files）會就地改檔並判紅。\n"
        "常見成因：在 fresh git worktree 裡 commit 不觸發本地 pre-commit hook。\n"
        "\n"
        "出路：\n"
        "  uv run ruff format .        # 全樹格式化\n"
        "  git add <上列檔案> && git commit --amend   # 或另開一個 fixup commit\n"
        "  然後重新 push\n"
        "\n"
        "規則來源：~/.claude/CLAUDE.md「Verification Before Claiming Done」"
    )
    sys.exit(2)


if __name__ == "__main__":
    main()

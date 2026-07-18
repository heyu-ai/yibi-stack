#!/usr/bin/env python3
"""PreToolUse hook: push 前擋下「已驗證的樹 != 要 push 的樹」。

pre-commit 的 formatter hook（ruff-format、trailing-whitespace 等）是**就地改檔**，
不是唯讀檢查。於是這條路徑會靜默失敗：

    commit -> make ci（formatter 就地改寫工作區）-> 綠 -> push

本地綠是真的，但那個改寫從未進 commit，CI 端沒有工作區可以 commit，必然紅。
（實例：yibi-stack PR #248，本地 make ci 全綠、CI 的 ruff-format 紅。）

本 hook 在 push 這個時間點檢查已追蹤檔案是否有未 commit 的改動——因為乾淨的流程
（改 -> CI -> commit -> push）在 push 前必然已經把驗證過的內容 commit 了。刻意不在
「跑完 make ci 當下」檢查：那一刻正常流程與 bug 流程的工作區狀態完全相同，無從分辨。

只看已追蹤檔案（git diff），不看未追蹤檔案：未追蹤檔（產生物、暫存檔）不影響
push 出去的樹，納入只會製造誤報。

Exit code:
  0 -> 放行
  2 -> 攔截（block）並顯示說明

規則來源：~/.claude/CLAUDE.md「Verification Before Claiming Done」
"""

import json
import os
import re
import shlex
import subprocess  # nosec B404
import sys

# Recognized shapes are plain git commands, optional inline assignments / env,
# sudo, subshell parentheses, and command lists separated by ;, &, |, or newline.
# Exotic wrappers and shell constructs (time, env -i, command, if/then, nested
# command substitutions / backticks) are not recognized and currently fall
# through to allow.  The threat model is accidental formatter drift, not an
# adversarial user evading their own guard; adversarial coverage needs a larger
# shell-aware (shlex-based) command parser rewrite rather than more regex cases.
#
# 先寬鬆找出「指令位置」的 git，再對 subcommand 前的每個 token 做白名單分類。
# 如此未知選項不會讓 regex no-match 後靜默放行。
_GIT_COMMAND = re.compile(
    r"(?:^|[;&|(]|\n)\s*"
    r"(?P<prefix>(?:(?:env\s+)?(?:[A-Za-z_]\w*=(?:\"[^\"]*\"|'[^']*'|\S+)\s+)*|sudo\s+))"
    r"git\b(?P<args>[^;&|\n]*)",
    re.MULTILINE,
)
_UNRESOLVABLE_PATH = re.compile(r"['\"$`~()]")
_NOT_A_GIT_REPO = "not a git repository"
_GIT_ENV_KEYS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")
_REPO_CONFIG_KEYS = {"core.worktree", "core.gitdir", "core.bare"}


class GitCheckError(RuntimeError):
    """Git tree state could not be verified safely."""


_GLOBAL_FLAGS = {
    "--bare",
    "--literal-pathspecs",
    "--glob-pathspecs",
    "--noglob-pathspecs",
    "--icase-pathspecs",
    "--no-optional-locks",
    "--no-pager",
    "--no-replace-objects",
    "--paginate",
    "--version",
    "--help",
    "-p",
}
_GLOBAL_OPTIONS_WITH_VALUE = {
    "-C",
    "-c",
    "--config-env",
    "--exec-path",
    "--git-dir",
    "--namespace",
    "--super-prefix",
    "--work-tree",
}


def _push_c_paths(match: re.Match[str]) -> list[str] | None:
    """Return every -C value for a push, or None when this Git command is not a push."""
    try:
        prefix_tokens = shlex.split(match.group("prefix"), posix=True)
        tokens = shlex.split(match.group("args"), posix=True)
    except ValueError as e:
        raise GitCheckError(f"Git push 指令無法靜態解析：{e}") from e

    unsafe_selector: str | None = None
    for token in prefix_tokens:
        key, separator, _value = token.partition("=")
        if separator and key in _GIT_ENV_KEYS:
            unsafe_selector = (
                f"無法安全確認 inline {key} 指定的 Git repository；"
                "請移除 repository selector 後再 push。"
            )

    paths: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.rstrip(")") == "push":
            if unsafe_selector is not None:
                raise GitCheckError(unsafe_selector)
            return paths
        if not token.startswith("-"):
            # 第一個非 option token 才是 Git subcommand；其後即使出現 push 也不是 push 指令。
            return None
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
                    raise GitCheckError(f"Git 全域選項缺少參數：{option}")
                value = tokens[index]
            if option == "-C":
                paths.append(value)
            elif option in {"--git-dir", "--work-tree"}:
                unsafe_selector = f"無法安全重現會改變目標工作樹的 Git 選項：{option}"
            elif option == "--config-env":
                unsafe_selector = (
                    "無法安全確認 --config-env 是否會改變 Git repository；"
                    "請移除 repository selector 後再 push。"
                )
            elif option == "-c":
                config_key = value.partition("=")[0].lower()
                if config_key in _REPO_CONFIG_KEYS:
                    unsafe_selector = (
                        f"無法安全確認 -c {config_key} 指定的 Git repository；"
                        "請移除 repository selector 後再 push。"
                    )
            index += 1
            continue
        # push 前出現非白名單 token，無法證明它不會影響目標樹。
        raise GitCheckError(f"無法辨識 git push 前的選項：{token}")
    return None


def _resolve_git_cwd(paths: list[str], base_cwd: str) -> str:
    """Resolve repeated literal -C paths using Git's cumulative semantics.

    Each relative -C is relative to the preceding location; an absolute path resets
    the base. Shell-expanded or quoted paths are deliberately rejected because the
    hook cannot reproduce shell evaluation safely and guessing would fail open.
    """
    if not paths:
        return os.path.realpath(base_cwd)
    if any(_UNRESOLVABLE_PATH.search(path) for path in paths):
        raise GitCheckError(
            "無法靜態解析 git -C 路徑，無法確認目標工作樹；"
            "路徑含 ()、~、$、引號或反引號時，請改用可靜態解析的絕對路徑。"
        )

    cwd = os.path.realpath(base_cwd)
    for path in paths:
        # Git 會依序 chdir；每段都 realpath 才能保留 symlink 後續 '..' 的語意。
        cwd = os.path.realpath(os.path.join(cwd, path))
    return cwd


def _dirty_tracked_files(cwd: str | None = None) -> list[str]:
    """回傳有未 commit 改動的已追蹤檔案（unstaged + staged）。

    --cached 之外再跑一次無 flag 版本，是為了同時涵蓋「已 stage 但未 commit」——
    兩者都會讓 push 出去的樹與工作區不一致。
    """
    env = os.environ.copy()
    for key in _GIT_ENV_KEYS:
        env.pop(key, None)
    env["LC_ALL"] = "C"

    files: list[str] = []
    for args in (["git", "diff", "--name-only"], ["git", "diff", "--cached", "--name-only"]):
        try:
            result = subprocess.run(  # nosec B603 B607
                args,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
            )
        except OSError as e:
            raise GitCheckError(f"Git 檢查失敗：{e}") from e
        if result.returncode != 0:
            if _NOT_A_GIT_REPO in result.stderr.lower():
                return []  # 真正的非 Git 目錄不屬於本 guard 的保護範圍。
            detail = result.stderr.strip() or f"git 結束碼 {result.returncode}"
            raise GitCheckError(f"Git 檢查失敗：{detail}")
        files.extend(line for line in result.stdout.splitlines() if line)
    return sorted(set(files))


def main() -> None:
    try:
        data = json.load(sys.stdin)
        if data.get("tool_name") != "Bash":
            sys.exit(0)
        command = data.get("tool_input", {}).get("command", "")
        payload_cwd = data.get("cwd")
    except Exception:
        sys.exit(0)

    if not isinstance(command, str):
        sys.exit(0)

    try:
        base_cwd = payload_cwd if isinstance(payload_cwd, str) else os.getcwd()
        found_push = False
        for match in _GIT_COMMAND.finditer(command):
            paths = _push_c_paths(match)
            if paths is None:
                continue
            found_push = True
            cwd = _resolve_git_cwd(paths, base_cwd)
            dirty = _dirty_tracked_files(cwd)
            if dirty:
                break
        else:
            dirty = []
    except GitCheckError as e:
        print(f"[BLOCKED] {e}\n請改用 guard 可靜態確認目標工作樹的 git push 指令。")
        sys.exit(2)
    if not found_push or not dirty:
        sys.exit(0)

    listed = "\n".join(f"    {f}" for f in dirty)
    print(
        "[BLOCKED] 有未 commit 的已追蹤改動，你驗證過的樹不是你要 push 的樹\n"
        "\n"
        f"{listed}\n"
        "\n"
        "若這些是 pre-commit 的 formatter 就地改寫（ruff-format 等），\n"
        "它們沒進 commit，CI 會在同一個 hook 上必然變紅——本地綠是真的，\n"
        "但那個綠來自工作區，不是來自你 push 出去的 commit。\n"
        "\n"
        "出路（擇一）：\n"
        "  1. 這些改動該進 PR：git add <files> && git commit\n"
        "  2. 這些是無關的 WIP：git stash 之後再 push\n"
        "\n"
        "規則來源：~/.claude/CLAUDE.md「Verification Before Claiming Done」"
    )
    sys.exit(2)


if __name__ == "__main__":
    main()

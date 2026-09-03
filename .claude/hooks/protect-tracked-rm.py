#!/usr/bin/env python3
# <!-- verified: probe -->
"""PreToolUse hook：防止遞迴 rm 刪除 Git 已追蹤內容。

Exit codes:
  0 -> 放行
  2 -> 攔截，並把原因輸出到 stdout 與 stderr

設計重點：
  - 以 ``git ls-files`` 查詢追蹤狀態，不把 ``git status`` 當成追蹤清單。
  - 探測結果是三態：有追蹤內容、確認沒有追蹤內容、無法確認。
  - 無法解析指令或無法完成 Git 探測時，一律明確攔截並把診斷寫到 stderr。

Known limitations（靜態分析仍可被刻意繞過，或已知的解析邊界）：
  - shell alias、函式、變數形式的執行檔名稱，以及刻意混淆後交給 eval 的指令無法完整展開。
  - 外部 script、Python、find -delete 等間接刪除方式不在本 hook 的 rm 掃描範圍。
  - tokenizer 不模擬完整 Bash 展開；明顯的 command substitution、glob 或動態目標會保守攔截，
    但刻意拆散或編碼後才在執行期組出的 rm 仍可能避開靜態分析。
  - Git 探測與真正執行 rm 之間仍有 TOCTOU 時窗；本 hook 不是檔案系統層的強制鎖。
  - 本 hook 只保護 Git 已追蹤內容；未追蹤或 gitignored 內容仍可能無法復原。
  - 若 target 是非 Git 目錄、但內含更深層的 nested repo/worktree，本 hook 不會遞迴列舉其 index
    （即使該非 Git 目錄本身被判定為「確認未追蹤」）——見 PR #418 Accepted Residual Risks。
  - wrapper 的罕見或平台特定 option 組合可能無法正確定位真正執行檔；無法分類但看得出
    遞迴 rm 意圖時會 block，刻意混淆後仍可能繞過。
  - symlink 路徑解析僅在 `cd <symlink> && rm -rf ../<target>` 這個特定情境做保守攔截；
    其餘穿越 symlink 的情境（rm target 字串本身以 symlink 元件開頭、`cd <symlink>` 後接
    一般相對路徑〔無 `..`〕、target 字串中間夾帶 `<symlink>/../`）均僅做 lexical 路徑展開，
    不會對中間的 symlink 元件做 realpath 解析，可能誤判為未追蹤而放行。
  - `env -S '<command>'` 的值視為不透明字串直接略過，不會遞迴解析或掃描其中是否含遞迴 rm。
  - `env -C<dir>`／`sudo -D<dir>` 等短選項貼著寫值（無空格）的形式目前不會被解析為目錄選項，
    後續的 rm target 會對呼叫端原本的 cwd解算，而非該 wrapper 指定的目錄。
  - `sudo --chroot=<dir>` 僅被當成 cwd 變更處理；inner command 的絕對路徑 target 仍對照
    host 根目錄解算，而非該 chroot 內的根目錄。
  - GNU `rm` 允許 `--recursive` 的唯一前綴縮寫（如 `--re`、`--rec`）；本 hook 目前只精確比對
    `--recursive` 全稱，縮寫形式不會被辨識為遞迴旗標。
  - `eval <command>`（不加引號、多個獨立 token）在語意上等同於把這些 token 以空白重組後
    再執行，但本 hook 的間接執行器文字掃描是逐一 token 比對正則，不會重組後再掃描——
    `eval rm -rf x`（不加引號）可能不會被偵測為遞迴 rm，即使等價的 `eval 'rm -rf x'`
    （加引號）會被正確攔截。
  - `cd` 出現在條件式（`&&`/`||`）中「不保證會執行」的分支、或管線（`|`，於 subshell 執行
    不外洩）以外的其他非保證執行情境時，cwd 追蹤可能與 Bash 實際的條件執行語意不完全一致。
  - `command cd <dir>`、`pushd <dir>`、`builtin cd <dir>` 目前不會被辨識為 `cd`，cwd 追蹤
    對這些形式維持呼叫端原本的目錄，可能導致後續 target 對錯誤的目錄解算。
  - 間接執行器（`bash -c`／`eval`）文字掃描與 wrapper 選項無法分類時的保守文字掃描
    （`has_visible_recursive_rm`）皆為粗粒度的字面比對，可能對特定內容（如檔名恰好含
    連字號後接 r/R 字元、或長選項名稱含 r/R 字母）產生安全方向的過度攔截（誤擋正常操作），
    但不影響安全性本身。
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from pathlib import Path

_GIT_TIMEOUT_SECONDS = 1.0
_NOT_A_REPOSITORY = "not a git repository"
_GIT_ENV_KEYS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")

_PUNCTUATION = ";&|(){}<>\n"
_SEPARATORS = frozenset((";", "&", "&&", "||", "|"))
_CONTROL_PREFIXES = frozenset(("!", "if", "then", "elif", "else", "while", "until", "do"))
_HEADER_PREFIXES = frozenset(("for", "case", "select"))
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_REDIRECTION_RE = re.compile(r"^\d*(?:>>?|<<?|<>|>&|<&).*")
_REDIRECTION_OPERATOR_RE = re.compile(r"^\d*(?:>>?|<<?|<>|>&|<&)$")
_DYNAMIC_TARGET_RE = re.compile(r"[$`*?\[]")
_INDIRECT_EXECUTORS = frozenset(("bash", "eval", "sh", "zsh"))
_RM_SUBCOMMAND_TOOLS = frozenset(("git", "svn", "hg", "pnpm", "cargo", "docker", "podman"))
_RECURSIVE_RM_TEXT_RE = re.compile(r"(?:^|[;&|(){}\s])(?:\S*/)?rm\b\s+[^;|(){}]*-\w*[rR]\w*")

_WRAPPERS = frozenset(
    (
        "command",
        "env",
        "exec",
        "ionice",
        "nice",
        "nohup",
        "parallel",
        "setsid",
        "stdbuf",
        "sudo",
        "time",
        "timeout",
        "watch",
        "xargs",
    )
)

_WRAPPER_OPTIONS_WITH_VALUE: dict[str, frozenset[str]] = {
    "env": frozenset(("-C", "--chdir", "-S", "--split-string", "-u", "--unset")),
    "ionice": frozenset(
        ("-c", "--class", "-n", "--classdata", "-p", "--pid", "-P", "--pgid", "-u", "--uid")
    ),
    "nice": frozenset(("-n", "--adjustment")),
    "parallel": frozenset(("-I", "-n", "--max-args", "-P", "--jobs")),
    "stdbuf": frozenset(("-i", "--input", "-o", "--output", "-e", "--error")),
    "sudo": frozenset(
        (
            "-C",
            "--close-from",
            "-D",
            "--chdir",
            "-g",
            "--group",
            "-h",
            "--host",
            "-p",
            "--prompt",
            "-R",
            "--chroot",
            "-r",
            "--role",
            "-t",
            "--type",
            "-T",
            "--command-timeout",
            "-u",
            "--user",
        )
    ),
    "timeout": frozenset(("-k", "--kill-after", "-s", "--signal")),
    "watch": frozenset(("-n", "--interval")),
    "xargs": frozenset(("-I", "-n", "--max-args", "-P", "--max-procs")),
}

_WRAPPER_CWD_OPTIONS: dict[str, frozenset[str]] = {
    "env": frozenset(("-C", "--chdir")),
    "sudo": frozenset(("-D", "--chdir", "-R", "--chroot")),
}


@dataclass(frozen=True)
class RmInvocation:
    """已解析的遞迴 rm 呼叫。"""

    targets: tuple[str, ...]
    cwd: Path


@dataclass(frozen=True)
class TrackedTarget:
    """一個包含 Git 已追蹤內容的 rm 目標。"""

    path: Path
    repo_root: Path
    files: tuple[str, ...]


def _diagnose(message: str) -> None:
    """把 hook 診斷寫到 stderr。"""
    print(f"[FAIL] protect-tracked-rm：{message}", file=sys.stderr)


def _remember_failure(errors: list[str] | None, message: str) -> None:
    """記錄探測失敗，並確保該失敗不會靜默。"""
    if errors is not None:
        errors.append(message)
    _diagnose(message)


def _git_env() -> dict[str, str]:
    """建立不受外部 Git repo-selection 變數污染的環境。"""
    env = os.environ.copy()
    for key in _GIT_ENV_KEYS:
        env.pop(key, None)
    env["LC_ALL"] = "C"
    return env


def _run_git(
    args: list[str], cwd: Path, errors: list[str] | None
) -> subprocess.CompletedProcess[str] | None:
    """執行 Git；任何無法取得答案的狀況都回傳 None 並寫出診斷。"""
    try:
        return subprocess.run(  # nosec B603 B607
            ["git", *args],
            cwd=cwd,
            env=_git_env(),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as e:
        _remember_failure(errors, f"找不到 git 執行檔：{e}")
    except subprocess.TimeoutExpired as e:
        _remember_failure(errors, f"git 探測逾時（{_GIT_TIMEOUT_SECONDS:g} 秒）：{e}")
    except OSError as e:
        _remember_failure(errors, f"無法啟動 git 探測：{e}")
    except subprocess.SubprocessError as e:
        _remember_failure(errors, f"git 子行程失敗：{e}")
    return None


def _nearest_directory(path: Path) -> Path | None:
    """找出 path 本身或最近的既存父目錄，不解析符號連結。"""
    candidate = path
    while True:
        try:
            if candidate.is_dir():
                return candidate
        except OSError as e:
            _diagnose(f"無法檢查路徑 {shlex.quote(str(candidate))}：{e}")
            return None
        if candidate.parent == candidate:
            return None
        candidate = candidate.parent


def _probe_start(path: Path, cwd: Path) -> Path | None:
    """選擇能查詢目標所屬 index 的起始目錄。"""
    try:
        start = path.parent if path.is_symlink() or not path.is_dir() else path
    except OSError:
        start = path.parent
    return _nearest_directory(start if start.is_absolute() else cwd / start)


def _tracked_files_with_root(
    path: str | Path, cwd: str | Path, errors: list[str] | None = None
) -> tuple[Path | None, list[str]] | None:
    """回傳 Git 根目錄與已追蹤檔案；None 表示探測失敗。"""
    base_cwd = Path(cwd)
    target = Path(path)
    if not target.is_absolute():
        target = Path(os.path.abspath(base_cwd / target))

    start = _probe_start(target, base_cwd)
    if start is None:
        _remember_failure(errors, f"找不到可供 Git 探測的父目錄：{shlex.quote(str(target))}")
        return None

    inside = _run_git(["rev-parse", "--is-inside-work-tree"], start, errors)
    if inside is None:
        return None
    if inside.returncode != 0:
        detail = inside.stderr.strip() or f"git 結束碼 {inside.returncode}"
        if _NOT_A_REPOSITORY in detail.lower():
            return None, []
        _remember_failure(errors, f"無法確認 Git worktree：{detail}")
        return None
    if inside.stdout.strip() != "true":
        _remember_failure(errors, f"git rev-parse 回傳非預期結果：{inside.stdout.strip()!r}")
        return None

    root_result = _run_git(["rev-parse", "--show-toplevel"], start, errors)
    if root_result is None:
        return None
    if root_result.returncode != 0:
        detail = root_result.stderr.strip() or f"git 結束碼 {root_result.returncode}"
        _remember_failure(errors, f"無法取得 Git 根目錄：{detail}")
        return None

    root_text = root_result.stdout.strip()
    if not root_text:
        _remember_failure(errors, "git rev-parse 未回傳 Git 根目錄")
        return None
    repo_root = Path(root_text)
    try:
        relative = target.relative_to(repo_root)
    except ValueError:
        _remember_failure(
            errors,
            f"目標 {shlex.quote(str(target))} 不在探測到的 Git 根目錄 "
            f"{shlex.quote(str(repo_root))} 內",
        )
        return None

    pathspec = str(relative) if relative.parts else "."
    listed = _run_git(["--literal-pathspecs", "ls-files", "-z", "--", pathspec], repo_root, errors)
    if listed is None:
        return None
    if listed.returncode != 0:
        detail = listed.stderr.strip() or f"git 結束碼 {listed.returncode}"
        _remember_failure(errors, f"無法列出 Git 已追蹤內容：{detail}")
        return None
    return repo_root, [item for item in listed.stdout.split("\0") if item]


def _tracked_files(
    path: str | Path, cwd: str | Path, errors: list[str] | None = None
) -> list[str] | None:
    """回傳目標內的已追蹤檔案；[] 表示確認沒有，None 表示探測失敗。"""
    result = _tracked_files_with_root(path, cwd, errors)
    if result is None:
        return None
    _repo_root, files = result
    return files


def _split_punctuation(word: str) -> list[str]:
    """把 shlex 合併的 punctuation run 拆成 shell 運算子。"""
    if not word or any(char not in _PUNCTUATION for char in word):
        return [word]
    result: list[str] = []
    index = 0
    while index < len(word):
        pair = word[index : index + 2]
        if pair in ("&&", "||", ";;", ">>", "<<", "<>", ">&", "<&"):
            result.append(";" if pair == ";;" else pair)
            index += 2
            continue
        char = word[index]
        result.append(";" if char == "\n" else char)
        index += 1
    return result


def _tokenize(command: str, errors: list[str] | None = None) -> list[str] | None:
    """以 stdlib shlex tokenize Bash 控制運算子，保留 newline 邊界。"""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=_PUNCTUATION)
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        tokens = [piece for word in lexer for piece in _split_punctuation(word)]
    except ValueError as e:
        _remember_failure(errors, f"無法解析 Bash 指令：{e}")
        return None
    return [word for word in tokens if word]


def _option_name(word: str) -> str:
    """取出 --option=value 的 option 名稱。"""
    return word.split("=", 1)[0]


def _directory_result(raw_target: str, cwd: Path | None) -> Path | None:
    """依目前 cwd 解析切換目錄選項；無法靜態確認時回傳 None。"""
    if _DYNAMIC_TARGET_RE.search(raw_target) or raw_target == "-":
        return None
    target = Path(os.path.expanduser(raw_target))
    if not target.is_absolute():
        if cwd is None:
            return None
        target = cwd / target
    target = Path(os.path.abspath(target))
    try:
        return target if target.is_dir() else cwd
    except OSError:
        return None


def _skip_wrapper_options(
    tokens: list[str], index: int, wrapper: str, cwd: Path | None
) -> tuple[int, Path | None] | None:
    """略過已知 wrapper 選項，回傳實際 command 的索引與有效 cwd。"""
    with_value = _WRAPPER_OPTIONS_WITH_VALUE.get(wrapper, frozenset())
    cwd_options = _WRAPPER_CWD_OPTIONS.get(wrapper, frozenset())
    effective_cwd = cwd
    while index < len(tokens):
        word = tokens[index]
        if wrapper == "env" and _ASSIGNMENT_RE.match(word):
            index += 1
            continue
        if word == "--":
            return index + 1, effective_cwd
        if not word.startswith("-") or word == "-":
            break
        name = _option_name(word)
        index += 1
        if name in with_value:
            if "=" in word:
                option_value = word.split("=", 1)[1]
            else:
                if index >= len(tokens):
                    return None
                option_value = tokens[index]
                index += 1
            if name in cwd_options:
                effective_cwd = _directory_result(option_value, effective_cwd)
    if wrapper == "timeout":
        if index >= len(tokens):
            return None
        index += 1
    return index, effective_cwd


def _command_location(tokens: list[str], cwd: Path | None) -> tuple[int, Path | None] | None:
    """穿透控制字、assignment 與已知 wrapper，定位執行檔與有效 cwd。"""
    index = 0
    while index < len(tokens) and tokens[index] in _CONTROL_PREFIXES:
        index += 1
    if index < len(tokens) and tokens[index] in _HEADER_PREFIXES:
        return None
    while index < len(tokens) and _ASSIGNMENT_RE.match(tokens[index]):
        index += 1

    seen_wrappers: set[int] = set()
    while index < len(tokens):
        executable = os.path.basename(tokens[index])
        if executable not in _WRAPPERS:
            return index, cwd
        if index in seen_wrappers:
            return None
        seen_wrappers.add(index)
        skipped = _skip_wrapper_options(tokens, index + 1, executable, cwd)
        if skipped is None:
            return None
        index, cwd = skipped
        while index < len(tokens) and _ASSIGNMENT_RE.match(tokens[index]):
            index += 1
    return None


def _command_index(tokens: list[str]) -> int | None:
    """穿透控制字、assignment 與已知 wrapper，定位真正執行檔。"""
    location = _command_location(tokens, None)
    return location[0] if location is not None else None


def _rm_targets(tokens: list[str], command_index: int) -> tuple[str, ...] | None:
    """解析遞迴 rm 的 targets；非遞迴 rm 回傳空 tuple，無法判定回傳 None。"""
    recursive = False
    targets: list[str] = []
    options_done = False
    index = command_index + 1
    while index < len(tokens):
        word = tokens[index]
        if _REDIRECTION_RE.match(word):
            index += 1
            if _REDIRECTION_OPERATOR_RE.fullmatch(word) and index < len(tokens):
                index += 1
            continue
        if not options_done and word == "--":
            options_done = True
            index += 1
            continue
        if not options_done and word.startswith("-") and word != "-":
            if word in ("--recursive",) or (
                not word.startswith("--") and any(flag in word[1:] for flag in ("r", "R"))
            ):
                recursive = True
            index += 1
            continue
        targets.append(word)
        index += 1
    if not recursive:
        return ()
    if not targets:
        return None
    if any(_DYNAMIC_TARGET_RE.search(target) for target in targets):
        return None
    return tuple(targets)


def _cd_result(tokens: list[str], cwd: Path) -> Path | None | bool:
    """回傳 cd 後 cwd；False 表示不是 cd，None 表示 cwd 無法靜態確認。"""
    index = 0
    while index < len(tokens) and tokens[index] in _CONTROL_PREFIXES:
        index += 1
    while index < len(tokens) and _ASSIGNMENT_RE.match(tokens[index]):
        index += 1
    if index >= len(tokens) or tokens[index] != "cd":
        return False
    index += 1
    while index < len(tokens) and tokens[index] in ("-L", "-P", "-e", "--"):
        index += 1
    if index >= len(tokens):
        raw_target = "~"
    elif index + 1 != len(tokens):
        return None
    else:
        raw_target = tokens[index]
    return _directory_result(raw_target, cwd)


def _parse_rm_invocations(
    command: str, base_cwd: Path, errors: list[str] | None = None
) -> list[RmInvocation] | None:
    """解析 shell command list，並追蹤每個遞迴 rm 的有效 cwd。"""
    tokens = _tokenize(command, errors)
    if tokens is None:
        return None

    invocations: list[RmInvocation] = []
    current: list[str] = []
    current_cwd: Path | None = base_cwd
    subshell_stack: list[Path | None] = []
    case_stack: list[tuple[bool, int]] = []
    brace_depth = 0

    def has_visible_recursive_rm(command_tokens: list[str]) -> bool:
        """掃描 clause 中仍清楚可見的遞迴 rm 意圖。

        若同一個 clause 在 ``rm`` token 之前已出現已知擁有 ``rm`` 子指令的工具
        （如 ``git``、``pnpm``、``cargo``、``docker``），則該 ``rm`` 視為該工具自己的
        子指令名稱，不是 coreutils 的 rm 執行檔——例如 ``git -C <root> rm -r -- <path>``
        （hook 自己在攔截訊息中建議的復原指令）。對這類子指令套用「clause 內任何位置
        出現 -r flag 即視為遞迴」的保守掃描會誤擋大量正常操作，故整個 clause 略過此檢查。
        """
        if any(os.path.basename(word) in _RM_SUBCOMMAND_TOOLS for word in command_tokens):
            return False
        for position, word in enumerate(command_tokens):
            if os.path.basename(word) != "rm":
                continue
            options = (
                later[1:].lower()
                for later in command_tokens[position + 1 :]
                if later.startswith("-")
            )
            if any("r" in option for option in options):
                return True
        return False

    def is_uncertain_destructive(command_tokens: list[str]) -> bool:
        """判斷無法完整分類的 clause 是否仍帶有遞迴 rm 意圖。"""
        index = _command_index(command_tokens)
        if index is None:
            return has_visible_recursive_rm(command_tokens)
        executable = os.path.basename(command_tokens[index])
        if executable == "rm":
            targets = _rm_targets(command_tokens, index)
            return targets is None or bool(targets)
        if executable in _INDIRECT_EXECUTORS:
            return any(_RECURSIVE_RM_TEXT_RE.search(word) for word in command_tokens[index + 1 :])
        return has_visible_recursive_rm(command_tokens)

    def flush(terminator: str) -> bool:
        nonlocal current_cwd
        if not current:
            return True
        command_tokens = current.copy()
        current.clear()
        if current_cwd is None:
            if is_uncertain_destructive(command_tokens):
                _remember_failure(errors, "先前 cd 的目標無法解析，無法確認 rm 的有效 cwd")
                return False
            return True

        cd_result = _cd_result(command_tokens, current_cwd)
        if cd_result is not False:
            if terminator not in ("|", "&"):
                current_cwd = cd_result
            return True

        location = _command_location(command_tokens, current_cwd)
        if location is None:
            if is_uncertain_destructive(command_tokens):
                _remember_failure(errors, "wrapper 或控制結構無法可靠分類遞迴 rm")
                return False
            return True
        index, command_cwd = location
        executable = os.path.basename(command_tokens[index])
        if executable != "rm":
            if executable in _INDIRECT_EXECUTORS and any(
                _RECURSIVE_RM_TEXT_RE.search(word) for word in command_tokens[index + 1 :]
            ):
                _remember_failure(
                    errors,
                    f"{executable} 將在執行期解析遞迴 rm，無法可靠判定其目標",
                )
                return False
            if is_uncertain_destructive(command_tokens):
                _remember_failure(errors, "wrapper 或控制結構無法可靠分類遞迴 rm")
                return False
            return True
        targets = _rm_targets(command_tokens, index)
        if targets is None:
            _remember_failure(errors, "遞迴 rm 含動態或無法解析的目標")
            return False
        if targets:
            if command_cwd is None:
                _remember_failure(errors, "wrapper 的目錄選項無法解析，無法確認 rm 的有效 cwd")
                return False
            invocations.append(RmInvocation(targets=targets, cwd=command_cwd))
        return True

    for word in tokens:
        if word in _SEPARATORS:
            if not flush(word):
                return None
            continue
        if word == "(":
            if current and is_uncertain_destructive(current):
                _remember_failure(errors, "無法區分 grouping 與遞迴 rm 的動態目標")
                return None
            if not flush(";"):
                return None
            subshell_stack.append(current_cwd)
            continue
        if word == ")":
            if case_stack and case_stack[-1][0] and len(subshell_stack) == case_stack[-1][1]:
                if not flush(";"):
                    return None
                continue
            if not flush(";"):
                return None
            if not subshell_stack:
                _remember_failure(errors, "Bash 指令含未配對的右括號")
                return None
            current_cwd = subshell_stack.pop()
            continue
        if word == "{":
            if current and is_uncertain_destructive(current):
                _remember_failure(errors, "無法區分 grouping 與遞迴 rm 的動態目標")
                return None
            if not flush(";"):
                return None
            brace_depth += 1
            continue
        if word == "}":
            if not flush(";"):
                return None
            if brace_depth == 0:
                _remember_failure(errors, "Bash 指令含未配對的右大括號")
                return None
            brace_depth -= 1
            continue
        if word == "case" and not current:
            case_stack.append((False, len(subshell_stack)))
        elif word == "in" and case_stack and not case_stack[-1][0]:
            case_stack[-1] = (True, case_stack[-1][1])
        elif word == "esac" and case_stack and case_stack[-1][0]:
            case_stack.pop()
        current.append(word)

    if not flush(";"):
        return None
    if subshell_stack or brace_depth:
        _remember_failure(errors, "Bash 指令含未配對的 grouping 符號")
        return None
    return invocations


def _resolve_target(raw_target: str, cwd: Path) -> Path:
    """依有效 cwd 展開 rm target，但不 dereference 符號連結。"""
    expanded = os.path.expanduser(raw_target)
    target = Path(expanded)
    if target.is_absolute():
        return Path(os.path.abspath(target))
    base_cwd = Path(os.path.realpath(cwd)) if ".." in target.parts else cwd
    return Path(os.path.abspath(base_cwd / target))


def _path_kind(path: Path) -> str:
    """回傳適合顯示給使用者的目標類型。"""
    try:
        if path.is_symlink():
            return "符號連結"
        if path.is_file():
            return "檔案"
        if path.is_dir():
            return "目錄"
    except OSError:
        pass
    return "路徑"


def _tracked_target(path: Path, cwd: Path, errors: list[str]) -> TrackedTarget | None | bool:
    """True-like TrackedTarget = 有追蹤內容；False = 無；None = 探測失敗。"""
    tracked = _tracked_files_with_root(path, cwd, errors)
    if tracked is None:
        return None
    root, files = tracked
    if not files:
        return False
    if root is None:
        _remember_failure(
            errors, f"已找到追蹤內容，但無法取得其 Git 根目錄：{shlex.quote(str(path))}"
        )
        return None
    return TrackedTarget(path=path, repo_root=root, files=tuple(files))


def _print_inconclusive(reason: str, target: Path | None = None) -> None:
    """輸出保守攔截訊息。"""
    target_line = f"\n目標：{shlex.quote(str(target))}" if target is not None else ""
    message = (
        "[BLOCKED] 無法確認 Git 追蹤狀態，已保守停止遞迴 rm。\n"
        f"原因：{reason}{target_line}\n\n"
        "請先排除探測或指令解析問題，再重新執行。"
    )
    print(message)
    print(message, file=sys.stderr)


def _print_tracked_block(found: TrackedTarget) -> None:
    """輸出已追蹤內容的攔截訊息與 repo-aware 指引。"""
    kind = _path_kind(found.path)
    listed = "\n".join(f"  {shlex.quote(item)}" for item in found.files[:20])
    if len(found.files) > 20:
        listed += f"\n  ... 另有 {len(found.files) - 20} 個已追蹤項目"
    relative = found.path.relative_to(found.repo_root)
    pathspec = str(relative) if relative.parts else "."
    message = (
        f"[BLOCKED] 遞迴 rm 目標包含 Git 已追蹤內容。\n\n"
        f"目標（{kind}）：{shlex.quote(str(found.path))}\n"
        f"Git 根目錄：{shlex.quote(str(found.repo_root))}\n"
        f"已追蹤項目：\n{listed}\n\n"
        "若確實要從版本庫移除，請由人工確認後使用：\n"
        f"  git -C {shlex.quote(str(found.repo_root))} rm -r -- {shlex.quote(pathspec)}"
    )
    print(message)
    print(message, file=sys.stderr)


def _payload_cwd(data: dict[str, object], tool_input: dict[str, object]) -> Path | None:
    """依 Claude Code payload 取得 invocation cwd。"""
    raw_cwd = data.get("cwd")
    if not isinstance(raw_cwd, str) or not raw_cwd:
        nested_cwd = tool_input.get("cwd")
        raw_cwd = nested_cwd if isinstance(nested_cwd, str) and nested_cwd else None
    if raw_cwd is None:
        try:
            return Path.cwd()
        except OSError as e:
            _diagnose(f"無法取得目前工作目錄：{e}")
            return None
    return Path(os.path.abspath(os.path.expanduser(raw_cwd)))


def _main() -> None:
    """處理一筆 hook payload。"""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, ValueError) as e:
        _diagnose(f"無法讀取 hook payload：{e}")
        sys.exit(0)
    if not isinstance(data, dict) or data.get("tool_name") != "Bash":
        sys.exit(0)
    raw_input = data.get("tool_input")
    if not isinstance(raw_input, dict):
        sys.exit(0)
    tool_input: dict[str, object] = raw_input
    command = tool_input.get("command")
    if not isinstance(command, str) or "rm" not in command:
        sys.exit(0)

    base_cwd = _payload_cwd(data, tool_input)
    if base_cwd is None:
        _print_inconclusive("無法取得 invocation cwd")
        sys.exit(2)

    errors: list[str] = []
    invocations = _parse_rm_invocations(command, base_cwd, errors)
    if invocations is None:
        _print_inconclusive(errors[-1] if errors else "Bash 指令無法可靠解析")
        sys.exit(2)

    for invocation in invocations:
        for raw_target in invocation.targets:
            target = _resolve_target(raw_target, invocation.cwd)
            result = _tracked_target(target, invocation.cwd, errors)
            if result is None:
                _print_inconclusive(errors[-1] if errors else "Git 探測失敗", target)
                sys.exit(2)
            if result is not False:
                _print_tracked_block(result)
                sys.exit(2)
    sys.exit(0)


def main() -> None:
    """執行 hook，未預期錯誤一律保守攔截。"""
    try:
        _main()
    except Exception as e:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        _diagnose(f"hook 發生未預期錯誤：{e}")
        sys.exit(2)


if __name__ == "__main__":
    main()

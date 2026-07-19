#!/usr/bin/env python3
"""PreToolUse hook: push 前擋下「已追蹤但從沒跑過 ruff format」的 Python 檔。

姊妹 hook `pre-push-tree-drift-guard.py` 擋的是**已格式化但沒 commit**（push 前工作區
有未 commit 的 tracked 改動）。本 hook 補的是**另一半、且它抓不到**的缺口：內容**已經
進 commit、但當初從沒跑過 ruff format**——此時 `git diff` 乾淨，tree-drift-guard 放行，
CI 端 `pre-commit run --all-files` 的 ruff-format 卻必然紅（就地改檔 → files were modified）。

這條路徑的成因（實例 yibi-stack PR #272，及其前身 PR #239 / #207 的同類復發）：

    fresh `git worktree add` 的 worktree 裡 commit **不觸發** pre-commit hook
    -> 未 ruff format 的新 .py 直接進 commit -> 本地看起來乾淨 -> push -> CI 紅

被動記錄（CLAUDE.md gotcha、typed lesson）已證明攔不住反覆復發，故改由本 hook 在 push
這個 CI-gate 時間點主動阻擋：對**已追蹤的 .py**（`git ls-files`）跑 `ruff format --check`，
有任何檔案會被重格式化就 block。

只掃**已追蹤**檔案（`git ls-files`），不掃未追蹤檔：這正是 CI 的 `pre-commit --all-files`
所看的集合（pre-commit 對 `git ls-files` 取檔，不含未追蹤檔）。掃整個工作目錄（`.`）會連
未追蹤、非 gitignore 的暫存 .py 一起判紅，製造 push 根本不含這些檔的誤報（姊妹 hook
「只看已追蹤檔案」同一理由）。已知殘留：`ruff --check` 讀的是工作區位元組，非 push refspec
指向的 commit 物件，故「commit 乾淨版本後又在工作區改亂」的少見序列仍可能誤報——這與
姊妹 hook 相同，屬可接受的取捨（鼓勵乾淨工作區）。

Exit code:
  0 -> 放行（非 push、非 git repo、ruff 不可用、無已追蹤 .py、或全部已格式化——一律 fail-open）
  2 -> 攔截（有已追蹤 .py 尚未 ruff format）並顯示清單與出路

規則來源：本 repo `CLAUDE.md` Known Gotchas「`make ci` before `git add` silently skips
         brand-new files」（fresh worktree commit 不觸發 pre-commit 的同類復發）。
"""

import contextlib
import json
import os
import re
import shlex
import subprocess  # nosec B404
import sys

_GIT_ENV_KEYS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")

# 測試 seam：黑盒測試在 tmp_path git repo（無 uv project）裡跑，`uv run ruff` 無法解析
# 專案。設此 env 可覆寫 ruff 指令**前綴**（executable + 子指令 + flag），hook 一律在其後
# 附上已追蹤 .py 清單，讓測試注入 PATH 上的真 ruff 直接掃 tmp repo（用真 ruff 而非 mock，
# 契合姊妹 hook 的測試哲學：mock 只驗證「有照我說的呼叫」，不驗證「我對 ruff 輸出的假設」）。
# production 不設它，一律走專案 pinned 的 `uv run ruff`（版本與 CI 的 pre-commit ruff-format
# 一致，避免 PATH 上某個版本相異的 ruff 判讀與 CI 分歧）。
_RUFF_CMD_ENV = "PRE_PUSH_RUFF_GUARD_CMD"
_DEFAULT_RUFF_CMD = ["uv", "run", "ruff", "format", "--check"]

# subprocess timeout（秒）。內層 ruff 上限必須 <= settings.json 的 hook timeout（120），否則
# harness 會先砍掉整個 hook，內層 timeout 形同虛設（見 settings.json pre-push-ruff-format-guard
# 的 "timeout": 120，特意給 fresh worktree 冷啟 `uv run` 足夠 headroom）。
_RUFF_TIMEOUT = 110
_GIT_TIMEOUT = 15

# 與 pre-push-tree-drift-guard 同一威脅模型：防的是「意外把未格式化的 commit push 出去」，
# 不是對抗使用者刻意繞過自己的 guard。故只需辨識常見 git 指令形狀（inline env / sudo /
# 指令串），exotic wrapper 落到放行分支即可。
_GIT_COMMAND = re.compile(
    r"(?:^|[;&|(]|\n)\s*"
    # atomic group `(?>...)`（Python 3.11+）包住 assignment 重複段：一旦匹配就不回溯，
    # 消除 `\S+` 與引號替換 overlap × 外層 `*` 造成的指數 backtracking（CodeQL py/redos）。
    # 每個 iteration 以 `\s+` 分隔、值不跨越空白，故 atomic 不會改變任何合法匹配。
    # 值支援引號形式（`FOO="a b"`），涵蓋帶空白的 inline env（沿用姊妹 hook 的 pattern）。
    r"(?:(?:env\s+)?(?>(?:[A-Za-z_]\w*=(?:\"[^\"]*\"|'[^']*'|\S+)\s+)*)|sudo\s+)"
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
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


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


def _git_env() -> dict[str, str]:
    """複製 environ 並清掉 GIT_DIR/GIT_WORK_TREE 等 selector，鎖定 LC_ALL=C。

    清 selector 避免 hook 執行環境（可能繼承自 git hook 情境）把解析導向別的 repo
    （見 rule 13「GIT_DIR / GIT_WORK_TREE Override」）。
    """
    env = os.environ.copy()
    for key in _GIT_ENV_KEYS:
        env.pop(key, None)
    env["LC_ALL"] = "C"
    return env


def _warn(message: str) -> None:
    """把 fail-open 的原因寫到 stderr，讓「guard 靜默沒跑」變成可診斷（rule 02）。

    診斷輸出本身**絕不可**影響控制流：stderr 已關閉/損壞（BrokenPipeError、OSError）或訊息
    含非 UTF-8 surrogate（UnicodeEncodeError）時 print 會擲例外；`_warn` 幾乎都在 fail-open
    路徑上被呼叫（呼叫端隨後要 exit 0），若讓例外往上傳會反轉成非零退出 → settings.json
    `|| exit 2` → 誤擋。故整段吞掉，寧可少一行診斷也不可影響 push（mob review R2：codex）。
    """
    with contextlib.suppress(Exception):  # 診斷輸出失敗不得影響 fail-open 控制流
        print(f"[WARN] pre-push-ruff-guard: {message}（fail-open，放行 push）", file=sys.stderr)


def _repo_root(base_cwd: str) -> str | None:
    """回傳 base_cwd 所在 repo（或 worktree）的 toplevel；非 git 目錄回傳 None。"""
    try:
        result = subprocess.run(  # nosec B603 B607
            ["git", "rev-parse", "--show-toplevel"],
            cwd=base_cwd,
            env=_git_env(),
            capture_output=True,
            text=True,
            errors="surrogateescape",  # 非 UTF-8 路徑不擲 UnicodeDecodeError
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        _warn(f"git rev-parse 失敗：{e}")
        return None
    if result.returncode != 0:
        return None  # 非 git 目錄：正常、非本 guard 範圍，不必 [WARN]
    root = result.stdout.strip()
    return root or None


def _tracked_py_files(root: str) -> list[str] | None:
    """回傳 repo 內所有**已追蹤**的 .py（相對 root 的路徑）。

    回傳 None 代表 git 查詢失敗（無法判斷）——呼叫端據此 fail-open 放行。
    比照 CI：`pre-commit --all-files` 對 `git ls-files` 取檔，只涵蓋已追蹤檔案；本 hook
    用同一集合，故不會把未追蹤、非 gitignore 的暫存 .py 誤判成 push 內容。
    """
    try:
        result = subprocess.run(  # nosec B603 B607
            ["git", "ls-files", "-z", "--", "*.py"],
            cwd=root,
            env=_git_env(),
            capture_output=True,
            text=True,
            errors="surrogateescape",  # 非 UTF-8 檔名不擲 UnicodeDecodeError
            timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        _warn(f"git ls-files 失敗：{e}")
        return None
    if result.returncode != 0:
        _warn(f"git ls-files 回傳碼 {result.returncode}")
        return None
    return [f for f in result.stdout.split("\0") if f]


def _unformatted_files(root: str) -> list[str] | None:
    """對已追蹤的 .py 跑 `ruff format --check`，回傳會被重格式化的檔案清單。

    回傳 None 代表無法判斷（ruff 不可用 / git 查詢失敗 / 執行失敗）——呼叫端 fail-open 放行。
    回傳 [] 代表全部已格式化（或無已追蹤 .py）。
    """
    tracked = _tracked_py_files(root)
    if tracked is None:
        return None
    if not tracked:
        return []  # 無已追蹤 .py，沒東西可檢查（不可傳空清單給 ruff，否則它會退回掃 `.`）。

    env = _git_env()
    env["NO_COLOR"] = "1"  # ruff 即使輸出到 pipe 仍會上色；關色讓檔名清單乾淨可讀。
    override = env.get(_RUFF_CMD_ENV)
    if override:
        try:
            base_cmd = shlex.split(override)
        except ValueError:
            return None
        if not base_cmd:
            return None
    else:
        base_cmd = list(_DEFAULT_RUFF_CMD)
    # `--` 終止選項解析：名稱像選項的檔案（例如 `-foo.py`）才不會被 ruff 誤判成 flag。
    # 全部路徑單次傳入：已追蹤 .py 數量對真實 repo 遠低於 ARG_MAX；極大 repo 若超限會擲
    # OSError -> 下方 fail-open（附 [WARN]），屬本便利 guard 可接受的殘留（未分批）。
    cmd = base_cmd + ["--"] + tracked
    try:
        result = subprocess.run(  # nosec B603 B607
            cmd,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            errors="surrogateescape",  # 非 UTF-8 路徑不擲 UnicodeDecodeError
            timeout=_RUFF_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        _warn(f"ruff 執行失敗：{e}")
        return None
    if result.returncode == 0:
        return []  # 全部已格式化
    if result.returncode == 1:
        # rc==1 本身即 ruff 的明確「有檔案會被重格式化」判定；一律 block，不因輸出解析
        # 失敗而 fail-open（未來 ruff 改字串 / 改輸出位置也不會靜默漏擋）。
        lines = [
            _ANSI_ESCAPE.sub("", ln).partition("Would reformat:")[2].strip()
            for ln in result.stdout.splitlines()
            if "Would reformat:" in ln
        ]
        return lines or ["(ruff 回報有檔案需要重新格式化；請跑：uv run ruff format .)"]
    # 其他非 0（例如 2 = 用法錯誤 / ruff 不存在於 uv 環境）無法判定 -> fail-open。
    _warn(f"ruff 回傳非預期碼 {result.returncode}")
    return None


def _evaluate() -> list[str]:
    """回傳需要 block 的檔案清單；空 list = 放行。

    所有「非 push / 非 git / 無法判斷」情形都回傳 []。本函式**不**呼叫 sys.exit：任何未預期
    例外交由 main() 統一 fail-open——否則 payload 解析、`-C` 路徑解析（realpath 遇 NUL 擲
    ValueError）、launch cwd 已刪除（getcwd 擲例外）、非 UTF-8 路徑等在 try 外擲例外時，會被
    settings.json 的 `|| exit 2` 反轉成 fail-closed（rule 02 外部資料邊界）。
    """
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return []
    command = data.get("tool_input", {}).get("command", "")
    if not isinstance(command, str):
        return []
    payload_cwd = data.get("cwd")
    base_cwd = payload_cwd if isinstance(payload_cwd, str) and payload_cwd else os.getcwd()

    for target in _push_target_cwds(command, base_cwd):
        root = _repo_root(target)
        if root is None:
            continue  # 非 git 目錄不屬本 guard 範圍
        found = _unformatted_files(root)
        if found:  # None（無法判斷）或 []（全乾淨）都跳過
            return found
    return []


def main() -> None:
    # fail-open 邊界：整段評估（payload 解析、型別驗證、-C 路徑解析、git/ruff 子行程）都包起來。
    # settings.json 以 `... || exit 2` 包裝本 hook，任何未捕捉例外會變 exit 1 -> `|| exit 2`
    # -> 擋 push，與 docstring 承諾的 fail-open 相反。sys.exit 由本函式負責、_evaluate 不自行
    # exit，故真正的 block 判斷不會被 except 吞掉。
    try:
        unformatted = _evaluate()
    except Exception as e:  # noqa: BLE001 -- 便利 guard：任何未預期失敗一律 fail-open
        _warn(f"未預期例外：{e}")
        sys.exit(0)

    if not unformatted:
        sys.exit(0)

    # surrogateescape 讓 tracked 路徑可能含 surrogate 字元；用 backslashreplace 轉成可安全
    # 輸出的字面，避免 print 對非 UTF-8 檔名擲 UnicodeEncodeError（mob review R2：agy）。
    listed = "\n".join(
        f"    {f.encode('utf-8', 'backslashreplace').decode('utf-8')}" for f in unformatted
    )
    # print 以 suppress 包住：block 這個結果由下方 sys.exit(2) 保證，訊息輸出失敗（stdout 損壞
    # / 罕見編碼問題）不得改變「必須擋」的結論，也不可讓例外反轉成別的退出碼。
    with contextlib.suppress(Exception):
        print(
            "[BLOCKED] 有已追蹤但未經 ruff format 的 Python 檔，push 出去 CI 必紅\n"
            "\n"
            f"{listed}\n"
            "\n"
            "這些是 git 已追蹤的 .py，但從沒跑過 ruff format——\n"
            "CI 的 pre-commit（--all-files）會就地改檔並判紅。\n"
            "常見成因：在 fresh git worktree 裡 commit 不觸發本地 pre-commit hook。\n"
            "\n"
            "出路：\n"
            "  uv run ruff format .        # 全樹格式化\n"
            "  git add <上列檔案> && git commit --amend   # 或另開一個 fixup commit\n"
            "  然後重新 push\n"
            "\n"
            "規則來源：本 repo CLAUDE.md Known Gotchas"
            "「make ci before git add silently skips brand-new files」"
        )
    sys.exit(2)


if __name__ == "__main__":
    main()

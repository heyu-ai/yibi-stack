#!/usr/bin/env python3
"""偵測「被 $() 呼叫的 shell function 內含 exit」中**真的會 fail-open** 的那一種。

## 為什麼需要這支 lint

`$(...)` 是 command substitution，跑在 **subshell** 裡。subshell 裡的 `exit` 只結束
subshell，**不會結束腳本**。於是這種寫法：

    _find_ancestor() {
      ...
      if [ "$depth" -gt 100 ]; then
        exit 1            # 作者以為這會中止整個腳本
      fi
    }
    if BROKEN_AT=$(_find_ancestor "$DIR"); then
      ...                 # 沒進來
    fi
    exit 0                # <-- 實際會走到這裡：靜默放行

呼叫端只看到「非零回傳」，會把「無法判定」誤當成「沒找到」而落到放行路徑。

實例（PR #234）：`assert_not_worktree.sh` 的深度上限「保險」自己就是 fail-open——
實測印出了 `[FAIL]` 卻仍 `exit 0`。三個 review voice 都沒抓到，是突變測試抓到的。
它還連帶讓一條測試變成假測試（測試斷言的 exit 0 恰好等於 bug 造成的 exit 0，
兩個 bug 互相抵銷）。

## 判準：不是「有 exit 就報」

光有「exit 在 $() 呼叫的 function 內」**不一定**會 fail-open。`set -e` 會接住裸賦值：

    semver=$(bump_semver "$v" "$t")     # subshell exit 1 -> 賦值非零 -> set -e 中止腳本
                                        # 沒有 fail-open（雖然是被 set -e 意外救到）

真正會 fail-open 的是**呼叫點讓 set -e 不觸發**的那些形式：

    if X=$(fn); then ... fi             # if/elif/while/until 條件 -> set -e 不觸發
    X=$(fn) || RC=$?                    # || -> 非最終位置 -> set -e 不觸發
    X=$(fn) && ...                      # && -> 非最終位置 -> set -e 不觸發
    ! X=$(fn)                           # ! 前綴 -> set -e 不觸發
    local X=$(fn)                       # SC2155: builtin exit 0 蓋掉 $() 的非零

但 `true && X=$(fn)` 的 `$(fn)` 在 AND-OR list **最終位置**——POSIX 規定 set -e
對最終命令仍有效，故不報。

或**腳本根本沒有 set -e / set -o errexit**（此時裸賦值也會繼續往下跑）。

本 lint 只報這些形式，故對 `bump.sh` 那種「裸賦值 + set -e」不吵。
實測基準：對 PR #234 修法前的版本報、對修好後的版本不報、對現有 repo 0 誤報。

## 為什麼要 parse 而不是 regex

regex 分不出三件事，每一件都會造成誤報：

1. `exit` 在 function 內，還是在主 body？（主 body 的 exit 完全正常）
2. 該 function 是被 `$()` 呼叫，還是被直接呼叫？（直接呼叫時 exit 完全正常）
3. 呼叫點有沒有被 `if` / `||` 包住？（決定 set -e 會不會接住）

第 2 點特別容易錯：只搜「函式名有沒有出現在某個 $() 內」會把「$() 裡剛好提到同名字串」
也算進去（例如 `LOG=$(python3 logger.py block ...)` 裡的 `block` 只是引數，該 function
其實是直接呼叫的——見測試 EG-004 的合成案例）。故本 lint 要求函式名是 `$(` 後的
**第一個 token**。

## 限制（誠實標註，勿當成完備）

- 用大括號深度而非完整 bash parser：先移除註解與引號內容再算深度。
- 只認 `name() {` 與 `function name {` 兩種定義形式。
- 只認同檔案內的定義與呼叫；跨檔 source、`eval`、間接呼叫（`$fn`）不追。
- `set -e` 只看檔案前 20 行的 `set -e` / `set -eu` / `set -euo pipefail` / `set -o errexit`。
- backtick 形式 `` X=`fn` `` 不偵測（只認 `$(...)` 語法）。
- `else`/`case` pattern 後的 exit 不特別處理。

## 為什麼預設是 advisory（warn-only）而非 blocking（PR #241 mob review）

PR #241 跨家 mob review 實測指出的 correctness 問題已在 issue #282 修復：

- 誤報（已修）：`&&`/`||` final-position、`set -o errexit` 長式、if-body 呼叫。
- 漏報（已修）：quoted `"$(fn)"`、`local`/`declare`/`export`/`readonly` SC2155。

預設仍為 advisory 直到經實際運行驗證穩定；CI 若要嚴格把關可加 `--fail`。

exit code:
    預設（advisory / warn-only）：一律 exit 0，finding 印到 stderr
        （pre-commit 端配 verbose: true 才會顯示）。
    --fail（opt-in 阻擋，供 CI）：找到至少一個「會 fail-open 的 subshell exit」時 exit 1。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_FUNC_DEF = re.compile(r"^\s*(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(\s*\))?\s*\{")
_EXIT = re.compile(r"(?:^|;|\bthen\b|\bdo\b|&&|\|\|)\s*exit\b")
_SET_E = re.compile(r"^\s*set\s+[^#]*(?:-[a-z]*e|-o\s+errexit)")
_MASKING_BUILTINS = re.compile(r"(local|declare|export|readonly|typeset)\b")


def _strip_noise(line: str) -> str:
    """移除註解與引號內容，避免它們裡面的大括號/exit 干擾判斷。"""
    out: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            i += 1
            continue
        if c == "#" and (not out or out[-1].isspace()):
            break
        out.append(c)
        i += 1
    return "".join(out)


def _strip_single_and_comments(line: str) -> str:
    """去除單引號內容與註解，保留雙引號內容（含 $()）。

    用於 call-site 偵測與 guard 分析：bash 不展開單引號內的 $()，
    但會展開雙引號內的 $()，故需保留後者。
    """
    out: list[str] = []
    in_single = False
    in_double = False
    i = 0
    while i < len(line):
        c = line[i]
        if in_single:
            if c == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if c == "\\" and i + 1 < len(line):
                out.append(c)
                out.append(line[i + 1])
                i += 2
                continue
            if c == '"':
                in_double = False
            out.append(c)
            i += 1
            continue
        if c == "'":
            in_single = True
            i += 1
            continue
        if c == '"':
            in_double = True
            out.append(c)
            i += 1
            continue
        if c == "#" and (not out or out[-1].isspace()):
            break
        out.append(c)
        i += 1
    return "".join(out)


def _has_set_e(lines: list[str]) -> bool:
    for ln in lines[:20]:
        clean = _strip_noise(ln)
        opts = clean.split(" -- ")[0] if " -- " in clean else clean
        if _SET_E.match(opts):
            return True
    return False


def _find_functions(lines: list[str]) -> dict[str, tuple[int, int]]:
    """回傳 {function 名稱: (起始行 index, 結束行 index)}。"""
    funcs: dict[str, tuple[int, int]] = {}
    i = 0
    while i < len(lines):
        clean = _strip_noise(lines[i])
        m = _FUNC_DEF.match(clean)
        if not m:
            i += 1
            continue
        name = m.group(1)
        depth = clean.count("{") - clean.count("}")
        start = i
        j = i
        while depth > 0 and j + 1 < len(lines):
            j += 1
            depth += _strip_noise(lines[j]).count("{") - _strip_noise(lines[j]).count("}")
        funcs[name] = (start, j)
        i = j + 1
    return funcs


def _unguarded_by_set_e(line: str, name: str) -> bool:
    """該行對 `name` 的 $() 呼叫，是否處在「set -e 不會觸發」的位置。

    POSIX：set -e 對 AND-OR list 中**非最後一個**命令不觸發，對
    if/elif/while/until 的條件部分不觸發，對 ``!`` 前綴的命令不觸發。
    """
    call = re.search(rf"\$\(\s*{re.escape(name)}\b", line)
    if not call:
        return False
    before = line[: call.start()]
    after = line[call.end() :]

    kw = re.search(r"\b(if|elif|while|until)\b", before)
    if kw:
        after_kw = before[kw.end() :]
        if not re.search(r";\s*(then|do)\b", after_kw):
            return True

    parts = re.split(r";\s*|\bthen\s+|\bdo\s+", before)
    stmt = parts[-1].lstrip() if parts else ""
    if stmt.startswith("!"):
        return True

    after_stmt = re.split(r";\s*|\bthen\s+|\bdo\s+", after)[0]
    return bool(re.search(r"\|\||&&", after_stmt))


def _masked_by_builtin(line: str, name: str) -> bool:
    """``local``/``declare``/``export``/``readonly``/``typeset`` 的 exit status 蓋掉 $() 的 exit status。

    即使有 set -e，``local X=$(fn)`` 的 exit status 永遠是 ``local`` 本身的 0，
    command substitution 的非零被靜默吞掉（ShellCheck SC2155）。
    """
    call = re.search(rf"\$\(\s*{re.escape(name)}\b", line)
    if not call:
        return False
    before = line[: call.start()]
    parts = re.split(r";\s*|\bthen\s+|\bdo\s+", before)
    stmt = parts[-1].lstrip() if parts else ""
    return bool(_MASKING_BUILTINS.match(stmt))


def check_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"[WARN] 讀不到 {path}：{e}", file=sys.stderr)
        return []
    except UnicodeDecodeError as e:
        print(f"[WARN] 非 UTF-8 編碼 {path}：{e}", file=sys.stderr)
        return []

    lines = text.splitlines()
    has_set_e = _has_set_e(lines)
    funcs = _find_functions(lines)
    findings: list[str] = []

    for name, (start, end) in funcs.items():
        # 找出「把 name 當作 $( 後第一個 token」的呼叫點。
        #
        # 不排除 function 自身內的呼叫（遞迴）：經 $() 遞迴呼叫自己時，那個 exit
        # 在遞迴路徑上同樣只殺 subshell，屬真陽性。
        # 誠實標註：**沒有測試能區分排不排除**——會遞迴又有 exit 的 function，
        # 現實中必然也有外部呼叫點（否則它是死碼），那個外部點自己就會觸發偵測。
        # 早期版本有排除邏輯，突變測試顯示它零覆蓋；檢視後判定它方向錯（會壓掉
        # 遞迴路徑的真陽性）且實務上惰性，故移除以求簡單，而非因為有測試逼它。
        call_sites: list[int] = []
        for idx, raw in enumerate(lines):
            vis = _strip_single_and_comments(raw)
            if re.search(rf"\$\(\s*{re.escape(name)}\b", vis):
                call_sites.append(idx)
        if not call_sites:
            continue

        risky: list[int] = []
        for i in call_sites:
            vis = _strip_single_and_comments(lines[i])
            if not has_set_e or _unguarded_by_set_e(vis, name) or _masked_by_builtin(vis, name):
                risky.append(i)
        if not risky:
            continue

        exit_lines = [i + 1 for i in range(start, end + 1) if _EXIT.search(_strip_noise(lines[i]))]
        if not exit_lines:
            continue

        for exit_ln in exit_lines:
            sites = ", ".join(str(i + 1) for i in risky)
            findings.append(
                f"{path}:{exit_ln}: function `{name}` 內的 `exit` 只會結束 subshell。"
                f"它在第 {sites} 行被 $() 呼叫，且該處 set -e 不會接住"
                f"（if/||/&& 條件位置，或本檔無 set -e），"
                f"呼叫端會把「無法判定」當成「沒找到」而靜默放行。"
                f"改用 return code 表達失敗，由呼叫端逐一分辨。"
            )
    return findings


def main(argv: list[str]) -> int:
    args = argv[1:]
    strict = "--fail" in args  # 預設 advisory（exit 0）；--fail 才阻擋（exit 1），供 CI opt-in
    paths = [Path(a) for a in args if a != "--fail"]
    if not paths:
        return 0

    all_findings: list[str] = []
    for p in paths:
        if p.is_file():
            all_findings.extend(check_file(p))

    if not all_findings:
        return 0

    label = "[FAIL]" if strict else "[WARN]"
    print(f"{label} 偵測到可能會靜默 fail-open 的 subshell exit：", file=sys.stderr)
    for f in all_findings:
        print(f"  {f}", file=sys.stderr)
    print("", file=sys.stderr)
    print("  背景見 .claude/rules/11-skill-authoring.md；實例見 PR #234。", file=sys.stderr)
    print(
        "  本 lint 預設為 advisory（見 module docstring「為什麼預設是 advisory」）。",
        file=sys.stderr,
    )
    return 1 if strict else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

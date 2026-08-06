#!/usr/bin/env python3
"""擋下 SKILL.md / commands 的 shell code fence 內的裸 `$1`-`$9`（issue #386）。

## 為什麼需要機械 gate 而不是一條 rule

skill body 的 argument substitution 會在 agent 讀到之前，把裸 `$N` 換成呼叫端的 argument
token。**磁碟上的檔案完全正確**，所以：

- `grep '\\$1' SKILL.md` 看到的是對的
- 執行 script 時也是對的（script 檔案不經過 substitution 層）
- 只有 agent 讀到的那一份是壞的

損壞還是**部分**的：只有「argument token 數量涵蓋得到」的那幾個會被換掉。以
`/pr-retro --pr 381` 呼叫（2 個 token）為例，`$1` 變成 `381` 而 `$2`-`$7` 原樣留著，範本
看起來大致正常，更難察覺。

實測（Claude Code 2.1.218，拋棄式 repo 探針，帶兩個 argument token 呼叫）：

| 寫法 | 渲染成 |
|------|--------|
| `$1` | `381` |
| `\\$1` | `$1` |
| `${1}` | `${1}` |
| `$7` | `$7`（token 不足） |

## 為什麼建議 `${N}` 而不是 `\\$N`

兩者都通過探針，但 `\\$N` 會讓**原始檔**變成 `local key="\\$1"`——有人直接把原始檔那段複製
到 shell script 時，bash 會把 `"\\$1"` 當成字面字串 `$1`，等於換一種壞法。`${N}` 的原始檔與
渲染結果完全相同，且兩邊都是正確 bash。

`${N}` 不被替換與官方規則一致而非巧合：escape 規則的適用對象是「`$` 後接數字、`ARGUMENTS`、
或已宣告的 argument 名稱」，`${` 的 `$` 後接的是 `{`，不在該集合內。

退出碼：0 = 無違規；1 = 有違規（逐筆列出）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# 只掃 shell 類 fence。其他語言的 `$1`（如 jq、awk、regex backreference）語意不同，
# 且不會被寫成 shell 位置參數使用，納入只會製造誤報。
_FENCE = re.compile(r"```(?:bash|sh|shell|console)\n(.*?)```", re.DOTALL)

# 裸 `$1`-`$9`。三個 negative lookbehind / lookahead 是 gate 的全部精確度來源：
#   (?<!\\)  -> `\$1` 是已跳脫形式，合法，不報
#   (?<!\{)  -> 這裡不會匹配 `${1}`，因為 `$` 後面必須緊接數字；保留此條是防止
#               未來有人把 pattern 放寬成 `\$\{?[1-9]` 時忘了排除 braced form
#   (?![0-9]) -> `$10` 以上不在 substitution 的作用範圍內（官方規則是單一數字），
#               但更重要的是避免把 `$1` 從 `$12` 裡切出來誤報
_BARE_POSITIONAL = re.compile(r"(?<!\\)\$([1-9])(?![0-9])")


def scan_text(text: str) -> list[tuple[int, str]]:
    """回傳 [(1-indexed 行號, 該行內容)]，只含 shell fence 內的違規行。

    純函式，讓失敗路徑可以用合成輸入測試，而不是只能對真實檔案斷言——真實檔案會漂移，
    合成輸入才是負向對照的可靠來源。
    """
    violations: list[tuple[int, str]] = []
    for fence in _FENCE.finditer(text):
        fence_start_line = text[: fence.start(1)].count("\n") + 1
        for offset, line in enumerate(fence.group(1).splitlines()):
            if _BARE_POSITIONAL.search(line):
                violations.append((fence_start_line + offset, line))
    return violations


# 排除路徑一律以「相對於掃描根」判斷，不可拿絕對路徑做子字串比對。
# 在 linked worktree 內執行時，repo 根本身就是 `<main>/.claude/worktrees/<name>`，
# 於是「絕對路徑含 .claude/worktrees」對**每一個**檔案都成立，掃描面會整個歸零而 lint
# 照樣回報乾淨——這正是本 repo 已記載過的同一類錯誤（rule 11 對 assert_not_worktree.sh：
# 「Do not substring-match `.claude/worktrees` — a worktree may be created at any path」）。
_EXCLUDED_PREFIXES: tuple[tuple[str, ...], ...] = (
    (".claude", "worktrees"),
    ("plugins", "cache"),
)


def _is_excluded(rel: Path) -> bool:
    parts = rel.parts
    return any(parts[: len(prefix)] == prefix for prefix in _EXCLUDED_PREFIXES)


def _targets(root: Path) -> list[Path]:
    seen: set[Path] = set()
    for path in root.rglob("*.md"):
        if _is_excluded(path.relative_to(root)):
            continue
        if path.name == "SKILL.md" or "commands" in path.parts:
            seen.add(path.resolve())
    return sorted(seen)


def main(argv: list[str]) -> int:
    paths = [Path(a).resolve() for a in argv] if argv else _targets(Path.cwd())

    total = 0
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            print(f"[FAIL] 無法讀取 {path}：{e}", file=sys.stderr)
            return 1
        for line_no, line in scan_text(text):
            total += 1
            print(
                f"[FAIL] {path}:{line_no} shell fence 內有裸位置參數，"
                f"會被 skill argument substitution 換掉：{line.strip()}",
                file=sys.stderr,
            )

    if total:
        print(
            f"[FAIL] 共 {total} 處。改用 ${{N}} braced form（見 issue #386）——"
            "磁碟上的檔案看起來正確，壞的是 agent 讀到的那一份。",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

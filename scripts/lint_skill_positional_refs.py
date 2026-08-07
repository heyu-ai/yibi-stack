#!/usr/bin/env python3
"""擋下 SKILL.md / commands 的 shell code fence 內會被 substitution 換掉的 `$N`（issue #386）。

## 為什麼需要機械 gate 而不是一條 rule

skill body 的 argument substitution 會在 agent 讀到之前，把裸 `$N` 換成呼叫端的 argument
token。**磁碟上的檔案完全正確**，所以：

- `grep '\\$1' SKILL.md` 看到的是對的
- 執行 script 時也是對的（script 檔案不經過 substitution 層）
- 只有 agent 讀到的那一份是壞的

損壞還是**部分**的：只有「argument token 數量涵蓋得到」的那幾個會被換掉，範本看起來大致
正常，更難察覺。

## 探針結果（Claude Code 2.1.218，拋棄式 repo，`/probe ALPHA BETA GAMMA` 三個 token）

**positional binding 是 0-based**（與官方文件的「`$1` is the first argument」不符；
`.claude/rules/11-skill-authoring.md` 的 "Skill Body — Literal `$` Escape" 已記錄此偏差）。
沒有這個前提，下表的每一行都會被讀成互相矛盾：

| 寫法 | 渲染成 | 這個 lint 的處置 |
|------|--------|------------------|
| `$0` | `ALPHA`（第一個 token） | **擋** —— 0-based 下它是被綁定的位置 |
| `$1` | `BETA`（第二個 token） | **擋** |
| `$9` | `$9`（超出 token 數） | **擋** —— 只是這次沒 token，換個呼叫就會中 |
| `$10` / `$12` | 原樣 | 放行（實測，非從「digit」一詞推論） |
| `$$1` | **`$BETA`** | **擋** —— 內層 `$1` 照樣被換，這是真缺陷不是誤報 |
| `${0}` / `${1}` | 原樣 | 放行 —— 這是本 lint 建議的修法 |
| `\\$1` | `$1` | 放行 —— 官方跳脫形式 |
| `$ARGUMENTS` | `ALPHA BETA GAMMA` | **放行**，見下方「已知未涵蓋」 |

## 為什麼建議 `${N}` 而不是 `\\$N`

兩者都通過探針，但 `\\$N` 會讓**原始檔**變成 `local key="\\$1"`——有人直接把原始檔那段複製
到 shell script 時，bash 會把 `"\\$1"` 當成字面字串 `$1`，等於換一種壞法。`${N}` 的原始檔與
渲染結果完全相同，且兩邊都是正確 bash。

`${N}` 不被替換是**實測結果**（上表），不是官方文件的保證——官方那句話定義的是 backslash
escape 的適用對象，不是 substitution 的 token 文法。

## 已知未涵蓋（刻意，不是疏漏）

- **`$ARGUMENTS`**：實測會被替換，但在 SKILL.md 內它幾乎總是**刻意**使用（skill 就是要拿到
  引數）。擋它會對正確用法開火，故放行。
- **非 shell fence 與 fence 外的 `$N`**：substitution 本身不看 fence（它是對整個 body 的詞法
  掃描），所以本 lint 的 fence 限制純粹是**避免誤報的啟發式**，不是對 substitution 的忠實
  建模。散文寫 `$1` 說明用法是正常的；`python` / `json` / `jq` fence 內的 `$1` 語意不同。
- **`text` fence**：本 repo 確實有 `text` fence 裝 shell 內容（`bash-anti-patterns/SKILL.md`、
  `harness-eval/SKILL.md`），目前皆無 `$N`。未納入是因為 `text` fence 同樣常拿來展示「第一個
  參數是 $1」這類文件，納入會產生誤報。

退出碼（具名結果，不是籠統 PASS/FAIL）：

- `0` = 掃了東西且無違規（stdout 印出掃描檔數，讓綠燈可被證偽）
- `1` = 發現違規（逐筆列出）
- `2` = 工具失敗（掃描面為空、檔案讀不到）——**與「發現違規」分開**，呼叫端才能分辨
  「跑不起來」與「跑了有發現」
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# 視為 shell 的 fence 語言（info-string 的第一個 token）。刻意不含 `text`，理由見 docstring。
_SHELL_LANGS = frozenset({"bash", "sh", "zsh", "shell", "shell-session", "console"})

# fence 開頭：CommonMark 允許 **0-3 個空格**的縮排；4 個以上是 indented code block，
# 其內容是字面文字而非 fence。寫成 `[ \t]*` 會讓一份用縮排展示 fence 寫法的文件被誤掃
# （PR #387 Round 2，codex 與 agy 各自提出，lead 已重現）。
_FENCE_OPEN = re.compile(r"^ {0,3}(?P<delim>`{3,}|~{3,})[ \t]*(?P<info>[^\n]*?)[ \t]*$")

# fence 結尾：**不得帶 info string**（CommonMark）。用開頭的 pattern 兼作結尾判定是
# PR #387 Round 2 的 Critical——` ```text ` 會把一個等長的 ```bash fence 關掉，後續 shell
# 內容整段逃出掃描面（fail-open）。兩家 voice 各自命中，lead 已重現。
_FENCE_CLOSE = re.compile(r"^ {0,3}(?P<delim>`{3,}|~{3,})[ \t]*$")

# 裸 `$0`-`$9`。兩個 lookaround，各有其職：
#   (?<!\\)   -> `\$1` 是官方跳脫形式，合法，不報
#   (?![0-9]) -> `$10` 以上實測不被替換（見 docstring 表），且避免把 `$1` 從 `$12` 切出來誤報
# **刻意不加 `(?<!\$)`**：探針顯示 `$$1` 渲染成 `$BETA`，內層 `$1` 照樣被替換，
# 所以 `$$1` 是真缺陷而非誤報。加上該 lookbehind 會開一個洞。
# braced form `${1}` 不匹配，是因為 `$` 後必須緊接數字而 `${1}` 接的是 `{`——這是 pattern 的
# 自然結果，不需要額外的 lookbehind（若未來把 pattern 放寬成 `\$\{?[0-9]`，必須另外排除
# braced form，否則 LSPR-EG-001 會紅）。
_BARE_POSITIONAL = re.compile(r"\$([0-9])(?![0-9])")


def _is_escaped(line: str, dollar_idx: int) -> bool:
    """`$` 前的反斜線數量是奇數才算被跳脫。

    不能用 `(?<!\\\\)` 單字元 lookbehind：`\\\\$1`（字面反斜線 + `$1`）前一個字元是 `\\`，
    lookbehind 會誤判為已跳脫而放行，但實際上 `$1` 照樣被替換（PR #387 Round 2，agy 提出，
    lead 已重現）。`re` 不支援變長 lookbehind，故改在 Python 端數。
    """
    n = 0
    i = dollar_idx - 1
    while i >= 0 and line[i] == "\\":
        n += 1
        i -= 1
    return n % 2 == 1


def _has_bare_positional(line: str) -> bool:
    return any(not _is_escaped(line, m.start()) for m in _BARE_POSITIONAL.finditer(line))


class ScanError(Exception):
    """工具本身失敗（讀不到檔、掃描面為空），與「發現違規」是不同的結果。"""


def _shell_fence_spans(lines: list[str]) -> list[tuple[int, int]]:
    """回傳 shell fence **內容**的 [(起始行 index, 結束行 index)]（0-based，右開）。

    用逐行狀態機而非跨檔 regex，因為 regex 版本同時會漏報與誤報（PR #387 mob review）：

    - 漏報：`~~~bash`（波浪號分隔符）、` ```bash title="x" `（帶 info-string metadata）、
      ` ```zsh `（語言集太窄）都不會匹配。
    - 漏報：未閉合的 fence 整段被跳過而非報錯。
    - 誤報：外層四反引號 fence 內含 ```bash **字面示例**時，regex 會把內層當成真 fence 掃描。
      狀態機以「分隔符字元相同且長度 >= 開頭長度」判定關閉，內層較短的分隔符無法關閉外層，
      故字面示例被正確地留在外層內容裡。
    """
    spans: list[tuple[int, int]] = []
    open_delim: str | None = None
    open_is_shell = False
    content_start = 0

    for i, line in enumerate(lines):
        if open_delim is None:
            m = _FENCE_OPEN.match(line)
            if m:
                open_delim = m.group("delim")
                info = m.group("info").strip()
                # info string 的第一個 token 才是語言（`bash title="x"` -> `bash`）
                lang = info.split()[0].lower() if info else ""
                open_is_shell = lang in _SHELL_LANGS
                content_start = i + 1
            continue

        # 已在 fence 內：關閉條件是「同字元、長度 >= 開頭、**且不帶 info string**」。
        # 少了最後一項，` ```text ` 會關掉等長的 ```bash fence，後續內容整段逃出掃描。
        close = _FENCE_CLOSE.match(line)
        if (
            close
            and close.group("delim")[0] == open_delim[0]
            and len(close.group("delim")) >= len(open_delim)
        ):
            if open_is_shell:
                spans.append((content_start, i))
            open_delim = None
            open_is_shell = False

    # 未閉合的 shell fence：把剩餘內容納入掃描，而不是靜默跳過整段
    if open_delim is not None and open_is_shell:
        spans.append((content_start, len(lines)))

    return spans


def scan_text(text: str) -> list[tuple[int, str]]:
    """回傳 [(1-indexed 行號, 該行內容)]，含**每一個** shell fence 內的**每一個**違規行。

    純函式，讓失敗路徑可以用合成輸入測試——真實檔案會漂移，合成輸入才是可靠的對照。
    """
    lines = text.splitlines()
    violations: list[tuple[int, str]] = []
    for start, end in _shell_fence_spans(lines):
        for idx in range(start, end):
            if _has_bare_positional(lines[idx]):
                violations.append((idx + 1, lines[idx]))
    return violations


# 排除路徑一律以「相對於掃描根」判斷，不可拿絕對路徑做子字串比對。
# 在 linked worktree 內執行時，repo 根本身就是 `<main>/.claude/worktrees/<name>`，
# 於是「絕對路徑含 .claude/worktrees」對**每一個**檔案都成立，掃描面會整個歸零而 lint
# 照樣回報乾淨。rule 11 對 assert_not_worktree.sh 記載的是同一句判準（「Do not
# substring-match `.claude/worktrees` — a worktree may be created at any path」），
# 但失效方向相反：那裡是 worktree 位於任意路徑導致漏擋，這裡是**在 worktree 內執行**
# 導致掃描面塌陷。
#
# `("plugins", "cache")`：本 repo 的 plugin cache 在 `~/.claude/plugins/cache/`，不在掃描根
# 之下，故此條目前不會命中。保留是為了讓掃描根被指向 home 或其他 checkout 時仍安全。
_EXCLUDED_PREFIXES: tuple[tuple[str, ...], ...] = (
    (".claude", "worktrees"),
    ("plugins", "cache"),
)

# 掃描面下限。低於此值代表排除規則或 traversal 出錯導致掃描面塌陷——那時的「零違規」
# 沒有資訊量，必須 fail loud 而不是回報乾淨。本 repo 現況為 59 個目標。
#
# **已知殘餘（PR #387 Round 2，agy 提出）**：這是**粗糙的絆線，不是完整性保證**。
# 部分塌陷只要仍高於下限就偵測不到——例如 repo 長到 100 個目標、一條錯的排除規則砍掉 75 個，
# 剩下的 25 仍 >= 20 而放行。之所以仍採固定下限而非結構不變量（如「`skills/` 與 `commands/`
# 都必須有產出」），是因為本 script 也會被指向任意 cwd 執行，那時要求特定目錄存在會變成誤報。
# 這個取捨的方向是刻意的：寧可漏掉部分塌陷，也不要對合法用法開火。
_MIN_SCAN_SURFACE = 20


def _is_excluded(rel: Path) -> bool:
    parts = rel.parts
    return any(parts[: len(prefix)] == prefix for prefix in _EXCLUDED_PREFIXES)


def _targets(root: Path) -> list[Path]:
    seen: set[Path] = set()
    for path in root.rglob("*.md"):
        if _is_excluded(path.relative_to(root)):
            continue
        if path.name == "SKILL.md" or "commands" in path.parts:
            # `.resolve()` 去重：repo-root 的 commands/*.md 多為指向 plugins/ 的 symlink，
            # 不去重會讓同一個實體檔案被回報兩次、`total` 灌水。
            seen.add(path.resolve())
    return sorted(seen)


def _collect(root: Path) -> list[Path]:
    paths = _targets(root)
    if len(paths) < _MIN_SCAN_SURFACE:
        raise ScanError(
            f"掃描面只有 {len(paths)} 個檔案（下限 {_MIN_SCAN_SURFACE}），"
            f"疑似排除規則或 traversal 讓掃描面塌陷；cwd={root}。"
            "空掃描面的「零違規」沒有資訊量，故不回報乾淨。"
        )
    return paths


def main(argv: list[str]) -> int:
    try:
        paths = [Path(a).resolve() for a in argv] if argv else _collect(Path.cwd())
    except ScanError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2

    violations: list[tuple[Path, int, str]] = []
    read_errors: list[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as e:
            # UnicodeError 必須與 OSError 一起接：`read_text(encoding="utf-8")` 對含 0xff 的
            # 檔案會丟 UnicodeDecodeError（是 ValueError 不是 OSError），逸出後變成 traceback
            # 並以 exit 1 結束——把工具失敗混進「發現違規」（PR #387 Round 2，codex 提出）。
            # 累積後繼續：中途 return 會讓後面的檔案完全沒被看過，而呼叫端只看到 exit 1，
            # 分不出「工具跑不起來」與「找到違規」。
            read_errors.append(f"{path}: {e}")
            continue
        for line_no, line in scan_text(text):
            violations.append((path, line_no, line))

    for path, line_no, line in violations:
        print(
            f"[FAIL] {path}:{line_no} shell fence 內有裸位置參數，"
            f"會被 skill argument substitution 換掉：{line.strip()}",
            file=sys.stderr,
        )

    # 修法建議要在 read_errors 的 early return **之前**印，否則同時有讀取失敗與違規時，
    # 使用者只看到讀取失敗、拿不到怎麼修違規的指引（PR #387 Round 2 NIT，agy 提出）。
    if violations:
        print(
            f"[FAIL] 共 {len(violations)} 處。改用 ${{N}} braced form（見 issue #386）——"
            "磁碟上的檔案看起來正確，壞的是 agent 讀到的那一份。"
            "若該 `$N` 屬於 awk / jq / sed 而非 shell 位置參數，改用跳脫形式 \\$N。",
            file=sys.stderr,
        )

    for err in read_errors:
        print(f"[FAIL] 無法讀取 {err}", file=sys.stderr)

    if read_errors:
        # 工具失敗優先於違規：exit 2 表示「沒跑完」，呼叫端不可把它讀成「跑完且有 N 個違規」。
        print(
            f"[FAIL] {len(read_errors)} 個檔案讀取失敗——工具未能完整執行，"
            "此結果不可當成「無違規」，也不可當成「違規只有上列這些」。",
            file=sys.stderr,
        )
        return 2

    if violations:
        return 1

    # 印出掃描檔數，讓綠燈可被證偽——「零違規」與「什麼都沒掃」必須看得出差別。
    print(f"[OK] 掃描 {len(paths)} 個檔案，無裸位置參數。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""Lint：新增的 rule 檔 / hook 必須帶「證據標記」與「機械化宣告」，否則以非零 exit 失敗。

`/pr-retro` 可能把未驗證的教訓寫成新 `.claude/rules/*.md` 或新 `.claude/hooks/*`。
本 lint 是 write-time gate 之外的第二道防線，跑在兩個地方：pre-commit（讀 git-staged diff）
與 CI（讀 PR / push 的 commit range，見下方「用法」）。它做**兩組互相獨立**的檢查，誰也不能
代替誰：

1. 證據標記（`check_rule_evidence` / `warn_rule_evidence`）——這條教訓為真嗎？分層強制：
   - 新增 `.claude/rules/*.md` 檔、新增 `.claude/hooks/**` script（含子目錄），或既有
     `.pre-commit-config.yaml` / `.claude/settings.json` 新註冊 hook → 缺標記即 **error**
     （pre-commit 端擋 commit；CI 端讓 job 失敗）。
   - 既有 rule 檔或 `CLAUDE.md` 新增 section（diff 中出現新的 `##` / `###` heading）→ 缺標記即
     **warn-only**（不擋；pre-commit 端需設 `verbose: true` 才看得到警告，CI 端本腳本直接寫
     stderr、無需該設定。起步期漸進，避免龐大歷史 corpus 一次爆紅）。**「warn-only」只指這一層
     證據標記**；下面的機械化宣告沒有 warn 層。
2. 機械化宣告（`check_rule_mechanization`）——為什麼它是 rule 而不是 gate？`.claude/rules/*.md`
   （新檔或既有檔）每個新增的 `##` / `###` section 必須恰好有一個宣告：
   `<!-- gate: <repo 相對路徑>[::<symbol>] -->`（連到既有機械 gate）或
   `<!-- gate: none (reason: <列舉值>) — <說明> -->`（無法機械化的豁免）。缺宣告與假宣告
   （dangling / 不合格的連結、列舉外的 reason、說明少於 12 個非空白字元、同 section 兩個宣告）
   一律 **error**，不分新檔或既有檔、沒有 warn 層。細節見 rule 11 與
   `openspec/changes/add-rule-mechanization-gate/`。

接受的證據標記（擇一，且必須出現在「自身即為標記」的行——不計入 table row `|...` 或
fenced code block ```...``` / `~~~...~~~` 內的文字，避免把「範例說明」誤判為真實證據）：
- 結構化：`<!-- verified: probe -->`、`<!-- verified: incident PR#NNN -->`
- prose 慣例：`Probed.`、`verified on <tool> <version>`、`(Source: PR #NNN`

「看不到內容」一律 fail-closed（機械化宣告檢查對 `.claude/rules/` 回 error；證據檢查維持原行為，
不重複回報）：100% 相似度的 rename（沒有 hunk）、沒有 hunk 的 copy、被 git 判為 binary 的新檔、
空的新檔（沒有地方放宣告）。「看不到」不能等於「通過」。

section 的切法（兩組檢查共用 `_sections_in_chunk`）：以新增行中的 `##` / `###` heading 為錨點；
fenced code block 內的 heading 不算；同一個 hunk 移除了同層級 heading 時，新增的 heading 是改標題、
不算新 section。**Setext heading 與縮排 heading 刻意不支援**：`.markdownlint.yaml` 為
`default: true`，MD003（heading 風格一致）會先擋下 ATX 檔案裡的 setext heading，rule 檔也全是 ATX。
因為 diff 以 `--unified=0` 讀取，宣告必須與其 heading 位於同一個 hunk（否則保守地報缺宣告）。

純函式 `check_rule_evidence(diff_text)`、`warn_rule_evidence(diff_text)`、
`check_rule_mechanization(diff_text, read_gate_file)` 供測試以合成 diff 呼叫——這是關鍵：
只對真實檔案斷言的 lint 無法測自己的失敗路徑，「新檔缺標記必回非空」「錨點缺失不空洞通過」
這些負向案例需要純函式入口。

用法：
  python3 scripts/lint_rule_evidence.py                      # 讀 git staged diff（pre-commit）
  python3 scripts/lint_rule_evidence.py --base <A> --head <B>  # 讀 commit range（CI）
  python3 scripts/lint_rule_evidence.py <diff-file>            # 讀檔（測試 / 手動）

三種模式互斥。CI 用 range 模式是因為 CI 上沒有 staged index——`git diff --cached` 在
runner 上永遠是空的，gate 會「跑完、通過、什麼都沒檢查」，正是本 repo 最常見的假綠形狀。

gate 連結的驗證資料來源跟著輸入走（驗的是「將被 commit / 被審查的內容」，不是工作樹）：
staged 模式讀 **index**（`git ls-files --stage`）、range 模式讀 `--head` 的樹（`git ls-tree`）、
positional diff 檔模式沒有 git 脈絡，讀**工作樹**。路徑必須精確指到一個 blob：連到目錄不算存在。

讀 diff 時不受使用者的 git 設定影響：`core.quotePath=false`、`--no-color --no-ext-diff
--no-textconv`、`-M`、固定 `a/` `b/` 前綴（原因見 `_run_git_diff`）。仍被 C-style 引號的特殊字元
路徑（tab、`"` 等）由 `_unquote_c_path` 解碼，解不開即 exit 2。

Exit code:
  0 -> 無 error（可能有 warn，已印到 stderr）
  1 -> 有 error（新檔 / 新 hook / 新註冊 hook 缺證據標記；rule section 缺宣告或宣告為假；
       看不到內容的新 rule 檔：純 rename、copy、binary、空檔）
  2 -> 設定錯誤（引數矛盾、git 不可用、commit 解不開、diff 裡有解不開的引號路徑、
       讀 gate 時 git 失敗或檔案不是「不存在」的 OS 錯誤，或無法執行）
"""

import posixpath
import re
import subprocess  # nosec B404
import sys
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 接受的證據標記（封閉列舉，任一命中即視為該區塊「有證據」）。每個 pattern 錨定到
# docstring 宣稱的確切形式——先前 `verified:` 接受任意後續文字、`verified on` 只要求
# 一個 token，兩者都超出封閉列舉本身宣稱的範圍（Codex R1 + 本檔重新審視發現先前只修了
# table/fence 過濾，沒收窄這兩個 pattern 本身）。
_EVIDENCE_MARKERS = [
    re.compile(r"<!--\s*verified:\s*probe\s*-->", re.IGNORECASE),  # 結構化：probe
    re.compile(r"<!--\s*verified:\s*incident\s+PR#\d+", re.IGNORECASE),  # 結構化：incident
    re.compile(r"\bProbed\.", re.IGNORECASE),  # prose：實測過
    re.compile(r"\bverified on\s+\S+\s+\S+"),  # prose：verified on <tool> <version>（兩個 token）
    re.compile(r"Source: PR #\d"),  # prose：(Source: PR #NNN
]

# `_NEW_RULE_FILE_RE` 不要求數字前綴——「NN-」是命名慣例，不是本檔的把關條件；沒有數字
# 前綴的新 rule 檔（如 `.claude/rules/retro-evidence.md`）過去會同時逃過 error 與 warn 兩層。
_NEW_RULE_FILE_RE = re.compile(r"^\.claude/rules/[^/]+\.md$")
# 允許子目錄（如 `.claude/hooks/lib/foo.py`）——過去單層路徑假設讓巢狀 hook script 逃過檢查。
_NEW_HOOK_FILE_RE = re.compile(r"^\.claude/hooks/.+$")
# 既有 always-loaded 文件面：rule 檔 + CLAUDE.md（rule 11 對 always-loaded 的定義包含兩者）。
_EXISTING_ALWAYS_LOADED_DOC_RE = re.compile(r"^(\.claude/rules/[^/]+\.md|CLAUDE\.md)$")
# diff 新增行中的 section heading（`+## ` / `+### `），錨點 = 新 section。
_ADDED_HEADING_RE = re.compile(r"^\+(#{2,3})\s+(.*)$")

# 既有設定檔新註冊 hook：不看整檔是否為新檔（這兩個檔案本身通常都是既有檔案），
# 而是看新增行是否「看起來像在註冊一個 hook」。
_SETTINGS_JSON_PATH = ".claude/settings.json"
_PRECOMMIT_CONFIG_PATH = ".pre-commit-config.yaml"
_SETTINGS_HOOK_COMMAND_RE = re.compile(r'"command"\s*:\s*"')
_PRECOMMIT_HOOK_ID_RE = re.compile(r"^\s*-\s*id:\s*\S+")


class _FileDiff:
    """一個檔案的 diff：新舊路徑 + 依 hunk（`@@ ... @@`）分組的新增行。

    分 hunk 儲存（而非攤平成單一清單）是刻意的：`_sections_missing_evidence` 需要
    「同一個 hunk 內」的新增 heading 與其後續內容配對，攤平會讓不相關 hunk 的證據
    標記被誤判為屬於前一個 hunk 新增的 heading（false negative，Gemini R1 發現）。
    """

    def __init__(self, old_path: str, new_path: str, unseen: str | None = None) -> None:
        self.old_path = old_path
        self.new_path = new_path
        # 「看不到內容」的檔案：git 輸出沒有 `---`/`+++`/hunk，diff 裡完全沒有內容可檢查。
        # 標記出來，讓各檢查明確決定怎麼處理，而不是靜默看不見它。取值：
        #   "pure_rename"  100% 相似度的 rename（只有 `rename from/to`）
        #   "copy"         沒有 hunk 的 copy（只有 `copy from/to`）
        #   "binary"       `Binary files ... differ`（含 NUL 等被 git 判為二進位的檔案）
        #   "empty"        空的新檔（只有 `new file mode` + `index`）
        self.unseen = unseen
        self.chunks: list[list[str]] = []  # 每個 hunk 一組；元素為新增行內容（不含前綴 `+`）
        # 與 `chunks` 等長：每個 hunk 被移除的 heading 層級（2 或 3），用來辨識「改標題」。
        self.removed_headings: list[list[int]] = []

    @property
    def pure_rename(self) -> bool:
        return self.unseen == "pure_rename"

    @property
    def added_lines(self) -> list[str]:
        """攤平所有 hunk 的新增行——只給不需要 hunk 邊界語意的整檔判定使用
        （如 `check_rule_evidence` 判斷「這個新檔哪裡都沒有證據標記」）。"""
        return [line for chunk in self.chunks for line in chunk]

    @property
    def is_new_file(self) -> bool:
        return self.old_path == "/dev/null"


_REMOVED_HEADING_RE = re.compile(r"^-(#{2,3})\s+")

# git 對特殊字元路徑的 C-style 引號：`\a \b \t \n \v \f \r \" \\` 與三位八進位位元組（`\350\246\217`）。
_C_ESCAPES = {
    "a": 0x07,
    "b": 0x08,
    "t": 0x09,
    "n": 0x0A,
    "v": 0x0B,
    "f": 0x0C,
    "r": 0x0D,
    '"': 0x22,
    "\\": 0x5C,
}


def _unquote_c_path(raw: str) -> str:
    """還原 git 的 C-style 引號路徑；沒有加引號的路徑原樣回傳。

    git 預設（`core.quotePath=true`）會把非 ASCII 與特殊字元的路徑輸出成 `"b/\\350\\246\\217.md"`。
    舊 parser 留著開頭的引號，路徑正則於是對不上，整個檔案對 lint 隱形——所以這裡要嘛正確解碼，
    要嘛 raise `ValueError` 讓 `main()` 以 exit 2 大聲失敗，絕不可原樣放行一個看不懂的路徑。
    """
    if not raw.startswith('"'):
        return raw
    if len(raw) < 2 or not raw.endswith('"'):
        raise ValueError(f"路徑引號沒有正確結尾：{raw}")
    body = raw[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        char = body[i]
        if char != "\\":
            out.extend(char.encode("utf-8"))
            i += 1
            continue
        i += 1
        if i >= len(body):
            raise ValueError(f"路徑結尾有未完成的跳脫：{raw}")
        escape = body[i]
        if escape in "01234567":
            digits = body[i : i + 3]
            if len(digits) != 3 or any(d not in "01234567" for d in digits):
                raise ValueError(f"路徑含不完整的八進位跳脫：{raw}")
            value = int(digits, 8)
            if value > 0xFF:
                raise ValueError(f"路徑含超出位元組範圍的八進位跳脫：{raw}")
            out.append(value)
            i += 3
        elif escape in _C_ESCAPES:
            out.append(_C_ESCAPES[escape])
            i += 1
        else:
            raise ValueError(f"路徑含未知的跳脫 `\\{escape}`：{raw}")
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"路徑不是合法的 UTF-8，無法判定它是不是 rule 檔：{raw}") from e


def _take_quoted(text: str) -> tuple[str, str]:
    """從以 `"` 開頭的字串切出第一個完整的引號 token；回傳 `(token, 其餘)`。"""
    i = 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            return text[: i + 1], text[i + 1 :]
        i += 1
    raise ValueError(f"`diff --git` 標頭的引號沒有結尾：{text}")


def _split_git_header(rest: str) -> tuple[str, str]:
    """`diff --git` 後面的兩個路徑（各自可能被引號）；回傳去掉 `a/` `b/` 前綴後的 `(舊, 新)`。

    只在 binary / 空檔這類沒有 `---`/`+++` 的區塊才需要它。兩半相同（沒有 rename）時以「兩半一致」
    決定分割點，路徑含空白也不會切錯；rename 的路徑改由 `rename from/to` 取得，不依賴這裡。
    """
    if rest.startswith('"'):
        first, remainder = _take_quoted(rest)
        return _strip_diff_path(first), _strip_diff_path(remainder.lstrip(" "))
    candidates = [
        i
        for i in range(len(rest))
        if rest[i] == " " and (rest.startswith("b/", i + 1) or rest.startswith('"b/', i + 1))
    ]
    if not candidates:
        raise ValueError(f"無法從 `diff --git` 標頭切出兩個路徑：{rest}")
    for i in candidates:
        old, new = _strip_diff_path(rest[:i]), _strip_diff_path(rest[i + 1 :])
        if old == new:
            return old, new
    i = candidates[0]
    return _strip_diff_path(rest[:i]), _strip_diff_path(rest[i + 1 :])


class _BlockHeader:
    """一個 `diff --git` 區塊在第一個 hunk 之前的標頭資訊，用來為「沒有 `+++`」的區塊建立記錄。"""

    def __init__(self, git_line: str = "") -> None:
        self.git_line = git_line
        self.rename_from: str | None = None
        self.rename_to: str | None = None
        self.copy_from: str | None = None
        self.copy_to: str | None = None
        self.new_file = False
        self.deleted_file = False
        self.binary = False

    def unseen_record(self) -> "_FileDiff | None":
        """這個區塊沒出現過 `+++` 時，是否仍代表一個「看不到內容」的檔案。"""
        if self.rename_from is not None and self.rename_to is not None:
            return _FileDiff(
                self.rename_from, self.rename_to, "binary" if self.binary else "pure_rename"
            )
        if self.copy_from is not None and self.copy_to is not None:
            return _FileDiff(self.copy_from, self.copy_to, "binary" if self.binary else "copy")
        if not (self.binary or self.new_file):
            return None  # 純 mode 變更、刪除空檔等：沒有新內容，不是本檔要管的形狀
        _, path = _split_git_header(self.git_line)
        old = "/dev/null" if self.new_file else path
        new = "/dev/null" if self.deleted_file else path
        return _FileDiff(old, new, "binary" if self.binary else "empty")


def _parse_diff(diff_text: str) -> list[_FileDiff]:
    """把 unified diff 切成 per-file、per-hunk，收集新增行。純字串解析，不呼叫 git。

    路徑若被 git 以 C-style 引號輸出會先解碼；解不開時 raise `ValueError`（`main()` 轉 exit 2）。
    """
    files: list[_FileDiff] = []
    current: _FileDiff | None = None
    current_chunk: list[str] | None = None
    old_path = ""
    block = _BlockHeader()

    def _flush_unseen() -> None:
        # 這個檔案區塊沒出現過 `+++`（current 仍是 None）：看標頭是否代表一個看不到內容的檔案。
        if current is None:
            record = block.unseen_record()
            if record is not None:
                files.append(record)

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            _flush_unseen()
            current = None
            current_chunk = None
            old_path = ""
            block = _BlockHeader(line[len("diff --git ") :])
            continue
        # 標頭行沒有 `+`/`-`/空白前綴，內容行一定有，所以不會把 diff 內容誤認成標頭。
        if line.startswith("rename from "):
            block.rename_from = _unquote_c_path(line[len("rename from ") :].strip())
            continue
        if line.startswith("rename to "):
            block.rename_to = _unquote_c_path(line[len("rename to ") :].strip())
            continue
        if line.startswith("copy from "):
            block.copy_from = _unquote_c_path(line[len("copy from ") :].strip())
            continue
        if line.startswith("copy to "):
            block.copy_to = _unquote_c_path(line[len("copy to ") :].strip())
            continue
        if line.startswith("new file mode "):
            block.new_file = True
            continue
        if line.startswith("deleted file mode "):
            block.deleted_file = True
            continue
        if line.startswith("Binary files ") and line.endswith(" differ"):
            block.binary = True
            continue
        if line.startswith("--- "):
            old_path = _strip_diff_path(line[4:])
            continue
        if line.startswith("+++ "):
            new_path = _strip_diff_path(line[4:])
            current = _FileDiff(old_path, new_path)
            files.append(current)
            current_chunk = None
            continue
        if line.startswith("@@") and current is not None:
            current_chunk = []
            current.chunks.append(current_chunk)
            current.removed_headings.append([])
            continue
        if current is None or current_chunk is None:
            continue
        # `+++ ` 的尾隨空格是刻意的：diff 內容行本身以 `++` 開頭時（如 `++Probed.`），
        # 加上 diff 的 `+` 前綴會變成 `+++Probed.`——沒有空格，不該被誤判成檔頭。
        if line.startswith("+") and not line.startswith("+++ "):
            current_chunk.append(line[1:])
        elif line.startswith("-"):
            removed = _REMOVED_HEADING_RE.match(line)
            if removed is not None:
                current.removed_headings[-1].append(len(removed.group(1)))
    _flush_unseen()  # 最後一個檔案之後沒有下一個 `diff --git`，要在這裡收尾
    return files


def _strip_diff_path(raw: str) -> str:
    """`a/path` / `b/path` / `/dev/null`（可能被 C-style 引號）-> 正規化路徑。"""
    raw = raw.strip()
    if raw == "/dev/null":
        return raw
    raw = _unquote_c_path(raw)
    if raw.startswith(("a/", "b/")):
        raw = raw[2:]
    return raw


_FENCE_OPEN_RE = re.compile(r"^(`{3,}|~{3,})")


class _FenceTracker:
    """逐行追蹤 fenced code block（``` 與 ~~~，含較長的外層 fence 包住較短的內層）。

    `feed(line)` 回傳這一行是否「屬於 fence」：開關 fence 的那兩行本身與其中間的行都算。
    關閉條件依 CommonMark：只由同一種字元組成、且長度不短於開啟的 fence——所以 ```` 外層
    fence 裡的 ``` 不會提早結束它。縮排不限（list item 內的 fence 也要認得）。
    限制：`--unified=0` 的 hunk 可能只含半個 fence（例如只新增了結尾的 ```），那時狀態會反過來；
    這種輸入本來就看不到完整脈絡，與「宣告必須與 heading 同一個 hunk」是同一類限制。
    """

    def __init__(self) -> None:
        self._marker: str | None = None

    def feed(self, line: str) -> bool:
        stripped = line.strip()
        if self._marker is None:
            match = _FENCE_OPEN_RE.match(stripped)
            # backtick fence 的 info string 不可含 backtick（那是行內 code，如 ```x``` 之類）
            if match is not None and not (
                match.group(1)[0] == "`" and "`" in stripped[len(match.group(1)) :]
            ):
                self._marker = match.group(1)
                return True
            return False
        if len(stripped) >= len(self._marker) and set(stripped) == {self._marker[0]}:
            self._marker = None
        return True


def _evidence_eligible_lines(lines: list[str]) -> list[str]:
    """濾掉 table row（`|` 開頭）與 fenced code block 內的行。

    這兩種脈絡常常「提及」證據標記語法本身當作範例說明（本檔自己的 docstring 表、
    rule 11 的證據形式表都是如此），並非真的宣稱該區塊已驗證——不濾掉的話，任何
    列出標記語法範例的文字都會被誤判為「有證據」。
    """
    eligible: list[str] = []
    fence = _FenceTracker()
    for line in lines:
        if fence.feed(line):
            continue
        if line.strip().startswith("|"):
            continue
        eligible.append(line)
    return eligible


def _has_evidence(lines: list[str]) -> bool:
    blob = "\n".join(_evidence_eligible_lines(lines))
    return any(marker.search(blob) for marker in _EVIDENCE_MARKERS)


def _sections_in_chunk(
    chunk: list[str], removed_levels: list[int] | None = None
) -> list[tuple[str, list[str]]]:
    """單一 diff hunk 內新增的 section：`(heading 標題, 該 section 的新增行含 heading 行)`。

    以新增行中的 heading 為錨點：只有 heading 本身被新增（即新 section）才計入；
    只在既有 section 內新增內容（無新 heading）不產生任何 section。證據檢查與機械化宣告
    檢查共用這個切法，確保兩者對「什麼算一個新 section」的判斷一致。兩個例外：

    - fenced code block 內的 `## ...` 是範例文字，不是 section（逐行追蹤 fence 狀態）。
    - 同一個 hunk 移除了同層級 heading 時，新增的 heading 是「改標題」而不是新 section：
      `removed_levels` 每個被移除的 heading 層級可豁免一個同層級的新增 heading（一對一消耗）。
      層級不同、或沒有成對的移除，仍算新 section。

    Setext heading（`Title\\n=====`）與縮排 heading 刻意不支援：`.markdownlint.yaml` 為
    `default: true`，MD003（heading 風格一致）會先擋下 ATX 檔案裡的 setext heading，且 rule 檔
    全是 ATX；實作它只會增加一條從不被走到的路徑。
    """
    sections: list[tuple[str, list[str]]] = []
    current_heading: str | None = None
    current_block: list[str] = []
    retitle_budget = list(removed_levels or [])
    fence = _FenceTracker()

    def _flush() -> None:
        if current_heading is not None:
            sections.append((current_heading, current_block))

    for line in chunk:
        in_fence = fence.feed(line)
        match = None if in_fence else _ADDED_HEADING_RE.fullmatch("+" + line)
        if match is not None:
            _flush()
            level = len(match.group(1))
            if level in retitle_budget:
                retitle_budget.remove(level)  # 改標題：不是新 section，其後的內文也不歸任何 section
                current_heading = None
                current_block = []
                continue
            current_heading = match.group(2).strip()
            current_block = [line]
        elif current_heading is not None:
            current_block.append(line)
    _flush()
    return sections


def _chunk_sections(fd: "_FileDiff") -> list[tuple[str, list[str]]]:
    """檔案內所有 hunk 的新增 section（逐 hunk 獨立，不跨 hunk 攤平）。"""
    return [
        section
        for chunk, removed in zip(fd.chunks, fd.removed_headings, strict=True)
        for section in _sections_in_chunk(chunk, removed)
    ]


def _sections_missing_evidence(fd: "_FileDiff") -> list[str]:
    """回傳「新增了 heading 但該 section 內無證據標記」的 heading 標題清單。

    逐 hunk 獨立評估（不跨 hunk 攤平）：同一檔案裡兩個不相關的 hunk 若被合併成一個
    清單，後面 hunk 新增的證據標記字串會被誤判成屬於前面 hunk 新增的 heading，讓真正
    缺證據的 section 被錯誤地判定為「有證據」（false negative，Gemini R1 發現）。
    """
    return [heading for heading, block in _chunk_sections(fd) if not _has_evidence(block)]


def _is_newly_protected(old_path: str, new_path: str, protected_re: re.Pattern[str]) -> bool:
    """`new_path` 符合受保護樣式，且 `old_path` 不符合。

    涵蓋兩種情境：真正的新檔（`old_path == "/dev/null"`，必然不符合任何樣式），以及
    從受保護目錄外 rename 進來的既有檔案（`old_path` 是目錄外的路徑，同樣不符合）。
    先前只看 `is_new_file`（`old_path == "/dev/null"`），rename 進來的檔案 `old_path`
    不是 `/dev/null` 所以被當成既有檔案，完全繞過 error gate（Codex + Gemini R1 皆發現）。
    """
    return bool(protected_re.fullmatch(new_path)) and not bool(protected_re.fullmatch(old_path))


def _is_settings_hook_registration(fd: "_FileDiff") -> bool:
    return fd.new_path == _SETTINGS_JSON_PATH and any(
        _SETTINGS_HOOK_COMMAND_RE.search(line) for line in fd.added_lines
    )


def _is_precommit_hook_registration(fd: "_FileDiff") -> bool:
    return fd.new_path == _PRECOMMIT_CONFIG_PATH and any(
        _PRECOMMIT_HOOK_ID_RE.match(line) for line in fd.added_lines
    )


def check_rule_evidence(diff_text: str) -> list[str]:
    """回傳 **error** 訊息清單（空 = 無 error）。

    三種觸發條件皆為 error（擋 commit）：新 rule 檔、新 hook script（含子目錄），
    或既有 `.pre-commit-config.yaml` / `.claude/settings.json` 新註冊的 hook。
    """
    errors: list[str] = []
    for fd in _parse_diff(diff_text):
        if fd.unseen:
            # 沒有內容可檢查（純 rename / copy / binary / 空檔）。進入 .claude/rules/ 者由
            # `check_rule_mechanization` 以 fail-closed 擋下；這裡刻意略過，證據 lint 的既有行為不變，
            # 也避免同一件事被兩個 lint 重複回報。
            continue
        path = fd.new_path
        is_new_rule = _is_newly_protected(fd.old_path, path, _NEW_RULE_FILE_RE)
        is_new_hook = _is_newly_protected(fd.old_path, path, _NEW_HOOK_FILE_RE)
        is_settings_hook = _is_settings_hook_registration(fd)
        is_precommit_hook = _is_precommit_hook_registration(fd)
        if not (is_new_rule or is_new_hook or is_settings_hook or is_precommit_hook):
            continue
        if not _has_evidence(fd.added_lines):
            if is_new_rule:
                kind = "rule 檔"
            elif is_new_hook:
                kind = "hook"
            else:
                kind = "設定檔新註冊 hook"
            errors.append(
                f"{path}：新增的 {kind} 缺少證據標記。"
                "須帶 `<!-- verified: probe -->` / `<!-- verified: incident PR#NNN -->`，"
                "或 prose `Probed.` / `verified on <tool> <version>` / `(Source: PR #NNN`。"
            )
    return errors


def warn_rule_evidence(diff_text: str) -> list[str]:
    """回傳 **warn** 訊息清單；既有 rule 檔 / CLAUDE.md 新增 section 缺證據標記（起步期不擋 commit）。"""
    warns: list[str] = []
    for fd in _parse_diff(diff_text):
        if not _EXISTING_ALWAYS_LOADED_DOC_RE.fullmatch(fd.new_path):
            continue
        if _is_newly_protected(fd.old_path, fd.new_path, _EXISTING_ALWAYS_LOADED_DOC_RE):
            continue  # 新增檔 / rename 進來的既有檔已由 error 層（check_rule_evidence）處理
        for heading in _sections_missing_evidence(fd):
            warns.append(
                f"{fd.new_path}：新增 section「{heading}」缺證據標記（建議補 probe 或 PR cite）"
            )
    return warns


# --- 機械化宣告（rule-mechanization-gate）---
#
# 證據標記回答「這條教訓為真嗎」；機械化宣告回答「為什麼它是 rule 而不是 gate」。兩者互不
# 替代。新增的 rule section 必須帶下列宣告之一（HTML 註解，與證據標記同形）：
#   <!-- gate: <repo 相對路徑>[::<symbol>] -->                      連結到既有機械 gate
#   <!-- gate: none (reason: <理由>) — <說明> -->                  無法機械化的豁免
# 宣告行在 fenced code block 與 table row 內不計（同 `_evidence_eligible_lines`）。

_GATE_DECLARATION_RE = re.compile(r"<!--\s*gate:\s*(.*?)\s*-->")
_EXEMPTION_RE = re.compile(r"none\s*\(\s*reason:\s*([^)]*?)\s*\)\s*(?:—\s*(.*))?")

# 封閉列舉、無 catch-all：新增理由必須改這個常數、spec 與 fixture，這個摩擦是刻意的。
_EXEMPT_REASONS = frozenset({"judgment", "no-observable-signal", "hook-cost"})
# 說明下限（非空白字元）。`TBD` / `TODO` / `N/A` / `none` 這些佔位字樣全都短於它，所以不需要
# 另一份佔位清單：過去那份清單藏在長度檢查之後、永遠走不到（死碼），已移除。
_MIN_EXPLANATION_CHARS = 12

# 合格 gate 的封閉清單。`.claude/rules/` 與 SKILL.md 刻意不在內：rule 指向 rule、或指向
# 一份 runbook，都不是機械化。
_GATE_DIR_PREFIXES = ("scripts/", ".claude/hooks/", ".github/workflows/")
_GATE_EXACT_FILES = frozenset({".pre-commit-config.yaml"})
_GATE_TASKS_TESTS_RE = re.compile(r"^tasks/(?:.+/)?tests/.+")

# 看不到內容的新 rule 檔：每種原因各自的錯誤說明（path 由呼叫端放在前面）。
_UNSEEN_FIX = "diff 看不到內容，無法檢查證據標記與機械化宣告；"
_UNSEEN_REASONS = {
    "pure_rename": (
        "純 rename（100% 相似、沒有內容 hunk）進入 .claude/rules/，"
        + _UNSEEN_FIX
        + "請在同一個 commit 補上兩者，或改成新增檔案"
    ),
    "copy": (
        "純 copy（沒有內容 hunk）進入 .claude/rules/，"
        + _UNSEEN_FIX
        + "請在同一個 commit 補上兩者，或改成新增檔案"
    ),
    "binary": (
        "被 git 判為二進位檔（Binary files differ）的新 rule 檔，"
        + _UNSEEN_FIX
        + "rule 檔必須是文字檔（檢查檔案是否含 NUL 位元組）"
    ),
    "empty": (
        "空的新 rule 檔（沒有任何內容行），沒有地方可以放證據標記與機械化宣告；"
        "請補上內容與宣告，或不要新增空的 rule 檔"
    ),
}

GateReader = Callable[[str], "str | None"]


def _git_bytes(args: list[str]) -> bytes:
    """在 `REPO_ROOT` 跑 git 並回傳 stdout；任何失敗都 raise `OSError`（由 `main()` 轉 exit 2）。

    沒有加 `--literal-pathspecs`：實測它不改變任何輸出（git 的 pathspec 比對本來就會先試字面相等），
    「gate 連結是路徑不是 pattern」這件事由 `_blob_sha` 的精確路徑比對負責，並有突變測試守著。
    """
    cmd = ["git", "-C", str(REPO_ROOT), *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=30)  # nosec B603
    except (OSError, subprocess.SubprocessError) as e:
        raise OSError(f"git {args[0]} 無法執行：{e}") from e
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise OSError(f"git {args[0]} 失敗：{stderr}")
    return proc.stdout


def _blob_sha(ref: str | None, rel_path: str) -> str | None:
    """`ref` 的樹（`None` = index）中「恰為 `rel_path`」的 blob 的 SHA；不存在回 `None`。

    只有路徑不存在是答案；git 本身失敗由 `_git_bytes` raise。精確比對路徑：連到目錄（樹項目或
    其下的檔案）、子模組都不是 gate 檔。
    """
    if ref is None:
        out = _git_bytes(["ls-files", "-z", "--stage", "--", rel_path])
    else:
        out = _git_bytes(["ls-tree", "-z", ref, "--", rel_path])
    for record in out.split(b"\0"):
        if not record:
            continue
        meta, _, raw_path = record.partition(b"\t")
        if raw_path.decode("utf-8", errors="surrogateescape") != rel_path:
            continue
        fields = meta.decode("ascii", errors="replace").split()
        if ref is None:
            mode, sha, stage = fields
            if stage != "0":
                raise OSError(f"index 內 {rel_path} 處於未合併狀態（stage {stage}），無法驗證")
            is_blob = mode != "160000"
        else:
            _, kind, sha = fields
            is_blob = kind == "blob"
        return sha if is_blob else None
    return None


def _git_gate_reader(ref: str | None) -> GateReader:
    """讀 git 物件庫裡的 gate 檔：`ref=None` 讀 index，否則讀該 commit 的樹。

    gate 連結要對「將被 commit / 被審查的內容」驗證，不是對工作樹：只存在於磁碟、沒有 stage 的
    script 在 commit 後就是 dangling link，而已 stage 但磁碟上不在的 script 其實有效。
    介面與 `_read_repo_file` 相同：不存在回 `None`、其他失敗 raise `OSError`。
    """

    def read(rel_path: str) -> str | None:
        sha = _blob_sha(ref, rel_path)
        if sha is None:
            return None
        try:
            return _git_bytes(["cat-file", "blob", sha]).decode("utf-8")
        except UnicodeDecodeError:
            return ""  # 存在但不是文字檔：沒有 symbol 可比對，連結本身仍成立

    return read


def _read_repo_file(rel_path: str) -> str | None:
    """以 `REPO_ROOT` 的**工作樹**讀 gate 檔；不存在回 `None`，其他 OS 錯誤原樣 raise。

    只給 positional diff 檔模式用：那種 diff 不帶 git 脈絡，沒有 index 或 head 可讀，所以讀工作樹
    （這是文件化的行為）。staged 與 range 模式用 `_git_gate_reader`。

    只有「檔案不存在」被當成答案；權限錯誤等代表「無法驗證」，必須讓 `main()` 以 exit 2
    大聲失敗，不可吞成「連結有效」或「連結無效」。
    """
    target = REPO_ROOT / rel_path
    try:
        if target.is_dir():
            return None
        return target.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return None
    except UnicodeDecodeError:
        return ""  # 存在但不是文字檔：沒有 symbol 可比對，連結本身仍成立


def _is_eligible_gate_path(path: str) -> bool:
    if not path or path.startswith("/") or "\\" in path or posixpath.normpath(path) != path:
        return False
    if ".." in path.split("/") or path.rsplit("/", 1)[-1] == "SKILL.md":
        return False
    return (
        path in _GATE_EXACT_FILES
        or path.startswith(_GATE_DIR_PREFIXES)
        or _GATE_TASKS_TESTS_RE.fullmatch(path) is not None
    )


def _link_problem(payload: str, read_gate_file: GateReader) -> str | None:
    path, _, symbol = payload.partition("::")
    if not _is_eligible_gate_path(path):
        return (
            f"gate link `{payload}` 不是合格的 gate 路徑"
            "（限 scripts/、.claude/hooks/、.github/workflows/、.pre-commit-config.yaml、"
            "tasks/**/tests/；rule 檔與 SKILL.md 不算 gate）"
        )
    content = read_gate_file(path)
    if content is None:
        return f"gate link `{payload}` 指向的路徑不存在：{path}"
    if symbol and not re.search(rf"(?<!\w){re.escape(symbol)}(?!\w)", content):
        return f"gate link `{payload}` 指向的檔案內找不到 symbol `{symbol}`：{path}"
    return None


def _exemption_problem(payload: str) -> str | None:
    match = _EXEMPTION_RE.fullmatch(payload)
    if match is None:
        return f"gate 豁免宣告格式錯誤：`{payload}`（應為 none (reason: <理由>) — <說明>）"
    reason, explanation = match.group(1).strip(), (match.group(2) or "").strip()
    if reason not in _EXEMPT_REASONS:
        return (
            f"gate 豁免的 reason `{reason}` 不在封閉列舉內（{', '.join(sorted(_EXEMPT_REASONS))}）"
        )
    compact = re.sub(r"\s+", "", explanation)
    if len(compact) < _MIN_EXPLANATION_CHARS:
        return (
            f"gate 豁免缺少實質說明（少於 {_MIN_EXPLANATION_CHARS} 個非空白字元；"
            "TBD / TODO / N/A / none 這類佔位字樣同樣不足）"
        )
    return None


def _declaration_payloads(block: list[str]) -> list[str]:
    blob = "\n".join(_evidence_eligible_lines(block))
    return [m.group(1).strip() for m in _GATE_DECLARATION_RE.finditer(blob)]


def _declaration_problems(payloads: list[str], read_gate_file: GateReader) -> list[str]:
    if len(payloads) > 1:
        return [f"同一個 section 有 {len(payloads)} 個宣告（互相矛盾或重複），只能有一個"]
    payload = payloads[0]
    problem = (
        _exemption_problem(payload)
        if payload.startswith("none")
        else _link_problem(payload, read_gate_file)
    )
    return [problem] if problem else []


def check_rule_mechanization(diff_text: str, read_gate_file: GateReader) -> list[str]:
    """回傳 **error** 訊息清單（空 = 無 error）。

    三類 error，且**不分新檔或既有檔、不降級成 warn**：
    - 缺宣告：`.claude/rules/*.md` 新增的 section 沒有任何宣告。新檔沒有任何 section 時改要求
      檔案層級宣告，否則整份檔案會逃過檢查。
    - 假宣告：連結指向不存在或不合格的目標、豁免理由不在列舉內、說明為佔位、同 section 多個
      宣告。把它降級成 warn 等於教人亂填通過。
    - 看不到內容：100% 相似度的 rename、沒有 hunk 的 copy、binary 新檔、空的新檔都沒有可讀的
      內容行，進入 `.claude/rules/` 時無從檢查，fail-closed 擋下——「看不到」不能等於「通過」。

    缺宣告原本在既有檔只是 warn（起步期漸進）。改成 error 的代價要說清楚：因為 diff 以
    `--unified=0` 讀取，宣告必須與其 heading 位於**同一個 hunk**；把 heading 插在既有內文
    之上、宣告落在未變動行時，會被擋下。這是刻意的保守誤報，修法是把宣告緊接在 heading 後。

    `read_gate_file(path)` 回傳檔案內容、不存在回 `None`；其他 OS 錯誤原樣 raise，由
    `main()` 轉 exit 2。純函式只透過它碰檔案系統，測試因此能用假檔案系統構造負向案例。
    """
    errors: list[str] = []
    for fd in _parse_diff(diff_text):
        if not _NEW_RULE_FILE_RE.fullmatch(fd.new_path):
            continue
        is_new = _is_newly_protected(fd.old_path, fd.new_path, _NEW_RULE_FILE_RE)
        if fd.unseen:
            # fail-closed：diff 裡沒有任何內容時，宣告與證據都無從檢查。「看不到」不能等於「通過」，
            # 所以擋下並要求同時改動內容。目錄內改名（不是 is_new）是既有檔、不在此列；copy 的來源即使
            # 也在 rules 目錄內，目標仍是一個新檔，所以 copy 不看來源。
            if is_new or fd.unseen == "copy":
                errors.append(f"{fd.new_path}：{_UNSEEN_REASONS[fd.unseen]}")
            continue
        sections = _chunk_sections(fd)
        units = sections or ([("（整份檔案）", fd.added_lines)] if is_new else [])
        for heading, block in units:
            payloads = _declaration_payloads(block)
            if not payloads:
                errors.append(f"{fd.new_path}：新增 section「{heading}」缺少機械化宣告")
                continue
            errors.extend(
                f"{fd.new_path}：section「{heading}」{problem}"
                for problem in _declaration_problems(payloads, read_gate_file)
            )
    return errors


def _run_git_diff(args: list[str], label: str) -> str:
    # 明確指定前綴：使用者全域設了 `diff.mnemonicPrefix=true` 時，`git diff --cached` 會輸出
    # `c/` / `i/` 而非 `a/` / `b/`，`_strip_diff_path` 只認後者，於是所有路徑都對不上、本 lint
    # 在 staged 模式（pre-commit）靜默通過卻什麼都沒檢查（本機實測；range 模式 commit 對 commit
    # 仍是 `a/` `b/`，所以 CI 不受影響，這正是它藏得住的原因）。
    #
    # 其餘幾個旗標同理：lint 讀的是 git 的輸出，使用者的 git 設定不可以改變那份輸出的形狀。
    # - `-c core.quotePath=false`：非 ASCII 路徑照原樣輸出，不被 C-style 引號成 `"b/\350..."`
    #   （仍會引號的特殊字元如 tab、`"` 由 `_unquote_c_path` 解碼）。
    # - `--no-color --no-ext-diff --no-textconv`：`color.ui=always` 會在行首塞 ANSI 碼，
    #   `diff.external` / textconv 會整個換掉輸出；任何一個都讓 `+## heading` 讀不到而靜默通過。
    # - `-M`：`diff.renames=copies` 會讓「複製進 rules 且來源同時被修改」的檔案變成沒有 hunk 的
    #   `copy from/to`；明確的 `-M` 讓 git 改輸出一般的新檔 diff。不用 `--no-renames`：它會把
    #   目錄內的純 rename 變成一個沒宣告的新檔，反而誤擋（AC-10 要求目錄內改名不報錯）。
    cmd = [
        "git",
        "-C",
        str(REPO_ROOT),
        "-c",
        "core.quotePath=false",
        "diff",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "-M",
        "--unified=0",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        *args,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)  # nosec B603
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"{label} 無法執行：{e}") from e
    if proc.returncode != 0:
        raise RuntimeError(f"{label} 失敗：{proc.stderr.strip()}")
    return proc.stdout


def _staged_diff() -> str:
    return _run_git_diff(["--cached"], "git diff --cached")


def _range_diff(base: str, head: str) -> str:
    """`base...head`（**三點**）的 unified diff。

    三點而非兩點是刻意的：GitHub 的 `pull_request.base.sha` 是 base 分支在事件當下的
    tip，不是 merge-base。兩點 `git diff base head` 比對的是兩棵樹，於是「fork 之後別人
    合進 base、本 PR 沒有」的檔案也會出現在 diff 裡（方向相反，呈現為刪除），把別人的
    改動算到本 PR 頭上。三點只看 head 自 merge-base 以來新增了什麼，正是 PR review 的語意。

    解不開的 commit（shallow checkout 缺物件是 CI 上的真實情境——workflow 需要
    `fetch-depth: 0`）在此轉成 RuntimeError，由 `main()` 以 exit 2 大聲失敗；不可回空字串，
    否則 gate 會在根本沒讀到 diff 的情況下報告通過。
    """
    return _run_git_diff([f"{base}...{head}", "--"], f"git diff {base}...{head}")


def _parse_args(argv: list[str]) -> tuple[str | None, str | None, str | None]:
    """回傳 `(base, head, diff_file)`；引數矛盾時 raise ValueError（由 `main()` 轉 exit 2）。

    手寫而非 argparse：argparse 的錯誤路徑是 `SystemExit`，`main()` 的契約是**回傳**
    exit code（測試直接呼叫 `main()` 斷言回傳值），混用會讓 exit 2 這條路徑逃出契約之外。
    """
    base: str | None = None
    head: str | None = None
    positional: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--base", "--head"):
            # 先驗邊界再取值：漏傳值時要給 clean 的 [FAIL]，不是 IndexError stacktrace。
            if i + 1 >= len(argv):
                raise ValueError(f"{arg} 後面需要一個 commit-ish 引數")
            value = argv[i + 1]
            # 空字串必須擋在這裡：`""` 不是 `None`，會通過下面的成對檢查而進入 range 模式，
            # 而 `git diff "...head"` 是**合法** range（等同 `HEAD...head`）——CI 的 checkout
            # 就在 head，於是 git exit 0 回空 diff，gate 印 [OK] 通過卻什麼都沒讀。這正是本檔
            # 要防的假綠形狀，只是換一道門進來。（PR #347 mob review，三家獨立提出。）
            if not value.strip():
                raise ValueError(f"{arg} 的值不可為空字串（空值會退化成 HEAD...HEAD 的空 diff）")
            if arg == "--base":
                base = value
            else:
                head = value
            i += 2
            continue
        if arg.startswith("-"):
            raise ValueError(f"未知選項：{arg}")
        positional.append(arg)
        i += 1

    if (base is None) != (head is None):
        raise ValueError("--base 與 --head 必須成對出現（只給一半無法界定 range）")
    if base is not None and positional:
        raise ValueError("range 模式（--base/--head）與 diff 檔路徑不可同時指定")
    if len(positional) > 1:
        raise ValueError(f"最多只能指定一個 diff 檔路徑，收到 {len(positional)} 個")
    return base, head, (positional[0] if positional else None)


def main(argv: list[str], read_gate_file: GateReader | None = None) -> int:
    try:
        base, head, diff_file = _parse_args(argv)
    except ValueError as e:
        print(f"[FAIL] 引數錯誤：{e}", file=sys.stderr)
        return 2

    if base is not None and head is not None:
        try:
            diff_text = _range_diff(base, head)
        except RuntimeError as e:
            print(f"[FAIL] {e}", file=sys.stderr)
            return 2
    elif diff_file is not None:
        try:
            diff_text = Path(diff_file).read_text(encoding="utf-8")
        except OSError as e:
            print(f"[FAIL] 無法讀取 diff 檔：{e}", file=sys.stderr)
            return 2
    else:
        try:
            diff_text = _staged_diff()
        except RuntimeError as e:
            print(f"[FAIL] {e}", file=sys.stderr)
            return 2

    try:
        warns = warn_rule_evidence(diff_text)
        # 兩組檢查並列、互不替代：證據標記不滿足宣告，宣告也不滿足證據標記。
        errors = check_rule_evidence(diff_text)
    except ValueError as e:
        # 解不開的 C-style 引號路徑：無法判定它是不是 rule 檔，不可略過它。
        print(f"[FAIL] 無法解析 diff：{e}", file=sys.stderr)
        return 2
    for w in warns:
        print(f"  [WARN] {w}", file=sys.stderr)

    # gate 連結的資料來源跟著輸入走：staged 讀 index、range 讀 `--head`、diff 檔讀工作樹。
    if read_gate_file is None:
        if base is not None and head is not None:
            read_gate_file = _git_gate_reader(head)
        elif diff_file is not None:
            read_gate_file = _read_repo_file
        else:
            read_gate_file = _git_gate_reader(None)
    try:
        mechanization_errors = check_rule_mechanization(diff_text, read_gate_file)
    except OSError as e:
        # 無法驗證 gate link 不是「連結有效」也不是「連結無效」；絕不可往下印 [OK]。
        print(f"[FAIL] 無法驗證 gate link（讀檔失敗）：{e}", file=sys.stderr)
        return 2

    if errors:
        print(f"[FAIL] {len(errors)} 個新增 rule/hook 缺證據標記：", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        print(
            "\n修法：為新 rule/hook 補上證據標記——"
            "可機械實測者附 probe 輸出並標 `<!-- verified: probe -->`；"
            "事件佐證者標 `(Source: PR #NNN` 或 `<!-- verified: incident PR#NNN -->`；"
            "若屬主觀 / 單次，改 park 到 typed-lessons 而非寫入 always-loaded 面。",
            file=sys.stderr,
        )
    if mechanization_errors:
        print(
            f"[FAIL] {len(mechanization_errors)} 個 rule 檔的機械化宣告檢查未通過：",
            file=sys.stderr,
        )
        for e in mechanization_errors:
            print(f"  {e}", file=sys.stderr)
        print(
            "\n修法：每個新增 rule section 擇一宣告——"
            "已有機械 gate 者寫 `<!-- gate: scripts/foo.py::symbol -->`（路徑須存在且屬 scripts/、"
            ".claude/hooks/、.github/workflows/、.pre-commit-config.yaml、tasks/**/tests/）；"
            "無法機械化者寫 `<!-- gate: none (reason: judgment|no-observable-signal|hook-cost) — <說明> -->`。"
            "純 rename 進 .claude/rules/ 時 diff 沒有內容可檢查，須同時補上證據標記與宣告。",
            file=sys.stderr,
        )
    if errors or mechanization_errors:
        return 1

    print(
        "[OK] 新增 rule/hook 皆帶證據標記與機械化宣告"
        + (f"（另有 {len(warns)} 個 warn）" if warns else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

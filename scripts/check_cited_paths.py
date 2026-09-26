#!/usr/bin/env python3
"""檢查 markdown 文件引用的路徑，是否都存在於「單一」目標 repo 的版控內。

用途：依週報（或任何自動產生的建議清單）開 issue 前的閘門。週報是對某個 repo 的心智模型
寫的，引用的路徑常常屬於另一個 repo、或已被搬走。一次只對一個 repo 檢查是刻意的——
允許「存在於任一 repo 即可」會把「開錯 repo」這個錯誤洗掉。

用法：
    python3 scripts/check_cited_paths.py <markdown-file> --repo <target-repo-root>

Exit code：
    0  每一條檢查到的引用都存在（缺的也都已用 expected-absent 宣告）。stderr 的 `[SKIPPED]`
       token 沒有檢查，須人工確認
    1  有路徑不存在、跳出 repo、單獨檔名同名多個，或 expected-absent 宣告的檔案其實存在
    2  無法判斷：檔案讀不到或不是 UTF-8、--repo 不是 git repo 的根目錄、git 執行失敗
       （非零、逾時、找不到 git）
    3  沒有抽到任何路徑引用，無法判斷——停下人工確認，不可當成通過

「存在」以 `--repo` 目前 checkout 的 git index（`git ls-files`）為準，並逐字比對大小寫：
已 git add 的檔案算存在，gitignored 與未追蹤的檔案算不存在。這不等於 GitHub 預設分支上的
內容——本機分支獨有、或只 git add 還沒 push 的檔案也算存在；要對齊 GitHub，`--repo` 必須
指向已 pull 的 main checkout。

設計原則：這是閘門，寧可多擋不可漏放，所以刻意不去「理解」markdown 結構——任何會把一段
文字判定為「不用檢查」的解析（fence、code span 配對、縮排程式碼區塊）只要判錯就會藏起路徑。
因此：
- 全文都抽取，包含 fenced code block 內的內容（範例裡的相對路徑多半是真實路徑）
- 逐行以硬分隔字元切 token：空白、markdown 標點（反引號、中括號、角括號、引號、`{}|,;=!`）
  與全形標點。中文、日文字不是硬分隔（路徑可能含中文）；只在散文語境、位於 token 頭尾且
  不緊貼 `/` 時剝掉，反引號與連結內的中文一律保留
- markdown 反斜線跳脫（`\\_`、`\\``）先還原成原字元再切；文件開頭的 BOM 先去掉
- 連結目標另外用 regex 從全文補抓，一律檢查：inline 連結（右中括號接左括號，目標前可有空白、
  換行或左角括號）、參考式連結定義（`[ref]:` 之後，不限行首——blockquote、清單、續行內都算，
  標籤可含跳脫字元，目標可在下一行）、HTML 的 `href`／`src`。註腳定義 `[^1]:` 不算。連結目標
  的 `?query` 先去掉；以 `/` 開頭者依 GitHub 語意視為 repo 根目錄起算

每個 token 依語境判斷：緊鄰反引號或角括號的屬「程式碼語境」，其餘屬「散文語境」——只看緊貼
token 的一個字元，不做配對。清理：去掉外圍或不成對的括號、首尾冒號、句尾句點，以及結尾的
`:行`、`:行:欄`、`:起-迄`、`#L12`、`#錨點`、`::pytest-node`；散文語境另外去掉首尾的強調符號
（`*`、`_`、`~`，緊貼 `/` 時視為 glob 保留）與句尾問號，避免斜體或粗體被當成 glob。
- 排除：flag（`-` 開頭）、`@` 開頭、絕對路徑（`/`、`~/`）、含 `://` 或 `mailto:` 等 scheme、
  不含任何字母（版本號、`3/3`）
- 連結目標：一律算路徑（不套下面的 shell 符號與 remote 排除）
- 非連結目標另外排除：含 shell 符號（`$`、`&`、`\\`）；看不出是路徑（見下）且第一段是目標
  repo 的 git remote 名稱（`origin/main`）。remote 名稱剛好也是 repo 頂層目錄時，看得出是
  路徑的寫法照常檢查（寧可多擋）
- 不含斜線：程式碼語境中有已知副檔名、或是已知無副檔名檔名（`Makefile` 等）才算路徑；
  散文語境一律不算（散文的 SKILL.md 多半是泛稱）
- 含斜線：看得出是路徑者一律檢查——結尾斜線、第一段是 repo 頂層項目或以點開頭、第二段起
  任一段含點、最後一段是已知無副檔名檔名。其餘在程式碼語境中三段以上也檢查；剩下的
  （owner/repo、Read/Write/Edit 這類斜線詞）不檢查，但印 `[SKIPPED]` 到 stderr

判斷存在：
- 結尾斜線：必須是 repo 根目錄起算的目錄；含 glob 時也只比對目錄
- 含 `*`／`?`：glob，`**` 可跨目錄，`?` 比對一個非 `/` 字元，至少命中一個已追蹤檔案才算存在
- 不含斜線的檔名：在任何深度找同名的已追蹤檔案，恰好一個才算存在（印出命中路徑）；
  多個印 `[AMBIGUOUS]`，要求改寫成完整路徑
- `.claude/rules/13` 這種編號簡寫：同一層有 `13-<名稱>.md` 即算存在
- 正規化後跳出 repo 的路徑（`../`）印 `[OUTSIDE]`

文件本來就在說明「某檔不存在」時，用 `<!-- expected-absent: <path> <path> -->` 明確宣告，
寫法須與 `[MISSING]` 行印出的字串完全相同。宣告只認文件最開頭的宣告區塊：從第一行起、
只由第 0 欄的宣告行與空白行組成，遇到第一個其他內容即結束。文件開頭不可能落在 fence、
inline code 或縮排程式碼區塊內，所以不需要任何結構判斷。宣告的每一條都會被檢查，不論內文
有沒有引用：缺席時印 [ABSENT-OK]；其實存在時印 [STALE-ABSENT] 並 exit 1；跳出 repo 的路徑
不可宣告，仍印 [OUTSIDE] 並 exit 1。

已知限制：散文寫法（「rule 12」）與散文中的單獨檔名不會被檢查；看不出是路徑的斜線 token
只列為 [SKIPPED]，不會讓閘門失敗；路徑含空白時會被切成片段各自判斷。
"""

import argparse
import os
import posixpath
import re
import subprocess  # nosec B404
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

_EXTS = {
    "md",
    "mdx",
    "txt",
    "rst",
    "py",
    "pyi",
    "sh",
    "bash",
    "zsh",
    "json",
    "jsonl",
    "toml",
    "yaml",
    "yml",
    "ini",
    "cfg",
    "conf",
    "env",
    "lock",
    "js",
    "mjs",
    "cjs",
    "ts",
    "tsx",
    "jsx",
    "dart",
    "go",
    "rs",
    "kt",
    "kts",
    "swift",
    "java",
    "gradle",
    "rb",
    "php",
    "c",
    "h",
    "cc",
    "cpp",
    "hpp",
    "sql",
    "html",
    "htm",
    "css",
    "scss",
    "xml",
    "plist",
    "csv",
    "svg",
    "png",
    "jpg",
    "pdf",
    "applescript",
    "tf",
    "proto",
}
_EXTENSIONLESS_NAMES = {
    "Makefile",
    "Dockerfile",
    "Justfile",
    "Procfile",
    "Gemfile",
    "LICENSE",
    "CODEOWNERS",
}

_CJK = "\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff"
_TOKEN_SPLIT_RE = re.compile(r"[\s`\[\]{}<>\"'|,;=!\u3000-\u303f\uff00-\uffef]+")
_SPLIT_KEEP_RE = re.compile(f"({_TOKEN_SPLIT_RE.pattern})")
# CommonMark 只認 \n、\r、\r\n 為換行；str.splitlines() 另會切 NEL、U+2028 等字元
_LINE_BREAK_RE = re.compile(r"\r\n|\r|\n")
_ESCAPE_RE = re.compile(r"\\([!-/:-@\[-`{-~])")
_DEST = r"<?([^\s<>`\"'　-〿＀-￯]+)"
_LINK_DEST_RE = re.compile(r"\]\(\s*" + _DEST)
# 不限定行首：定義可在 blockquote、清單、續行內；標籤可含跳脫字元。多抓只會多檢查
_REF_DEF_RE = re.compile(r"\[(?!\^)(?:\\.|[^\]\\\n])+\]:[ \t]*(?:\r?\n[ \t>]*)?" + _DEST)
_HTML_ATTR_RE = re.compile(r"\b(?:href|src)\s*=\s*[\"']?\s*([^\"'\s<>]+)", re.IGNORECASE)
_LEADING_EMPHASIS_RE = re.compile(r"^[*_~]+(?=[^/*_~])")
_TRAILING_EMPHASIS_RE = re.compile(r"(?<=[^/*_~])[*_~]+$")
_DECLARATION_RE = re.compile(r"^<!--\s*expected-absent:\s*(.*?)\s*-->\s*$")
_LEADING_CJK_RE = re.compile(rf"^[{_CJK}]+(?=[^/{_CJK}])")
_TRAILING_CJK_RE = re.compile(rf"(?<=[^/{_CJK}])[{_CJK}]+$")
_SUFFIX_RE = re.compile(r"(?:::\S+|#.*|(?::\d+)+(?:-\d+)?)$")
_SENTENCE_DOT_RE = re.compile(r"(?<=[^./])\.$")
_SCHEME_RE = re.compile(r"^(?:mailto|tel|data|javascript|about):", re.IGNORECASE)
_SHELL_CHARS = set("$&\\")
_NUMBERED_RE = re.compile(r"^\d+$")


@dataclass
class RepoIndex:
    """目標 repo 的已追蹤檔案清單（相對路徑，以 / 分隔）。"""

    files: set[str]
    remotes: set[str] = field(default_factory=set)
    dirs: set[str] = field(init=False)
    top_level: set[str] = field(init=False)
    by_name: dict[str, list[str]] = field(init=False)

    def __post_init__(self) -> None:
        self.dirs = set()
        self.by_name = {}
        for f in self.files:
            parts = f.split("/")
            for i in range(1, len(parts)):
                self.dirs.add("/".join(parts[:i]))
            self.by_name.setdefault(parts[-1], []).append(f)
        self.top_level = {f.split("/", 1)[0] for f in self.files}


@dataclass
class Resolution:
    status: str  # ok / missing / outside / ambiguous
    matches: list[str] = field(default_factory=list)


def _git(repo: Path, *args: str) -> str:
    """在 repo 執行 git，回傳 stdout；無法執行、逾時或非零結束一律丟 RuntimeError。"""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"}
    }
    try:
        proc = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"無法執行 git {args[0]}：{e}") from e
    if proc.returncode != 0:
        raise RuntimeError(f"git {args[0]} 失敗：{proc.stderr.strip()}")
    return proc.stdout


def load_index(repo: Path) -> RepoIndex:
    """讀取 repo 的已追蹤檔案；--repo 必須是 git repo（或 worktree）的根目錄。"""
    try:
        top = _git(repo, "rev-parse", "--show-toplevel").strip()
    except RuntimeError as e:
        raise RuntimeError(f"{repo} 不是 git repo：{e}") from e
    if Path(top).resolve() != repo.resolve():
        raise RuntimeError(f"--repo 必須是 repo 根目錄（{top}），不是子目錄：{repo}")
    files = {f for f in _git(repo, "ls-files", "-z").split("\0") if f}
    remotes = set(_git(repo, "remote").split())
    return RepoIndex(files=files, remotes=remotes)


def _strip_parens(token: str) -> str:
    """剝掉外圍成對的括號與不成對的首尾括號；路徑內成對的括號（`a(1).md`）保留。"""
    while token.startswith("(") and token.endswith(")") and len(token) > 1:
        token = token[1:-1]
    while token.startswith("(") and token.count("(") > token.count(")"):
        token = token[1:]
    while token.endswith(")") and token.count(")") > token.count("("):
        token = token[:-1]
    return token


def _clean(token: str, prose: bool) -> str:
    """剝掉 token 首尾不屬於路徑的字元，反覆套用直到不再變化。"""
    previous = None
    while token != previous:
        previous = token
        token = _strip_parens(token.strip(":"))
        token = _SUFFIX_RE.sub("", token).rstrip(":")
        token = _SENTENCE_DOT_RE.sub("", token)
        if prose:
            # 散文才剝頭尾中文：反引號與連結內的中文是路徑本身
            token = _TRAILING_CJK_RE.sub("", _LEADING_CJK_RE.sub("", token))
            # 強調符號緊貼 `/` 時是 glob（`dir/*`、`**/x`），不剝
            token = _LEADING_EMPHASIS_RE.sub("", _TRAILING_EMPHASIS_RE.sub("", token))
            token = token.rstrip("?")
        elif len(token) > 4 and token.startswith("**") and token.endswith("**"):
            token = token[2:-2]
    return unquote(token) if "%" in token else token


def _ext(segment: str) -> str | None:
    stem = segment.lstrip(".")
    if "." not in stem:
        return None
    return stem.rsplit(".", 1)[1].lower()


def _classify(token: str, index: RepoIndex, in_code: bool = True, is_link: bool = False) -> str:
    """回傳 path / skipped / ignore。

    is_link（markdown 連結目標）一律當路徑；in_code=False（散文語境）時只認看得出是路徑的
    斜線 token，單獨檔名不查。
    """
    if not token or token.startswith(("-", "@", "/", "~/")) or token == "~":
        return "ignore"
    if "://" in token or _SCHEME_RE.match(token):
        return "ignore"
    if not any(c.isalpha() for c in token):
        return "ignore"
    if is_link:
        return "path"
    if any(c in _SHELL_CHARS for c in token):
        return "ignore"
    segments = [s for s in token.split("/") if s]
    if not segments:
        return "ignore"
    if "/" not in token:
        if in_code and (token in _EXTENSIONLESS_NAMES or _ext(token) in _EXTS):
            return "path"
        return "ignore"
    first = segments[0]
    looks_like_path = (
        token.endswith("/")
        or first in index.top_level
        or first.startswith(".")
        or any("." in s for s in segments[1:])
        or segments[-1] in _EXTENSIONLESS_NAMES
    )
    if looks_like_path:
        return "path"
    # remote ref（`origin/main`）只在看不出是路徑時才排除，否則同名頂層目錄下的路徑會被略過
    if first in index.remotes:
        return "ignore"
    if in_code and len(segments) > 2:
        return "path"
    return "skipped"


def _link_destinations(raw: str, unescaped: str) -> list[str]:
    """抓出 inline 連結、參考式連結定義、HTML href/src 的目標（去掉 `?query`）。

    參考式定義在跳脫還原前後的文字各抓一次：還原後才認得出 `\\]` 以外的一般寫法，
    還原前才認得出標籤含跳脫 `]` 的寫法。以 `/` 開頭的連結目標依 GitHub 語意視為 repo
    根目錄起算。
    """
    found = [m.group(1) for m in _LINK_DEST_RE.finditer(unescaped)]
    found += [m.group(1) for m in _HTML_ATTR_RE.finditer(unescaped)]
    for text in (raw, unescaped):
        found += [_ESCAPE_RE.sub(r"\1", m.group(1)) for m in _REF_DEF_RE.finditer(text)]
    dests = []
    for dest in found:
        # 先截在未成對的 `)`：`](a.md)|[b](https://x)` 不可被抓成一整串再因含 `://` 被丟掉
        dest = _until_unbalanced_paren(dest).split("?", 1)[0]
        # 先解碼再處理開頭斜線：`%2Fa.md` 解碼後才看得出是根目錄起算
        dest = unquote(dest) if "%" in dest else dest
        if dest.startswith("/") and not dest.startswith("//"):
            dest = dest.lstrip("/")
        dests.append(dest)
    return dests


def _until_unbalanced_paren(dest: str) -> str:
    """回傳 dest 在第一個未成對 `)` 之前的部分；路徑內成對的括號（`a(1).md`）保留。"""
    depth = 0
    for i, c in enumerate(dest):
        if c == "(":
            depth += 1
        elif c == ")":
            if depth == 0:
                return dest[:i]
            depth -= 1
    return dest


def extract_candidates(text: str, index: RepoIndex) -> tuple[list[str], list[str]]:
    """回傳（要檢查的路徑、未檢查只列 [SKIPPED] 的 token），皆依首次出現順序去重。

    全文都抽取（含 fence 內容），不做任何 markdown 結構判斷，所以解析錯誤只會多檢查、
    不會漏檢；連結目標另外補抓並一律檢查。
    """
    candidates: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()

    def add(token: str, kind: str) -> None:
        if kind == "ignore":
            return
        if token in seen:
            if kind == "path" and token in skipped:
                skipped.remove(token)
                candidates.append(token)
            return
        seen.add(token)
        (candidates if kind == "path" else skipped).append(token)

    original = text.removeprefix("﻿")
    text = _ESCAPE_RE.sub(r"\1", original)
    for line in _LINE_BREAK_RE.split(text):
        # 捕捉群組讓 split 保留分隔字元：parts 為 token、分隔、token、分隔…交錯
        parts = _SPLIT_KEEP_RE.split(line)
        for i in range(0, len(parts), 2):
            before = parts[i - 1] if i > 0 else ""
            after = parts[i + 1] if i + 1 < len(parts) else ""
            piece = parts[i]
            # inline 連結目標在這裡也檢查一次（去掉 ?query），不只依賴 _link_destinations：
            # 兩道獨立的抽取，任一道的 regex 判錯都不會讓路徑漏檢
            is_link = before.endswith("]") and piece.startswith("(")
            if is_link:
                piece = piece.split("?", 1)[0]
                if _SCHEME_RE.match(piece.lstrip("(")):
                    continue  # `(tel:123)` 清理時會被當成行號後綴剝成 `tel`，先排除
            in_code = is_link or before.endswith(("`", "<")) or after.startswith(("`", ">"))
            token = _clean(piece, prose=not in_code)
            add(token, _classify(token, index, in_code, is_link))
    for dest in _link_destinations(original, text):
        # scheme 要在清理前判斷：`tel:123` 清理時會被當成行號後綴剝成 `tel`
        if "://" in dest or _SCHEME_RE.match(dest):
            continue
        token = _clean(dest, prose=False)
        add(token, _classify(token, index, in_code=True, is_link=True))
    return candidates, skipped


def parse_expected_absent(text: str) -> list[str]:
    """收集文件開頭宣告區塊內 `<!-- expected-absent: a b -->` 的路徑，依出現順序去重。

    宣告區塊從第一行起，只由第 0 欄的宣告行與空白行組成，遇到第一個其他內容即結束。
    """
    found: list[str] = []
    for line in _LINE_BREAK_RE.split(text.removeprefix("﻿")):
        if not line.strip():
            continue
        m = _DECLARATION_RE.match(line)
        if not m:
            break
        for token in m.group(1).split():
            if token not in found:
                found.append(token)
    return found


def _glob_regex(pattern: str) -> re.Pattern[str]:
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def resolve(token: str, index: RepoIndex) -> Resolution:
    """判斷 token 在 repo 版控內的狀態。"""
    is_dir_ref = token.endswith("/")
    rel = posixpath.normpath(token.rstrip("/"))
    if rel == ".." or rel.startswith("../") or rel.startswith("/"):
        return Resolution("outside")
    if "/" not in token.rstrip("/") and not is_dir_ref:
        if "*" in rel or "?" in rel:
            pattern = _glob_regex(rel)
            hits = sorted(n for n in index.by_name if pattern.match(n))
            return Resolution("ok", hits) if hits else Resolution("missing")
        matches = sorted(index.by_name.get(rel, []))
        if not matches:
            return Resolution("missing")
        if len(matches) > 1:
            return Resolution("ambiguous", matches)
        return Resolution("ok", matches)
    if "*" in rel or "?" in rel:
        pattern = _glob_regex(rel)
        pool = index.dirs if is_dir_ref else index.files
        hits = sorted(p for p in pool if pattern.match(p))
        return Resolution("ok", hits) if hits else Resolution("missing")
    if is_dir_ref:
        return Resolution("ok") if rel in index.dirs else Resolution("missing")
    if rel in index.files or rel in index.dirs:
        return Resolution("ok")
    parent, _, last = rel.rpartition("/")
    if _NUMBERED_RE.match(last):
        numbered = re.compile(rf"^{re.escape(parent)}/{last}-[^/]+\.md$")
        hits = sorted(f for f in index.files if numbered.match(f))
        if hits:
            return Resolution("ok", hits)
    return Resolution("missing")


def _skip_reason(token: str, index: RepoIndex) -> str:
    """[SKIPPED] 行的說明：程式碼語境下仍會略過的是 owner/repo 形狀，其餘是散文斜線詞。"""
    if _classify(token, index, in_code=True) == "skipped":
        return "形似 owner/repo，未檢查；若是路徑請寫到檔名或加結尾斜線"
    return "散文中看不出是路徑，未檢查；若是路徑請用反引號包住"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="檢查 markdown 引用的路徑是否存在於目標 repo 的版控內"
    )
    parser.add_argument("file", type=Path, help="要檢查的 markdown 檔（週報或 issue body）")
    parser.add_argument("--repo", type=Path, required=True, help="目標 repo 根目錄")
    args = parser.parse_args(argv)

    if not args.file.is_file():
        print(f"[FAIL] 找不到要檢查的檔案：{args.file}", file=sys.stderr)
        return 2
    if not args.repo.is_dir():
        print(f"[FAIL] 目標 repo 不是目錄：{args.repo}", file=sys.stderr)
        return 2
    try:
        text = args.file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"[FAIL] 無法讀取 {args.file}（須為 UTF-8）：{e}", file=sys.stderr)
        return 2
    try:
        index = load_index(args.repo)
    except RuntimeError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2

    candidates, skipped = extract_candidates(text, index)
    declared = parse_expected_absent(text)
    for token in skipped:
        print(f"[SKIPPED] {token}（{_skip_reason(token, index)}）", file=sys.stderr)

    if not candidates and not declared:
        print(
            f"[FAIL] {args.file} 沒有抽到任何路徑引用，無法判斷是否可以開票。請人工確認文件"
            "確實沒有引用路徑；若有，改用反引號包住完整路徑後重跑。",
            file=sys.stderr,
        )
        return 3

    missing: list[str] = []
    other_bad: list[str] = []
    stale: list[str] = []
    for token in candidates:
        if token in declared:
            continue
        res = resolve(token, index)
        if res.status == "ok":
            shown = f" -> {res.matches[0]}" if "/" not in token and res.matches else ""
            print(f"[OK] {token}{shown}")
        elif res.status == "ambiguous":
            print(f"[AMBIGUOUS] {token}（同名 {len(res.matches)} 個：{', '.join(res.matches)}）")
            other_bad.append(token)
        elif res.status == "outside":
            print(f"[OUTSIDE] {token}（跳出目標 repo）")
            other_bad.append(token)
        else:
            print(f"[MISSING] {token}")
            missing.append(token)
    for token in declared:
        status = resolve(token, index).status
        if status == "outside":
            print(f"[OUTSIDE] {token}（跳出目標 repo，不可宣告為 expected-absent）")
            other_bad.append(token)
        elif status in {"ok", "ambiguous"}:
            print(f"[STALE-ABSENT] {token}")
            stale.append(token)
        else:
            print(f"[ABSENT-OK] {token}")

    bad = missing + other_bad
    print(
        f"檢查 {len(candidates)} 條引用、{len(declared)} 條 expected-absent 宣告："
        f"{len(bad)} 條有問題、{len(stale)} 條宣告過時（{args.repo.resolve()}）"
    )
    if missing:
        print(
            f"[FAIL] {len(missing)} 條引用的路徑不在目標 repo 的版控內：可能屬於另一個 repo、"
            "已被搬走、還沒 git add，或是筆誤。先修正文件或改開到正確的 repo 再開票。若文件本來"
            "就在說明「此檔不存在」，在文件最開頭加 <!-- expected-absent: <與 [MISSING] 行相同的"
            "字串> --> 明確宣告。",
            file=sys.stderr,
        )
    if other_bad:
        print(
            f"[FAIL] {len(other_bad)} 條引用跳出目標 repo 或同名多個：跳出 repo 的改開到正確的 "
            "repo（不可用 expected-absent 放行）；同名多個的改寫成完整路徑。",
            file=sys.stderr,
        )
    if stale:
        print(
            f"[FAIL] {len(stale)} 條宣告為 expected-absent 的路徑其實存在：把它從宣告移除並改寫"
            "文件的「不存在」敘述；若文件本來是寫給別的 repo，改用正確的 --repo 重跑。",
            file=sys.stderr,
        )
    return 1 if bad or stale else 0


if __name__ == "__main__":
    sys.exit(main())

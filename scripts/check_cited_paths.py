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
    2  無法判斷：檔案讀不到或不是 UTF-8、fence 到文件結尾仍未關閉、--repo 不是 git repo 的
       根目錄、git 執行失敗（非零、逾時、找不到 git）
    3  沒有抽到任何路徑引用，無法判斷——停下人工確認，不可當成通過

「存在」以 `--repo` 目前 checkout 的 git index（`git ls-files`）為準，並逐字比對大小寫：
已 git add 的檔案算存在，gitignored 與未追蹤的檔案算不存在。這不等於 GitHub 預設分支上的
內容——本機分支獨有、或只 git add 還沒 push 的檔案也算存在；要對齊 GitHub，`--repo` 必須
指向已 pull 的 main checkout。

抽取範圍：fenced code block 以外的全文（散文、inline code、連結都算），逐行以空白、markdown
標點（反引號、中括號、角括號、引號、`{}|,;=!`）與 CJK 字元切成 token。刻意不做 code span
配對——落單或跳脫的反引號、巢狀括號、跨行的 span 或連結都不可能藏起路徑，配錯最多多檢查。
路徑本身含上述字元時會被切成片段各自檢查（可能誤擋，不會漏放）。括號不切開，只剝掉外圍或
不成對的首尾括號，所以 `docs/a(1).md` 保持完整。

fence：開頭行縮排至多 3 格；關閉行去掉前後空白後全是同一種 fence 字元、長度不短於開頭，
且縮排不超過開頭行縮排 + 3（list item 內的 fence 會整體縮排）。到文件結尾仍未關閉時 exit 2。

每個 token 先去掉外圍括號、首尾冒號、粗體的 `**`、句尾句點，以及結尾的 `:行`、`:行:欄`、
`:起-迄`、`#L12`、`#錨點`、`::pytest-node`，再依語境判斷：
- 語境：緊鄰反引號或角括號、或是連結目標（緊接在 `]` 之後的 `(`）的 token 屬「程式碼語境」，
  其餘屬「散文語境」。只看緊貼 token 的一個字元，不做配對
- 排除（兩種語境皆同）：flag（`-` 開頭）、`@` 開頭、絕對路徑（`/`、`~`）、含 `://`、
  `mailto:` 等 scheme、含 shell 符號（`$`、`&`、`\\`）、不含任何字母（版本號、`3/3`）、
  第一段是目標 repo 的 git remote 名稱（`origin/main`）
- 連結目標：一律算路徑
- 不含斜線：程式碼語境中有已知副檔名、或是已知無副檔名檔名（`Makefile` 等）才算路徑；
  散文語境一律不算（散文的 `SKILL.md` 多半是泛稱）
- 含斜線：看得出是路徑者一律檢查——結尾斜線、第一段是 repo 頂層項目或以點開頭、第二段起
  任一段含點、最後一段是已知無副檔名檔名。其餘在程式碼語境中三段以上也檢查；剩下的
  （`owner/repo`、`Read/Write/Edit` 這類斜線詞）不檢查，但印 `[SKIPPED]` 到 stderr

判斷存在：
- 結尾斜線：必須是 repo 根目錄起算的目錄；含 glob 時也只比對目錄
- 含 `*`／`?`：glob，`**` 可跨目錄，`?` 比對一個非 `/` 字元，至少命中一個已追蹤檔案才算存在
- 不含斜線的檔名：在任何深度找同名的已追蹤檔案，恰好一個才算存在（印出命中路徑）；
  多個印 `[AMBIGUOUS]`，要求改寫成完整路徑
- `.claude/rules/13` 這種編號簡寫：同一層有 `13-<名稱>.md` 即算存在
- 正規化後跳出 repo 的路徑（`../`）印 `[OUTSIDE]`

文件本來就在說明「某檔不存在」時，用 `<!-- expected-absent: <path> <path> -->` 明確宣告，
寫法須與 `[MISSING]` 行印出的字串完全相同。宣告的每一條都會被檢查，不論內文有沒有引用：
缺席時印 [ABSENT-OK]；其實存在時印 [STALE-ABSENT] 並 exit 1；跳出 repo 的路徑不可宣告，
仍印 [OUTSIDE] 並 exit 1。宣告必須在 fence 以外單獨一行，且前後都是空行（或文件頭尾）：
CommonMark 的 inline code 不會跨空行，所以這樣的宣告不可能是 inline code 內的示範寫法。

已知限制：fence 內的路徑、散文寫法（「rule 12」）、散文中的單獨檔名不會被檢查；看不出是
路徑的斜線 token 只列為 [SKIPPED]，不會讓閘門失敗。
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

_FENCE_OPEN_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
# 路徑不會含這些字元；真的含時會被切成片段各自檢查，只會多擋、不會漏放
_TOKEN_SPLIT_RE = re.compile(r"[\s`\[\]{}<>\"'|,;=!　-〿぀-ヿ㐀-䶿一-鿿＀-￯]+")
_SPLIT_KEEP_RE = re.compile(f"({_TOKEN_SPLIT_RE.pattern})")
_DECLARATION_RE = re.compile(r"^\s*<!--\s*expected-absent:\s*(.*?)\s*-->\s*$")
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


def _clean(token: str) -> str:
    token = _strip_parens(token.strip(":"))
    if len(token) > 4 and token.startswith("**") and token.endswith("**"):
        token = token[2:-2]
    token = _SUFFIX_RE.sub("", token).rstrip(":")
    token = _SENTENCE_DOT_RE.sub("", token)
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
    if not token or token.startswith(("-", "@", "/", "~")):
        return "ignore"
    if "://" in token or _SCHEME_RE.match(token) or any(c in _SHELL_CHARS for c in token):
        return "ignore"
    if not any(c.isalpha() for c in token):
        return "ignore"
    if is_link:
        return "path"
    segments = [s for s in token.split("/") if s]
    if not segments:
        return "ignore"
    if "/" not in token:
        if in_code and (token in _EXTENSIONLESS_NAMES or _ext(token) in _EXTS):
            return "path"
        return "ignore"
    first = segments[0]
    if first in index.remotes:
        return "ignore"
    looks_like_path = (
        token.endswith("/")
        or first in index.top_level
        or first.startswith(".")
        or any("." in s for s in segments[1:])
        or segments[-1] in _EXTENSIONLESS_NAMES
    )
    if looks_like_path:
        return "path"
    if in_code and len(segments) > 2:
        return "path"
    return "skipped"


def _scan(text: str) -> tuple[list[str], list[str]]:
    """回傳（fence 以外的行、獨立成段的 expected-absent 宣告行內容）。

    fence 關閉行的縮排不得超過開頭行縮排 + 3（CommonMark 規則相對於所在容器，這裡以開頭行縮排
    近似 list item 的容器縮排）。fence 到文件結尾仍未關閉時丟 ValueError。
    """
    lines = text.splitlines()
    outside: list[str] = []
    declarations: list[str] = []
    fence: tuple[int, str] | None = None
    for i, line in enumerate(lines):
        if fence is not None:
            indent, marker = fence
            stripped = line.strip()
            if (
                stripped
                and set(stripped) == {marker[0]}
                and len(stripped) >= len(marker)
                and len(line) - len(line.lstrip(" ")) <= indent + 3
            ):
                fence = None
            continue
        m = _FENCE_OPEN_RE.match(line)
        if m and not (m.group(2)[0] == "`" and "`" in m.group(3)):
            fence = (len(m.group(1)), m.group(2))
            continue
        outside.append(line)
        decl = _DECLARATION_RE.match(line)
        isolated = (i == 0 or not lines[i - 1].strip()) and (
            i == len(lines) - 1 or not lines[i + 1].strip()
        )
        if decl and isolated:
            declarations.append(decl.group(1))
    if fence is not None:
        raise ValueError(f"fence（{fence[1]}）到文件結尾仍未關閉，無法判斷後文是否為程式碼")
    return outside, declarations


def extract_candidates(text: str, index: RepoIndex) -> tuple[list[str], list[str]]:
    """回傳（要檢查的路徑、以 owner/repo 形狀略過的 token），皆依首次出現順序去重。

    fence 以外全文都抽取（散文、inline code、連結），不依賴 code span 配對，因此配對錯誤
    只會多檢查、不會漏檢。fence 到文件結尾仍未關閉時丟 ValueError。
    """
    candidates: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for line in _scan(text)[0]:
        # 捕捉群組讓 split 保留分隔字元：parts 為 token、分隔、token、分隔…交錯
        parts = _SPLIT_KEEP_RE.split(line)
        for i in range(0, len(parts), 2):
            raw = parts[i]
            token = _clean(raw)
            before = parts[i - 1] if i > 0 else ""
            after = parts[i + 1] if i + 1 < len(parts) else ""
            # 只看緊貼 token 的字元：CJK 與反引號都是分隔字元，會被合併成同一段分隔
            is_link = before.endswith("]") and raw.startswith("(")
            in_code = is_link or before.endswith(("`", "<")) or after.startswith(("`", ">"))
            kind = _classify(token, index, in_code, is_link)
            if kind == "ignore":
                continue
            if token in seen:
                if kind == "path" and token in skipped:
                    skipped.remove(token)
                    candidates.append(token)
                continue
            seen.add(token)
            (candidates if kind == "path" else skipped).append(token)
    return candidates, skipped


def parse_expected_absent(text: str) -> list[str]:
    """收集 fence 以外、獨立成段的 `<!-- expected-absent: a b -->` 宣告路徑，依出現順序去重。

    宣告須單獨一行且前後為空行（或文件開頭／結尾）：CommonMark 的 inline code 不會跨空行，
    所以這樣的宣告不可能落在 inline code 內，不需判斷反引號配對。
    """
    found: list[str] = []
    for decl in _scan(text)[1]:
        for token in decl.split():
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
    try:
        candidates, skipped = extract_candidates(text, index)
        declared = parse_expected_absent(text)
    except ValueError as e:
        print(f"[FAIL] {args.file}：{e}。補上關閉的 fence 後重跑。", file=sys.stderr)
        return 2

    for token in skipped:
        print(f"[SKIPPED] {token}（形似 owner/repo，未檢查；若是路徑請寫完整）", file=sys.stderr)

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
            "就在說明「此檔不存在」，在文件內加 <!-- expected-absent: <與 [MISSING] 行相同的字串> "
            "--> 明確宣告。",
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

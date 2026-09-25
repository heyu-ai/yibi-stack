#!/usr/bin/env python3
"""檢查 markdown 文件引用的路徑，是否都存在於「單一」目標 repo 的版控內。

用途：依週報（或任何自動產生的建議清單）開 issue 前的閘門。週報是對某個 repo 的心智模型
寫的，引用的路徑常常屬於另一個 repo、或已被搬走。一次只對一個 repo 檢查是刻意的——
允許「存在於任一 repo 即可」會把「開錯 repo」這個錯誤洗掉。

用法：
    python3 scripts/check_cited_paths.py <markdown-file> --repo <target-repo-root>

Exit code：
    0  每一條引用都存在（缺的也都已用 expected-absent 宣告）
    1  有路徑不存在、跳出 repo、單獨檔名同名多個，或 expected-absent 宣告的檔案其實存在
    2  使用錯誤：檔案讀不到或不是 UTF-8、--repo 不是 git repo 的根目錄、git 執行失敗
    3  沒有抽到任何路徑引用，無法判斷——停下人工確認，不可當成通過

「存在」以 `git ls-files` 為準（已追蹤或已 git add 的檔案），並逐字比對大小寫。gitignored、
未追蹤、其他 worktree 裡的檔案都算不存在，與 GitHub 上看到的內容一致。

抽取範圍（fenced code block 以外）：
- inline code（任意數量反引號包住的片段），內容依空白切成多個 token，所以
  `python3 scripts/a.py --x` 會抽出 `scripts/a.py`
- markdown 連結 `[文字](path)` 的相對路徑（有 scheme 的網址與純錨點不算）

每個 token 先去掉結尾的 `:行`、`:行:欄`、`:起-迄`、`#L12`、`#錨點`、`::pytest-node`，再判斷：
- 排除：flag（`-` 開頭）、`@` 開頭、絕對路徑（`/`、`~`）、含 `://` 或 shell 符號（`=`、`$` 等）、
  不含任何字母（版本號、`3/3`、`+32/-4`）、第一段是目標 repo 的 git remote 名稱（`origin/main`）、
  第一段形似網域（`raw.githubusercontent.com/...`）
- 不含斜線：有已知副檔名、或是已知無副檔名檔名（`Makefile` 等）才算路徑；其餘視為一般字詞
- 含斜線：預設一律算路徑。唯一例外是「兩段、最後一段沒有點、第一段不是 repo 的頂層項目」
  （`owner/repo` 的形狀，例如 `heyu-ai/yibi-stack`）：不檢查，但印 `[SKIPPED]` 到 stderr

判斷存在：
- 結尾斜線：必須是 repo 根目錄起算的目錄
- 含 `*`／`?`：glob，`**` 可跨目錄，至少命中一個已追蹤檔案才算存在
- 不含斜線的檔名：在任何深度找同名的已追蹤檔案，恰好一個才算存在（印出命中路徑）；
  多個印 `[AMBIGUOUS]`，要求改寫成完整路徑
- `.claude/rules/13` 這種編號簡寫：同一層有 `13-<名稱>.md` 即算存在
- 正規化後跳出 repo 的路徑（`../`）印 `[OUTSIDE]`

文件本來就在說明「某檔不存在」時，用 `<!-- expected-absent: <path> <path> -->` 明確宣告，
寫法須與 `[MISSING]` 行印出的字串完全相同。宣告的每一條都會被檢查，不論內文有沒有引用：
缺席時印 [ABSENT-OK]；其實存在時印 [STALE-ABSENT] 並 exit 1。fence 或 inline code 內的宣告不算數
（那通常是在示範寫法）。

已知限制：散文寫法（「rule 12」）、fence 內的路徑、不含斜線也沒有已知副檔名的字詞不會被檢查；
`owner/repo` 形狀的兩段路徑只列為 [SKIPPED]，不會讓閘門失敗。
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
_DOMAIN_TLDS = {"com", "org", "net", "io", "dev", "ai", "app", "co", "tw", "gov", "edu"}

_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_SPAN_RE = re.compile(r"(`+)(.+?)(?<!`)\1(?!`)")
_LINK_RE = re.compile(r"\[[^\]]*\]\(\s*(<[^>]*>|[^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\s*\)")
_EXPECTED_ABSENT_RE = re.compile(r"<!--\s*expected-absent:\s*(.*?)\s*-->")
_SUFFIX_RE = re.compile(r"(?:::\S+|#.*|(?::\d+)+(?:-\d+)?)$")
_SHELL_CHARS = set("=$`(){}<>|&;!\"'\\")
_STRIP_CHARS = "\"'`,;:()[]"
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


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"}
    }
    return subprocess.run(  # nosec B603 B607
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )


def load_index(repo: Path) -> RepoIndex:
    """讀取 repo 的已追蹤檔案；--repo 必須是 git repo（或 worktree）的根目錄。"""
    try:
        top = _git(repo, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"無法執行 git：{e}") from e
    if top.returncode != 0:
        raise RuntimeError(f"{repo} 不是 git repo：{top.stderr.strip()}")
    if Path(top.stdout.strip()).resolve() != repo.resolve():
        raise RuntimeError(f"--repo 必須是 repo 根目錄（{top.stdout.strip()}），不是子目錄：{repo}")
    listed = _git(repo, "ls-files", "-z")
    if listed.returncode != 0:
        raise RuntimeError(f"git ls-files 失敗：{listed.stderr.strip()}")
    remotes = _git(repo, "remote")
    if remotes.returncode != 0:
        raise RuntimeError(f"git remote 失敗：{remotes.stderr.strip()}")
    files = {f for f in listed.stdout.split("\0") if f}
    return RepoIndex(files=files, remotes=set(remotes.stdout.split()))


def _clean(token: str) -> str:
    token = token.strip().strip(_STRIP_CHARS)
    token = _SUFFIX_RE.sub("", token)
    return token.strip(_STRIP_CHARS)


def _ext(segment: str) -> str | None:
    stem = segment.lstrip(".")
    if "." not in stem:
        return None
    return stem.rsplit(".", 1)[1].lower()


def _classify(token: str, index: RepoIndex) -> str:
    """回傳 path / skipped / ignore。"""
    if not token or token.startswith(("-", "@", "/", "~")):
        return "ignore"
    if "://" in token or any(c in _SHELL_CHARS for c in token):
        return "ignore"
    if not any(c.isalpha() for c in token):
        return "ignore"
    segments = [s for s in token.split("/") if s]
    if not segments:
        return "ignore"
    if "/" not in token:
        if token in _EXTENSIONLESS_NAMES or _ext(token) in _EXTS:
            return "path"
        return "ignore"
    first = segments[0]
    if first in index.remotes:
        return "ignore"
    if first not in index.top_level and not first.startswith("."):
        labels = first.split(".")
        if len(labels) > 1 and labels[-1].lower() in _DOMAIN_TLDS:
            return "ignore"
        if len(segments) == 2 and not token.endswith("/") and "." not in segments[1]:
            return "skipped"
    return "path"


def _outside_fences(text: str) -> list[str]:
    """回傳 fence 以外的行；fence 依 CommonMark 規則比對開啟字元與長度。"""
    lines: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        if fence is not None:
            stripped = line.strip()
            if (
                stripped
                and set(stripped) == {fence[0]}
                and len(stripped) >= len(fence)
                and len(line) - len(line.lstrip(" ")) <= 3
            ):
                fence = None
            continue
        m = _FENCE_OPEN_RE.match(line)
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            fence = m.group(1)
            continue
        lines.append(line)
    return lines


def _raw_tokens(line: str) -> list[str]:
    tokens: list[str] = []
    for m in _SPAN_RE.finditer(line):
        tokens.extend(m.group(2).split())
    for m in _LINK_RE.finditer(line):
        tokens.append(unquote(m.group(1).strip("<>")))
    return tokens


def extract_candidates(text: str, index: RepoIndex) -> tuple[list[str], list[str]]:
    """回傳（要檢查的路徑、以 owner/repo 形狀略過的 token），皆依首次出現順序去重。"""
    candidates: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for line in _outside_fences(text):
        for raw in _raw_tokens(line):
            token = _clean(raw)
            if token in seen:
                continue
            kind = _classify(token, index)
            if kind == "ignore":
                continue
            seen.add(token)
            (candidates if kind == "path" else skipped).append(token)
    return candidates, skipped


def parse_expected_absent(text: str) -> list[str]:
    """收集 fence 與 inline code 以外 `<!-- expected-absent: a b -->` 宣告的路徑，依出現順序去重。"""
    found: list[str] = []
    for line in _outside_fences(text):
        for m in _EXPECTED_ABSENT_RE.finditer(_SPAN_RE.sub("", line)):
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
        hits = sorted(f for f in index.files if pattern.match(f))
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

    candidates, skipped = extract_candidates(text, index)
    declared = parse_expected_absent(text)
    for token in skipped:
        print(f"[SKIPPED] {token}（形似 owner/repo，未檢查；若是路徑請寫完整）", file=sys.stderr)

    if not candidates and not declared:
        print(
            f"[FAIL] {args.file} 沒有抽到任何路徑引用，無法判斷是否可以開票。請人工確認文件"
            "確實沒有引用路徑；若有，改用反引號包住完整路徑後重跑。",
            file=sys.stderr,
        )
        return 3

    bad: list[str] = []
    stale: list[str] = []
    for token in candidates:
        res = resolve(token, index)
        if token in declared:
            continue
        if res.status == "ok":
            shown = f" -> {res.matches[0]}" if "/" not in token and res.matches else ""
            print(f"[OK] {token}{shown}")
        elif res.status == "ambiguous":
            print(f"[AMBIGUOUS] {token}（同名 {len(res.matches)} 個：{', '.join(res.matches)}）")
            bad.append(token)
        elif res.status == "outside":
            print(f"[OUTSIDE] {token}（跳出目標 repo）")
            bad.append(token)
        else:
            print(f"[MISSING] {token}")
            bad.append(token)
    for token in declared:
        if resolve(token, index).status in {"ok", "ambiguous"}:
            print(f"[STALE-ABSENT] {token}")
            stale.append(token)
        else:
            print(f"[ABSENT-OK] {token}")

    print(
        f"檢查 {len(candidates)} 條引用、{len(declared)} 條 expected-absent 宣告："
        f"{len(bad)} 條有問題、{len(stale)} 條宣告過時（{args.repo.resolve()}）"
    )
    if bad:
        print(
            f"[FAIL] {len(bad)} 條引用的路徑不在目標 repo 的版控內（或同名多個、跳出 repo）："
            "可能屬於另一個 repo、已被搬走、還沒 git add，或是筆誤。先修正文件或改開到正確的 "
            "repo 再開票。若文件本來就在說明「此檔不存在」，在文件內加 "
            "<!-- expected-absent: <與 [MISSING] 行相同的字串> --> 明確宣告。",
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

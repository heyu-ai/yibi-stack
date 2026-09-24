#!/usr/bin/env python3
"""檢查 markdown 文件內 inline code 引用的路徑，是否都存在於「單一」目標 repo。

用途：依週報（或任何自動產生的建議清單）開 issue 前的閘門。週報是對某個 repo 的心智模型
寫的，引用的路徑常常屬於另一個 repo、或已被搬走。一次只對一個 repo 檢查是刻意的——
允許「存在於任一 repo 即可」會把「開錯 repo」這個錯誤洗掉。

用法：
    python3 scripts/check_cited_paths.py <markdown-file> --repo <target-repo-root>

Exit code：0 全部存在（或沒有任何路徑引用，此時 stderr 印 [WARN]）；1 有路徑不存在，
或宣告為 expected-absent 的路徑其實存在；2 使用錯誤（檔案或 repo 不存在）。

抽取規則（只看 fenced code block 以外的 inline code，即單一反引號包住的片段）：
- 去掉結尾的 `:行號` 或 `:起-迄`
- 只含英數、`_ . @ * / -` 的片段才考慮；開頭為 `- @ / ~` 者排除（flag、npm scope、絕對路徑）
- 不含斜線者：最後一段有已知副檔名才算（例如 `CLAUDE.md`），在 repo 任何深度找同名檔
- 含斜線者：第一段含點、不以點開頭且 repo 內不存在者視為網址排除；其餘在最後一段有已知
  副檔名、或以斜線結尾、或第一段是 repo 既有頂層項目時才算（藉此排除 `origin/main`、
  `owner/repo` 這類非路徑）
- `.claude/rules/13` 這種編號簡寫：同層有 `13-*` 即算存在

文件本來就在說明「某檔不存在」時，用 `<!-- expected-absent: <path> <path> -->` 明確宣告，
這些路徑缺席時印 [ABSENT-OK]；若它們其實存在，印 [STALE-ABSENT] 並 exit 1。

已知限制：散文寫法（「rule 12」）與 fenced code block 內的路徑不會被檢查。
"""

import argparse
import os
import re
import sys
from pathlib import Path

_EXTS = {
    "md",
    "py",
    "sh",
    "json",
    "toml",
    "yaml",
    "yml",
    "txt",
    "js",
    "ts",
    "cfg",
    "ini",
    "lock",
    "applescript",
}
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_SPAN_RE = re.compile(r"`([^`\n]+)`")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.@*/-]+$")
_LINE_SUFFIX_RE = re.compile(r":\d+(?:-\d+)?$")
_SKIP_DIR_NAMES = {".git", ".venv", "node_modules", "__pycache__"}
_EXPECTED_ABSENT_RE = re.compile(r"<!--\s*expected-absent:\s*(.*?)\s*-->")


def _has_ext(segment: str) -> bool:
    if "." not in segment.lstrip("."):
        return False
    return segment.rsplit(".", 1)[1].lower() in _EXTS


def _is_candidate(token: str, repo_root: Path) -> bool:
    if not token or not _TOKEN_RE.match(token):
        return False
    if token.startswith(("-", "@", "/", "~")):
        return False
    segments = [s for s in token.split("/") if s]
    if not segments:
        return False
    if "/" not in token:
        return _has_ext(segments[-1])
    first = segments[0]
    first_exists = "*" not in first and (repo_root / first).exists()
    if "." in first and not first.startswith(".") and not first_exists:
        return False
    if _has_ext(segments[-1]) or token.endswith("/"):
        return True
    return first_exists


def parse_expected_absent(text: str) -> set[str]:
    """收集文件內 `<!-- expected-absent: a b c -->` 明確宣告「本來就不存在」的路徑。"""
    found: set[str] = set()
    for match in _EXPECTED_ABSENT_RE.finditer(text):
        found.update(match.group(1).split())
    return found


def extract_candidates(text: str, repo_root: Path) -> list[str]:
    """回傳文件中需要檢查的路徑，依首次出現順序、去重。"""
    in_fence = False
    seen: set[str] = set()
    out: list[str] = []
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in _SPAN_RE.finditer(line):
            token = _LINE_SUFFIX_RE.sub("", match.group(1).strip())
            if token in seen or not _is_candidate(token, repo_root):
                continue
            seen.add(token)
            out.append(token)
    return out


def _walk_names(repo_root: Path) -> set[str]:
    names: set[str] = set()
    for root, dirs, files in os.walk(repo_root):
        here = Path(root)
        dirs[:] = [
            d
            for d in dirs
            if d not in _SKIP_DIR_NAMES and not (d == "worktrees" and here.name == ".claude")
        ]
        names.update(dirs)
        names.update(files)
    return names


def exists_in_repo(token: str, repo_root: Path, _names: set[str] | None = None) -> bool:
    """路徑（或 glob）是否存在於 repo；不含斜線的檔名在任何深度存在即可。"""
    rel = token.rstrip("/")
    if "/" not in rel:
        names = _names if _names is not None else _walk_names(repo_root)
        if "*" in rel:
            pattern = re.compile("^" + re.escape(rel).replace(r"\*", ".*") + "$")
            return any(pattern.match(n) for n in names)
        return rel in names
    if "*" in rel:
        return next(repo_root.glob(rel), None) is not None
    target = repo_root / rel
    if target.exists():
        return True
    # `.claude/rules/13` 這種編號簡寫：同層有 `13-*` 即算存在
    last = target.name
    if last.isdigit() and target.parent.is_dir():
        return any(p.name.startswith(f"{last}-") for p in target.parent.iterdir())
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="檢查 markdown 引用的路徑是否存在於目標 repo")
    parser.add_argument("file", type=Path, help="要檢查的 markdown 檔（週報或 issue body）")
    parser.add_argument("--repo", type=Path, required=True, help="目標 repo 根目錄")
    args = parser.parse_args(argv)

    if not args.file.is_file():
        print(f"[FAIL] 找不到要檢查的檔案：{args.file}", file=sys.stderr)
        return 2
    if not args.repo.is_dir():
        print(f"[FAIL] 目標 repo 不是目錄：{args.repo}", file=sys.stderr)
        return 2

    repo_root = args.repo.resolve()
    try:
        text = args.file.read_text(encoding="utf-8")
    except OSError as e:
        print(f"[FAIL] 無法讀取 {args.file}：{e}", file=sys.stderr)
        return 2

    candidates = extract_candidates(text, repo_root)
    if not candidates:
        print(
            f"[WARN] {args.file} 沒有抽到任何路徑引用；若文件確實引用了路徑，請確認有用反引號包住",
            file=sys.stderr,
        )
        return 0

    expected_absent = parse_expected_absent(text)
    names = _walk_names(repo_root) if any("/" not in c.rstrip("/") for c in candidates) else set()
    missing: list[str] = []
    stale: list[str] = []
    for token in candidates:
        present = exists_in_repo(token, repo_root, names)
        if token in expected_absent:
            if present:
                print(f"[STALE-ABSENT] {token}")
                stale.append(token)
            else:
                print(f"[ABSENT-OK] {token}")
        elif present:
            print(f"[OK] {token}")
        else:
            print(f"[MISSING] {token}")
            missing.append(token)

    print(f"檢查 {len(candidates)} 條路徑，{len(missing)} 條不存在於 {repo_root}")
    if missing:
        print(
            f"[FAIL] {len(missing)} 條引用的路徑不存在於目標 repo：可能屬於另一個 repo、已被搬走，"
            "或是筆誤。先修正文件或改開到正確的 repo，再開票。若文件本來就在說明「此檔不存在」，"
            "在文件內加 <!-- expected-absent: <path> ... --> 明確宣告。",
            file=sys.stderr,
        )
    if stale:
        print(
            f"[FAIL] {len(stale)} 條宣告為 expected-absent 的路徑其實存在：文件的「不存在」敘述已過時。",
            file=sys.stderr,
        )
    return 1 if missing or stale else 0


if __name__ == "__main__":
    sys.exit(main())

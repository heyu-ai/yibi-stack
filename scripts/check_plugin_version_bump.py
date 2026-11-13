#!/usr/bin/env python3
"""改到 plugin 出貨內容時，要求 lockstep 版號一起往上升。

Claude Code 以 plugin 版號判斷要不要更新本機快取（`~/.claude/plugins/cache/<mkt>/<plugin>/<ver>/`）。
版號沒變，`claude plugin update` 就不會換掉舊快取，合併的修正在使用者端等於沒出貨。
2026-11-11 的實例：pr-cycle-deep 的建票修正（#643）在 v1.24.2 發版後才合併，之後沒有發版，
使用者端一直跑舊的 1.24.2，每個 PR 照舊多開一張 deferred 票，兩天後才查出原因。

規則：比較 `--base` 與 `--head` 的 merge base 到 head 之間的改動。只要改到任一
`plugins/<name>/`（該目錄有 `.claude-plugin/plugin.json`）底下的出貨檔案，head 上所有
plugin 的 `.claude-plugin/plugin.json` 與 `package.json` 版號就必須一致（lockstep），
而且必須大於 merge base 上的版號。

不算出貨內容、不觸發本檢查的路徑：
- 路徑中含 `tests` 目錄的檔案（測試不改變使用者端行為）；
- 版號檔本身（`.claude-plugin/plugin.json`、`package.json`），它們是被檢查的對象。

升版做法：`scripts/sync-plugin-versions.sh <新版號>` 一次改齊所有版號檔。

已知限制：兩個 PR 從同一個 base 升到同一個版號時，各自的 PR check 都會通過，後 merge 的
那個在 main 上不會再升版。CI 的 push 檢查（以 push 前後的 SHA 比較）會讓 main 轉紅，
但那時已經 merge 了。

Exit code：0 = 沒有改到出貨內容，或版號已正確升版；1 = 需要升版而沒有升，或 lockstep 不一致；
2 = 無法取得資料（git 失敗、版號檔缺失或格式錯誤）。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404
import sys
from pathlib import PurePosixPath

PLUGINS_DIR = "plugins"
MANIFEST = ".claude-plugin/plugin.json"
PACKAGE = "package.json"
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class DataError(RuntimeError):
    """無法取得判定所需的資料；對應 exit 2。"""


def _git(repo: str, *args: str) -> str:
    try:
        proc = subprocess.run(  # nosec B603 B607
            ["git", "-C", repo, *args], capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise DataError(f"無法執行 git {' '.join(args)}：{e}") from e
    if proc.returncode != 0:
        raise DataError(
            f"git {' '.join(args)} 失敗（exit {proc.returncode}）：{proc.stderr.strip()}"
        )
    return proc.stdout


def parse_semver(value: object, where: str) -> tuple[int, int, int]:
    """只接受 X.Y.Z；其他形狀（含 pre-release）一律視為資料錯誤，不猜比較規則。"""
    match = _SEMVER.match(value) if isinstance(value, str) else None
    if match is None:
        raise DataError(f"{where} 的 version 不是 X.Y.Z：{value!r}")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def plugin_names(repo: str, ref: str) -> list[str]:
    """回傳 ref 上有 `.claude-plugin/plugin.json` 的 plugin 目錄名稱。"""
    out = _git(repo, "ls-tree", "-r", "--name-only", ref, "--", PLUGINS_DIR)
    names = sorted(
        {
            PurePosixPath(p).parts[1]
            for p in out.splitlines()
            if p.endswith(f"/{MANIFEST}") and len(PurePosixPath(p).parts) == 4
        }
    )
    if not names:
        raise DataError(f"{ref} 上找不到任何 {PLUGINS_DIR}/*/{MANIFEST}")
    return names


def is_shipped(path: str, plugins: set[str]) -> bool:
    """判斷改動路徑是否屬於某個 plugin 的出貨內容。"""
    parts = PurePosixPath(path).parts
    if len(parts) < 3 or parts[0] != PLUGINS_DIR or parts[1] not in plugins:
        return False
    rel = "/".join(parts[2:])
    if rel in (MANIFEST, PACKAGE):
        return False
    return "tests" not in parts[2:-1]


def versions_at(repo: str, ref: str, plugins: list[str]) -> dict[str, tuple[int, int, int]]:
    """讀取 ref 上每個版號檔的版號；檔案缺失或格式錯誤時拋 DataError。"""
    found: dict[str, tuple[int, int, int]] = {}
    for name in plugins:
        for rel in (MANIFEST, PACKAGE):
            path = f"{PLUGINS_DIR}/{name}/{rel}"
            raw = _git(repo, "show", f"{ref}:{path}")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                raise DataError(f"{ref}:{path} 不是合法 JSON：{e}") from e
            if not isinstance(data, dict):
                raise DataError(f"{ref}:{path} 不是 JSON 物件")
            found[path] = parse_semver(data.get("version"), f"{ref}:{path}")
    return found


def _fmt(v: tuple[int, int, int]) -> str:
    return ".".join(str(x) for x in v)


def check(repo: str, base: str, head: str) -> tuple[int, list[str]]:
    """回傳 (exit code, 訊息)。exit 2 的情況以 DataError 拋出。"""
    merge_base = _git(repo, "merge-base", base, head).strip()
    plugins = plugin_names(repo, head)
    changed = _git(repo, "diff", "--name-only", f"{merge_base}..{head}").splitlines()
    shipped = [p for p in changed if is_shipped(p, set(plugins))]
    if not shipped:
        return 0, ["[SKIP] 沒有改到 plugin 出貨內容，不需要升版"]

    head_versions = versions_at(repo, head, plugins)
    distinct = sorted(set(head_versions.values()))
    if len(distinct) != 1:
        lines = ["[FAIL] head 上的 plugin 版號不一致（lockstep 要求全部相同）："]
        lines += [f"  {path}: {_fmt(v)}" for path, v in sorted(head_versions.items())]
        lines.append("  修法：scripts/sync-plugin-versions.sh <新版號>")
        return 1, lines

    base_plugins = [p for p in plugin_names(repo, merge_base) if p in plugins]
    base_max = max(versions_at(repo, merge_base, base_plugins).values())
    new = distinct[0]
    if new <= base_max:
        lines = [
            f"[FAIL] 改到 plugin 出貨內容，但版號沒有升（base {_fmt(base_max)}，head {_fmt(new)}）。",
            "  版號不變時 claude plugin update 不會更新使用者的快取，合併的改動不會生效。",
            "  修法：scripts/sync-plugin-versions.sh <大於 base 的新版號>",
            "  觸發本檢查的檔案（最多列 10 筆）：",
        ]
        lines += [f"    {p}" for p in shipped[:10]]
        return 1, lines
    return 0, [f"[OK] plugin 版號 {_fmt(base_max)} -> {_fmt(new)}（{len(shipped)} 個出貨檔案改動）"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="比較基準（PR base SHA 或 push 前的 SHA）")
    parser.add_argument(
        "--head", required=True, help="要檢查的 commit（PR head SHA 或 push 後的 SHA）"
    )
    parser.add_argument("--repo", default=".", help="git repo 路徑（預設目前目錄）")
    args = parser.parse_args(argv)
    try:
        code, lines = check(args.repo, args.base, args.head)
    except DataError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 2
    stream = sys.stdout if code == 0 else sys.stderr
    for line in lines:
        print(line, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())

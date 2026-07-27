#!/usr/bin/env python3
"""掃描（並可選擇實際刪除）Claude Code plugin cache 中未被參照的舊版本目錄。

Claude Code 更新 marketplace plugin 時，只會在
`~/.claude/plugins/cache/<marketplace>/<plugin>/` 下新增一個版本目錄，從不刪除舊版本——
`installed_plugins.json` 對每個 `<plugin>@<marketplace>` 只記錄一筆目前釘選的
`installPath`，其餘版本目錄不會再被讀取，純粹是磁碟累積。這支 script 讀取安裝清單，
比對所有 marketplace 的 cache 目錄，列出（dry-run）或刪除（--apply）未被參照的版本目錄。

不會在沒有 --apply 的情況下刪除任何檔案。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def _load_active_paths() -> set[str]:
    path = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"[FAIL] {path} 不存在 -- 尚未安裝任何 Claude Code plugin", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"[FAIL] 無法讀取 {path}：{e}", file=sys.stderr)
        sys.exit(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"[FAIL] {path} 格式錯誤：{e}", file=sys.stderr)
        sys.exit(1)

    active: set[str] = set()
    for entries in data.get("plugins", {}).values():
        for entry in entries:
            install_path = entry.get("installPath")
            if install_path:
                active.add(str(Path(install_path).resolve()))
    return active


def _find_stale_dirs(cache_root: Path, active_paths: set[str]) -> list[Path]:
    stale: list[Path] = []
    if not cache_root.is_dir():
        return stale
    for marketplace_dir in sorted(cache_root.iterdir()):
        if not marketplace_dir.is_dir():
            continue
        for plugin_dir in sorted(marketplace_dir.iterdir()):
            if not plugin_dir.is_dir():
                continue
            for version_dir in sorted(plugin_dir.iterdir()):
                if not version_dir.is_dir():
                    continue
                if str(version_dir.resolve()) not in active_paths:
                    stale.append(version_dir)
    return stale


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def prune(cache_root: Path, dry_run: bool) -> int:
    active_paths = _load_active_paths()
    stale_dirs = _find_stale_dirs(cache_root, active_paths)

    total_bytes = 0
    for version_dir in stale_dirs:
        size = _dir_size(version_dir)
        total_bytes += size
        marker = "[DRY-RUN]" if dry_run else "[REMOVE]"
        print(f"{marker} {version_dir}  ({size / 1024:.0f} KB)")
        if not dry_run:
            shutil.rmtree(version_dir)

    print()
    print(f"共 {len(stale_dirs)} 個未被參照的舊版本目錄，合計約 {total_bytes / 1024 / 1024:.1f} MB")
    if dry_run:
        print("此為 dry-run，未實際刪除任何檔案。加上 --apply 才會真的刪除。")

    return 0


def main() -> int:
    cache_root = Path.home() / ".claude" / "plugins" / "cache"
    dry_run = "--apply" not in sys.argv
    return prune(cache_root, dry_run)


if __name__ == "__main__":
    sys.exit(main())

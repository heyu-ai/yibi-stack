#!/usr/bin/env python3
"""掃描（並可選擇實際刪除）Claude Code plugin cache 中未被參照的舊版本目錄。

Claude Code 更新 marketplace plugin 時，只會在
`~/.claude/plugins/cache/<marketplace>/<plugin>/` 下新增一個版本目錄，從不刪除舊版本——
`installed_plugins.json` 對每個 `<plugin>@<marketplace>` 記錄一份或多份安裝（user／local
scope 各一筆），每筆帶自己的 `installPath`；未被任何一筆參照的版本目錄不會再被讀取，
純粹是磁碟累積。這支 script 讀取安裝清單，比對所有 marketplace 的 cache 目錄，
列出（dry-run）或刪除（--apply）未被參照的版本目錄。

安全設計（本工具會呼叫 `shutil.rmtree`，故守衛的預設方向一律是「不刪」）：

- **Tri-state 安裝清單解析**：區分「確認為孤兒」與「無法確認」。清單缺檔、格式錯誤、
  結構非預期、任一筆缺 `installPath`、或推導出的 active set 為空時，一律 fail loud 退出，
  絕不把「讀不出有效安裝」誤當成「整個 cache 都是孤兒」。
- **刪除前重新確認**：每次 `rmtree` 前重讀安裝清單，若該目錄在掃描後已被重新釘選則跳過；
  若當下讀不到清單，同樣跳過該筆而非依舊快照刪除。
- **不跟隨 symlink**：marketplace／plugin／version 三層皆拒絕 symlink，並斷言每個刪除
  候選解析後仍位於 cache root 內，避免刪到 cache 之外的真實目錄。

不會在沒有 --apply 的情況下刪除任何檔案。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

_MANIFEST_RELATIVE = (".claude", "plugins", "installed_plugins.json")

# 安裝中的版本目錄會先被建立並填充，`installPath` 之後才寫進 installed_plugins.json。
# 在那段窗口內，該目錄在任何一次重讀下都「長得像孤兒」——刪除前重新確認也分辨不出來。
# 因此再加一道時間門檻：近期有異動的目錄一律不碰，留到下次執行再判斷。
# 門檻取 300 秒有實測依據：本機 50 個版本目錄中，5 分鐘內有異動的是 0 個、
# 1 小時內是 21 個，所以 300 秒足以覆蓋安裝窗口，又不會誤擋真正該回收的舊版本。
_RECENT_ACTIVITY_SECONDS = 300


def _manifest_path() -> Path:
    return Path.home().joinpath(*_MANIFEST_RELATIVE)


def _read_active_paths() -> set[str]:
    """讀取安裝清單並回傳目前釘選的絕對路徑集合。

    任何「無法確認 active set」的情況都 raise RuntimeError，由呼叫端決定是 fail loud
    退出（初次載入）還是跳過該筆刪除（刪除前重新確認）。永遠不會回傳空集合。
    """
    path = _manifest_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise RuntimeError(f"{path} 不存在 -- 尚未安裝任何 Claude Code plugin") from e
    except OSError as e:
        raise RuntimeError(f"無法讀取 {path}：{e}") from e

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{path} 格式錯誤：{e}") from e

    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict):
        raise RuntimeError(f"{path} 結構非預期：頂層缺少 dict 型別的 `plugins` 欄位")

    active: set[str] = set()
    for key, entries in plugins.items():
        if not isinstance(entries, list):
            raise RuntimeError(f"{path} 結構非預期：`plugins[{key!r}]` 不是 list")
        for entry in entries:
            if not isinstance(entry, dict):
                raise RuntimeError(f"{path} 結構非預期：`plugins[{key!r}]` 內含非 dict 項目")
            install_path = entry.get("installPath")
            if not install_path:
                raise RuntimeError(
                    f"{path} 中 `{key}` 有一筆安裝缺少 `installPath`；"
                    "無法確認它釘選哪個目錄，中止以免誤刪"
                )
            active.add(str(Path(install_path).resolve()))

    if not active:
        raise RuntimeError(
            f"{path} 可解析但推導不出任何 `installPath`；"
            "拒絕把整個 cache 判定為孤兒（如確要清空請手動刪除）"
        )
    return active


def _load_active_paths() -> set[str]:
    """初次載入：無法確認 active set 時 fail loud 退出。"""
    try:
        return _read_active_paths()
    except RuntimeError as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        sys.exit(1)


def _is_within(path: Path, root: Path) -> bool:
    """path（已解析）是否位於 root（已解析）之內。

    抽成獨立述詞是為了可被單獨測試：在三層 symlink 拒絕就位的前提下，呼叫端那個
    containment 斷言理論上不可達，若內嵌在迴圈裡就沒有任何測試能證明它仍然正確。
    這是 belt-and-braces——刪除是不可逆的，多一道成本一行的防線值得，但它必須是
    一道「被證明過」的防線。
    """
    return path == root or root in path.parents


def _find_stale_dirs(cache_root: Path, active_paths: set[str]) -> tuple[list[Path], list[Path]]:
    """回傳 (未被參照的版本目錄, [(被跳過的路徑, 原因)])。

    每個被排除的項目都帶明確原因並回報，不做靜默丟棄——使用者要能分辨
    「這個目錄沒被列出」是因為它安全、還是因為工具不敢碰它。
    """
    stale: list[Path] = []
    skipped: list[tuple[Path, str]] = []
    if not cache_root.is_dir():
        return stale, skipped

    root_resolved = cache_root.resolve()
    now = time.time()

    def _walk(parent: Path) -> list[Path]:
        children: list[Path] = []
        for child in sorted(parent.iterdir()):
            if child.is_symlink():
                skipped.append((child, "symlink，不跟隨以免刪到 cache root 之外"))
                continue
            if not child.is_dir():
                skipped.append((child, "非目錄，不列入版本目錄候選"))
                continue
            children.append(child)
        return children

    for marketplace_dir in _walk(cache_root):
        for plugin_dir in _walk(marketplace_dir):
            for version_dir in _walk(plugin_dir):
                resolved = version_dir.resolve()
                if not _is_within(resolved, root_resolved):
                    # 三層 symlink 拒絕就位時理論上不可達；留作 belt-and-braces。
                    skipped.append((version_dir, "解析後位於 cache root 之外"))
                    continue
                if str(resolved) in active_paths:
                    continue
                try:
                    age = now - version_dir.stat().st_mtime
                except OSError as e:
                    skipped.append((version_dir, f"無法讀取 mtime（{e}），不確認就不刪"))
                    continue
                if age < _RECENT_ACTIVITY_SECONDS:
                    skipped.append(
                        (
                            version_dir,
                            f"最近 {_RECENT_ACTIVITY_SECONDS} 秒內有異動，可能是安裝中的目錄",
                        )
                    )
                    continue
                stale.append(version_dir)
    return stale, skipped


def _dir_size(path: Path) -> int:
    """加總目錄下所有一般檔案大小；掃描過程中消失的檔案跳過，不中斷整個流程。"""
    total = 0
    for f in path.rglob("*"):
        try:
            if f.is_symlink() or not f.is_file():
                continue
            total += f.stat().st_size
        except OSError:
            continue
    return total


def prune(cache_root: Path, dry_run: bool) -> int:
    active_paths = _load_active_paths()
    stale_dirs, skipped = _find_stale_dirs(cache_root, active_paths)

    for path, reason in skipped:
        print(f"[SKIP] {path} -- {reason}", file=sys.stderr)

    total_bytes = 0
    removed = 0
    failures = 0
    # 兩個計數器刻意分開：「確認後發現被重新釘選」是良性結果（工具正確地沒動它），
    # 「根本無法確認」則與初次載入失敗是同一種輸入，必須反映在退出碼上，否則同一個
    # 壞掉的安裝清單會因為「什麼時候壞的」而給出 exit 1 或 exit 0 兩種相反答案。
    skipped_repinned = 0
    skipped_unconfirmed = 0

    for version_dir in stale_dirs:
        size = _dir_size(version_dir)

        if dry_run:
            print(f"[DRY-RUN] {version_dir}  ({size / 1024:.0f} KB)")
            total_bytes += size
            continue

        # AC-6：刪除前以「當下」的安裝清單重新確認，不依賴掃描時的快照。
        try:
            current_active = _read_active_paths()
        except RuntimeError as e:
            print(f"[FAIL] {version_dir} -- 無法重新確認安裝清單（{e}），跳過", file=sys.stderr)
            skipped_unconfirmed += 1
            continue
        if str(version_dir.resolve()) in current_active:
            print(f"[SKIP] {version_dir} -- 掃描後已被重新釘選，跳過", file=sys.stderr)
            skipped_repinned += 1
            continue

        try:
            shutil.rmtree(version_dir)
        except OSError as e:
            print(f"[FAIL] 無法刪除 {version_dir}：{e}", file=sys.stderr)
            failures += 1
            continue

        # 先刪成功才印 [REMOVE]，避免輸出宣稱一個沒發生的刪除。
        print(f"[REMOVE] {version_dir}  ({size / 1024:.0f} KB)")
        total_bytes += size
        removed += 1

    total_mb = total_bytes / 1024 / 1024

    print()
    if dry_run:
        print(f"共 {len(stale_dirs)} 個未被參照的舊版本目錄，合計約 {total_mb:.1f} MB")
        print("此為 dry-run，未實際刪除任何檔案。加上 --apply 才會真的刪除。")
    else:
        print(f"實際刪除 {removed} 個目錄，回收約 {total_mb:.1f} MB")
        if skipped_repinned:
            print(f"另有 {skipped_repinned} 個目錄在刪除前確認為已重新釘選而跳過")
        if skipped_unconfirmed:
            print(f"另有 {skipped_unconfirmed} 個目錄無法重新確認而跳過（詳見上方 [FAIL] 訊息）")
        if failures:
            print(f"另有 {failures} 個目錄刪除失敗（詳見上方 [FAIL] 訊息）")

    return 1 if (failures or skipped_unconfirmed) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="prune_plugin_cache.py",
        description="清理 ~/.claude/plugins/cache/ 下未被參照的舊版本 plugin 目錄。",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="實際刪除；未指定時為 dry-run，只列出候選目錄與可回收空間。",
    )
    args = parser.parse_args(argv)

    cache_root = Path.home() / ".claude" / "plugins" / "cache"
    return prune(cache_root, dry_run=not args.apply)


if __name__ == "__main__":
    sys.exit(main())

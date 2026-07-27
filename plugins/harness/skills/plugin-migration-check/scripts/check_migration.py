#!/usr/bin/env python3
"""偵測 yibi-stack marketplace 內已改名/合併/移除的孤兒 plugin 安裝，並印出修復指令。

Claude Code 的 plugin 系統沒有 pack 改名/合併/拆分的遷移機制：pack 一旦從
marketplace.json 消失，任何使用者原本裝的同名 plugin 就變成孤兒——installed_plugins.json
裡的紀錄可能繼續留著（指向再也抓不到新內容的舊 cache），也可能被自動清掉但不會自動
補裝新名稱的 pack。這支 script 讀取本機安裝清單，比對已知的遷移歷史，印出使用者需要
手動執行的 uninstall/install 指令。

不會自動執行任何 `claude plugin` 指令——只印出建議，交由使用者自行執行。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MARKETPLACE_SLUG = "yibi-stack"

# 遷移歷史（新增一筆 pack rename/split/merge/delete 時，務必同步更新此表；
# 這是本 script 唯一的知識來源，不會自動推導）。
# old_pack -> 目標 pack 清單；空 list 代表「已移除，無替代方案」。
MIGRATION_MAP: dict[str, list[str]] = {
    "pr-flow": ["dev-cycle"],
    "bash-hygiene": ["harness"],
    "tdd": ["methodology", "dev-cycle"],
    "util": ["dev-cycle"],
    "writing": [],
}

# 目前 marketplace 有效的 pack 清單（static fallback；若讀不到使用者本機的
# marketplace 快取才會用到這份備援清單，新增/刪除 pack 時也要同步更新）。
CURRENT_PACKS_FALLBACK = frozenset(
    {"harness", "sdd", "growth", "dev-cycle", "3rd-tools", "methodology"}
)


def _load_installed_plugins() -> dict[str, list[dict]]:
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
    return data.get("plugins", {})


def _load_current_packs() -> tuple[frozenset[str], bool]:
    """回傳 (目前有效 pack 名稱集合, 是否為即時讀取而非 fallback)。"""
    cache_path = (
        Path.home()
        / ".claude"
        / "plugins"
        / "marketplaces"
        / MARKETPLACE_SLUG
        / ".claude-plugin"
        / "marketplace.json"
    )
    try:
        text = cache_path.read_text(encoding="utf-8")
        data = json.loads(text)
        names = {p["name"] for p in data.get("plugins", []) if "name" in p}
        if names:
            return frozenset(names), True
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass
    return CURRENT_PACKS_FALLBACK, False


def check() -> int:
    installed = _load_installed_plugins()
    current_packs, is_live = _load_current_packs()

    suffix = f"@{MARKETPLACE_SLUG}"
    yibi_installed = {
        name[: -len(suffix)]: entries
        for name, entries in installed.items()
        if name.endswith(suffix)
    }

    if not yibi_installed:
        print(f"[OK] 未安裝任何 {MARKETPLACE_SLUG} plugin，無需檢查")
        return 0

    print(f"=== {MARKETPLACE_SLUG} plugin migration check ===")
    if not is_live:
        print("[WARN] 讀不到本機 marketplace 快取，改用內建靜態 pack 清單 (可能不是最新狀態)")
    print()

    stale_count = 0
    ok_count = 0

    for pack, entries in sorted(yibi_installed.items()):
        if pack in current_packs:
            ok_count += 1
            continue

        stale_count += 1
        version = entries[0].get("version", "?") if entries else "?"
        targets = MIGRATION_MAP.get(pack)

        if targets is None:
            print(
                f"[WARN] {pack}@{MARKETPLACE_SLUG}（目前安裝版本 {version}）"
                "已從 marketplace 移除，且找不到已知的遷移路徑。"
            )
            print("  請至 https://github.com/heyu-ai/yibi-stack 確認目前 pack 清單，或手動移除：")
            print(f"    claude plugin uninstall {pack}@{MARKETPLACE_SLUG}")
        elif not targets:
            print(
                f"[removed] {pack}@{MARKETPLACE_SLUG}（目前安裝版本 {version}）已移除，無替代方案："
            )
            print(f"    claude plugin uninstall {pack}@{MARKETPLACE_SLUG}")
        else:
            install_targets = " ".join(f"{t}@{MARKETPLACE_SLUG}" for t in targets)
            print(
                f"[stale] {pack}@{MARKETPLACE_SLUG}（目前安裝版本 {version}）"
                "已改名/合併，建議執行："
            )
            print(f"    claude plugin uninstall {pack}@{MARKETPLACE_SLUG}")
            print(f"    claude plugin install {install_targets}")
        print()

    print("=== 摘要 ===")
    print(f"{stale_count} 個孤兒安裝需要處理，{ok_count} 個正常")

    return 1 if stale_count else 0


if __name__ == "__main__":
    sys.exit(check())

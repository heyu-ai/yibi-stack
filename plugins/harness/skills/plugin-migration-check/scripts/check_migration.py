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
from typing import NamedTuple

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


class RemovedSkill(NamedTuple):
    """pack 仍在、但其中某支 skill 被刪除的紀錄。MIGRATION_MAP 只管整個 pack，看不到這種情況。"""

    pack: str  # 目前（最後）收容它的 pack
    removed_in: tuple[int, int, int]  # 從哪個版本起不再提供
    former_packs: frozenset[str]  # 歷史上曾收容它的 pack；裝了其中任一個就提示
    replacement: str  # 給使用者看的替代做法


# skill 層級的移除歷史（刪除 pack 內的 skill 時，務必同步更新此表）。
REMOVED_SKILLS: dict[str, RemovedSkill] = {
    "tdd-kentbeck": RemovedSkill(
        pack="methodology",
        removed_in=(1, 23, 0),
        former_packs=frozenset({"methodology", "tdd"}),
        replacement=(
            "TDD 改由 /pr-cycle-deep、/pr-cycle-fast 的 red-first gate 在 review 前機械檢查；"
            "專案需提供 scripts/red-first-check.py 才會生效（參考 heyu-ai/yibi-mvp#2017）"
        ),
    ),
    "flutter-tdd": RemovedSkill(
        pack="methodology",
        removed_in=(1, 23, 0),
        former_packs=frozenset({"methodology", "tdd"}),
        replacement="技術棧專屬的 TDD skill 改由各專案自行決定並在自己的 repo 維護",
    ),
}

# make install 會把 skill symlink 到這兩處；skill 被刪後 symlink 會指向不存在的目錄
SKILL_LINK_DIRS = (Path(".claude") / "skills", Path(".agents") / "skills")


def _parse_version(text: str) -> tuple[int, int, int] | None:
    parts = text.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return int(parts[0]), int(parts[1]), int(parts[2])


def _fmt(version: tuple[int, int, int]) -> str:
    return ".".join(str(n) for n in version)


def _removed_skill_notices(yibi_installed: dict[str, list[dict]]) -> list[str]:
    """已安裝的 pack 若曾收容被刪的 skill，回傳給使用者的提示行（只是資訊，不計入待處理）。"""
    lines: list[str] = []
    for skill, info in sorted(REMOVED_SKILLS.items()):
        holders = sorted(info.former_packs & yibi_installed.keys())
        if not holders:
            continue
        removed = _fmt(info.removed_in)
        entries = yibi_installed.get(info.pack) or []
        version = _parse_version(str(entries[0].get("version", ""))) if entries else None
        if info.pack in yibi_installed and version is not None and version < info.removed_in:
            when = f"更新到 {info.pack} {removed} 後會消失"
        else:
            when = f"已於 {info.pack} {removed} 移除"
        lines.append(f"[notice] {skill}（你裝了 {', '.join(holders)}）{when}。")
        lines.append(f"    替代做法：{info.replacement}")
    return lines


def _dangling_skill_links() -> list[Path]:
    """被刪 skill 殘留、指向不存在目錄的 symlink（make install 使用者也適用）。"""
    found: list[Path] = []
    for base in SKILL_LINK_DIRS:
        for skill in sorted(REMOVED_SKILLS):
            link = Path.home() / base / skill
            if link.is_symlink() and not link.exists():
                found.append(link)
    return found


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

    dangling_links = _dangling_skill_links()

    if not yibi_installed and not dangling_links:
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

    for link in dangling_links:
        stale_count += 1
        print(f"[stale-link] {link} 指向已刪除的 skill，建議移除這個 symlink：")
        print(f"    rm {link}")
        print()

    notices = _removed_skill_notices(yibi_installed)
    for line in notices:
        print(line)
    if notices:
        print()

    print("=== 摘要 ===")
    print(f"{stale_count} 個孤兒安裝需要處理，{ok_count} 個正常")

    return 1 if stale_count else 0


if __name__ == "__main__":
    sys.exit(check())

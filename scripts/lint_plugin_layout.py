#!/usr/bin/env python3
"""Lint：plugin pack 結構一致性——symlink、自我引用路徑、marketplace 登記、版本 lockstep。

本 repo 的 pack 名稱同時扮演兩個角色：**分類標籤**與**檔案系統路徑**。只有前者是設計決策，
後者卻被寫進 SKILL.md 的 self-locate fallback、頂層 symlink、marketplace 登記與 CI 設定。
於是「把一個 skill 換個 pack」這種語意操作，會變成跨十幾個檔的機械重構——而其中一類失誤
**不會有任何訊號**。本 lint 就是為那一類而存在。

四項斷言：

1. **頂層 symlink 全部可解析**——`skills/<name>` 與 `commands/<cmd>.md` 是指向
   `plugins/<pack>/...` 的 symlink。搬動或刪除 plugin 端而漏了頂層，會留下 dangling
   symlink，讓 `lint_skill_bash.py` 讀取失敗。那是「壞掉後連偵錯工具都跑不了」的缺口。

2. **SKILL.md / command 的自我引用路徑與 cache key 必須指向自己所屬的 pack**——三個 skill
   （pr-retrospective / pr-control-log / pr-cycle-fast）用三段 fallback 定位自己的 scripts：
   plugin cache（`<pack>@yibi-stack`）→ `$HOME/.claude/skills/<name>/`（**這三者都沒有頂層
   symlink，故此段從未被 make install 建出來，是死的**）→ in-repo 相對路徑
   `plugins/<pack>/skills/<name>/`。所以 tier-3 是唯一備援。pack 改名時漏改它，行為是
   **靜默降級**：三段全 miss，然後 `[FAIL]` 訊息叫使用者去安裝一個已不存在的 pack。
   這是本檔存在的主要理由。

   判準：引用路徑的 `<skill>` 與該檔自己的 skill 名相同 -> 視為自我引用，pack 必須相符；
   不同 -> 視為跨 pack 引用（如 codex-review 引用 pr-cycle-deep 的測試路徑），只驗存在。
   `<pack>@yibi-stack` 一律要求等於自己所屬 pack（目前 repo 內 14 處全數符合）。

3. **marketplace.json 與 pack 目錄雙向一致**——每筆 `source` 目錄存在，且
   `name` == `plugin.json.name` == `package.json.name`；反向亦然：任何有 `package.json`
   的 pack 目錄都必須被登記。反向這條補掉一個靜默破洞：未登記的 pack 會被
   `lint_skill_scope.py` 當成「外部 plugin」而豁免其 namespace 檢查。

4. **`package.json.version` == `.claude-plugin/plugin.json.version`**——目前無任何 CI 檢查，
   只有一個本機 warn-only hookify 規則。走 `make release` 時由 sync_plugin_versions.py 保證，
   手動 bump 單一 pack 則無防線。

Usage:
  python3 scripts/lint_plugin_layout.py

Exit code:
  0 -> 全部通過
  1 -> 有違規
  2 -> 設定錯誤（marketplace.json / plugins 目錄缺失或格式錯誤）
"""

import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
PLUGINS_DIR = REPO_ROOT / "plugins"
SKILLS_DIR = REPO_ROOT / "skills"
COMMANDS_DIR = REPO_ROOT / "commands"

MARKETPLACE_SLUG = "yibi-stack"

# plugins/<pack>/skills/<skill>（existence 檢查用；nested sub-skill 只取第一段，
# 足以判斷「這個 skill 目錄本身存在」，完整路徑的自我引用比對交給下面的 tail-based 檢查）
_PATH_RE = re.compile(r"plugins/([a-z0-9][a-z0-9-]*)/skills/([a-z0-9][a-z0-9-]*)")
# pack-root 形狀的 self-locate 賦值，例：SDD_ROOT="plugins/sdd"（無 /skills/ 段——
# spectra-amplifier 的 tier-3 自我定位到整個 pack，而非特定 skill 子目錄）。
# `_ROOT` 後綴限制縮小誤判面：本 repo 四個既有 self-locate 變數
# （CL_ROOT/PCF_ROOT/RETRO_ROOT/SDD_ROOT）都以 `_ROOT` 結尾，任意 `VAR="plugins/<pack>"`
# 賦值不應該全部被當成 self-locate（可能是無關的迭代/查表邏輯）。
_PACKROOT_ASSIGN_RE = re.compile(
    r'(?P<var>[A-Z][A-Z0-9_]*_ROOT)="plugins/(?P<pack>[a-z0-9][a-z0-9-]*)"'
)
# <pack>@yibi-stack
_CACHE_KEY_RE = re.compile(rf"([a-z0-9][a-z0-9-]*)@{re.escape(MARKETPLACE_SLUG)}\b")

# 合法的跨 pack cache-key 引用（例：某 skill 明確要求使用者安裝另一個 pack）。
# 目前為空——repo 內 14 處 `<pack>@yibi-stack` 全部指向自己所屬 pack。
# 新增例外時請一併說明理由，不要為了讓 lint 過而加。
CACHE_KEY_EXCEPTIONS: set[tuple[str, str]] = set()  # (相對檔案路徑, 被引用的 pack)


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


# --- 1. 頂層 symlink ----------------------------------------------------------


def check_root_symlinks() -> list[str]:
    """頂層 skills/ 與 commands/ 的每個項目都必須可解析。"""
    errors: list[str] = []
    targets: list[Path] = []
    if SKILLS_DIR.is_dir():
        targets.extend(sorted(SKILLS_DIR.iterdir()))
    if COMMANDS_DIR.is_dir():
        targets.extend(sorted(p for p in COMMANDS_DIR.iterdir() if p.suffix == ".md"))

    for entry in targets:
        if entry.exists():
            continue
        link = os.readlink(entry) if entry.is_symlink() else "(不是 symlink)"
        errors.append(
            f"  {_rel(entry)} -> {link}：無法解析。"
            f"搬動請重指到新路徑（與 git mv 同一 commit）；刪除請 git rm 此 symlink。"
        )
    return errors


# --- 2. 自我引用路徑與 cache key ----------------------------------------------


def _owning_pack(path: Path) -> str:
    """plugins/<pack>/... -> <pack>"""
    return path.relative_to(PLUGINS_DIR).parts[0]


def _own_skill_tail(path: Path) -> str | None:
    """plugins/<pack>/skills/<a>/<b>/.../SKILL.md -> "a/b/..."（skills/ 之後、SKILL.md
    之前的完整相對路徑，用 `/` join）；非 skill 檔回傳 None。

    對 flat skill（plugins/alpha/skills/foo/SKILL.md）回傳 "foo"；對 nested sub-skill
    （plugins/growth/skills/mycelium/recap/SKILL.md）回傳 "mycelium/recap"——回傳完整尾段
    而非只取 leaf，是因為自我引用比對需要整條路徑相符，只比 leaf 會把
    `plugins/other/skills/mycelium/recap` 誤判成跨 pack 引用（leaf "recap" 對得上，
    但沒人比對中間的 "mycelium" 段）。
    """
    parts = path.relative_to(PLUGINS_DIR).parts
    if len(parts) >= 4 and parts[1] == "skills" and parts[-1] == "SKILL.md":
        return "/".join(parts[2:-1])
    return None


def _iter_pack_docs() -> list[Path]:
    if not PLUGINS_DIR.is_dir():
        return []
    docs = list(PLUGINS_DIR.glob("*/skills/**/SKILL.md"))
    docs.extend(PLUGINS_DIR.glob("*/commands/*.md"))
    return sorted(set(docs))


def _dedupe(errors: list[str]) -> list[str]:
    """保序去重。

    self-locate fallback 常在同一行寫兩次同一條路徑（`[ -r "<path>/x" ]` 的判斷式與
    緊接的賦值），逐一 finditer 會產生完全相同的兩行輸出。重複訊息會稀釋真正的問題數，
    讓讀者以為問題比實際多。
    """
    seen: set[str] = set()
    out: list[str] = []
    for e in errors:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def check_pack_references() -> list[str]:
    errors: list[str] = []
    for doc in _iter_pack_docs():
        try:
            text = doc.read_text(encoding="utf-8")
        except OSError as e:
            errors.append(f"  {_rel(doc)}：無法讀取（{type(e).__name__}: {e.strerror}）")
            continue

        owner = _owning_pack(doc)
        own_tail = _own_skill_tail(doc)
        rel_doc = _rel(doc)

        # (a) 存在性檢查：referenced skill 目錄是否存在。只取 skills/ 後第一段即可判斷
        # 「這個目錄本身存在」；自我引用的 pack 正確性交給 (b) 的完整 tail 比對。
        for m in _PATH_RE.finditer(text):
            ref_pack, ref_skill = m.group(1), m.group(2)
            line_no = text[: m.start()].count("\n") + 1
            ref_dir = PLUGINS_DIR / ref_pack / "skills" / ref_skill
            if not ref_dir.is_dir():
                errors.append(
                    f"  {rel_doc}:{line_no}: 引用不存在的路徑 "
                    f"plugins/{ref_pack}/skills/{ref_skill}/"
                )

        # (b) 自我引用（skill-form）：比對完整尾段而非 leaf，nested sub-skill 才抓得到。
        # 用該檔自己的 own_tail 動態組 regex，只匹配「引用路徑以我自己的完整尾段結尾」
        # 的那些出現——與 (a) 分開跑，故存在性錯誤與自我引用錯誤互不遮蔽彼此。
        if own_tail is not None:
            tail_re = re.compile(rf"plugins/([a-z0-9][a-z0-9-]*)/skills/{re.escape(own_tail)}\b")
            for m in tail_re.finditer(text):
                ref_pack = m.group(1)
                line_no = text[: m.start()].count("\n") + 1
                if ref_pack != owner:
                    errors.append(
                        f"  {rel_doc}:{line_no}: 自我引用指向錯誤的 pack——"
                        f"寫的是 plugins/{ref_pack}/，但本 skill 住在 plugins/{owner}/。"
                        f"這是 self-locate fallback 的最後一段，寫錯會靜默降級。"
                    )

        # (c) 自我引用（pack-root form）：spectra-amplifier 的 tier-3 自我定位到整個 pack
        # 而非 skill 子目錄，形如 `SDD_ROOT="plugins/sdd"`——(a)/(b) 的 /skills/ 前提在此
        # 不成立，需要獨立偵測。
        for m in _PACKROOT_ASSIGN_RE.finditer(text):
            ref_pack = m.group("pack")
            line_no = text[: m.start()].count("\n") + 1
            if ref_pack != owner:
                errors.append(
                    f"  {rel_doc}:{line_no}: pack-root 自我引用指向錯誤的 pack——"
                    f'`{m.group("var")}="plugins/{ref_pack}"`，但本文件住在 plugins/{owner}/。'
                    f"這是 self-locate fallback 的最後一段，寫錯會靜默降級。"
                )

        for m in _CACHE_KEY_RE.finditer(text):
            ref_pack = m.group(1)
            line_no = text[: m.start()].count("\n") + 1
            if (rel_doc, ref_pack) in CACHE_KEY_EXCEPTIONS:
                continue
            if not (PLUGINS_DIR / ref_pack).is_dir():
                errors.append(
                    f"  {rel_doc}:{line_no}: cache key "
                    f"'{ref_pack}@{MARKETPLACE_SLUG}' 指向不存在的 pack"
                )
            elif ref_pack != owner:
                errors.append(
                    f"  {rel_doc}:{line_no}: cache key "
                    f"'{ref_pack}@{MARKETPLACE_SLUG}' 與所屬 pack '{owner}' 不符。"
                    f"若為蓄意的跨 pack 引用，請加進 CACHE_KEY_EXCEPTIONS 並說明理由。"
                )
    return _dedupe(errors)


# --- 3. marketplace 雙向一致 --------------------------------------------------


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def check_marketplace(entries: list[dict]) -> list[str]:
    errors: list[str] = []
    # resolved source 目錄集合，不是 name 集合——目錄 basename 與 marketplace 登記的
    # name 是兩個獨立識別符，可以不同（如 source: ./plugins/foo 但 name: "bar"）。
    # 用 name 比對目錄 basename 會誤報一個正確登記的 pack「未登記」。
    registered_dirs: set[Path] = set()

    for entry in entries:
        name = entry.get("name")
        source = entry.get("source")
        if not name or not isinstance(source, str):
            errors.append(f"  marketplace.json：項目缺少 name 或 source（{entry!r}）")
            continue

        pack_dir = (REPO_ROOT / source).resolve()
        if not pack_dir.is_dir():
            errors.append(f"  marketplace.json：'{name}' 的 source '{source}' 目錄不存在")
            continue
        registered_dirs.add(pack_dir)

        for rel_path in (
            Path(".claude-plugin") / "plugin.json",
            Path("package.json"),
        ):
            data = _read_json(pack_dir / rel_path)
            if data is None:
                errors.append(
                    f"  {source}/{rel_path}：缺失或格式錯誤（marketplace 已登記 '{name}'）"
                )
            elif data.get("name") != name:
                errors.append(
                    f"  {source}/{rel_path}：name 為 '{data.get('name')}'，"
                    f"與 marketplace.json 的 '{name}' 不符"
                )

    # 反向：有 package.json **或** plugin.json 的 pack 目錄都必須被登記，否則
    # lint_skill_scope 會靜默豁免它。`.claude-plugin/plugin.json` 才是 Claude Code
    # 實際讀的 manifest，`package.json` 只是 repo 記帳用——只認 package.json 存在
    # 會讓「只有 plugin.json」的未登記 pack 逃過這道檢查。
    for pack_dir in sorted(PLUGINS_DIR.iterdir()) if PLUGINS_DIR.is_dir() else []:
        if not pack_dir.is_dir():
            continue
        has_manifest = (pack_dir / "package.json").is_file() or (
            pack_dir / ".claude-plugin" / "plugin.json"
        ).is_file()
        if not has_manifest:
            continue
        if pack_dir.resolve() not in registered_dirs:
            errors.append(
                f"  plugins/{pack_dir.name}/ 有 package.json 或 plugin.json 但未登記進"
                f" marketplace.json。未登記的 pack 會被 lint_skill_scope.py 當成外部"
                f" plugin 而豁免檢查。"
            )
    return errors


# --- 4. 版本 lockstep ---------------------------------------------------------


def check_version_lockstep() -> list[str]:
    errors: list[str] = []
    if not PLUGINS_DIR.is_dir():
        return errors
    for pack_dir in sorted(PLUGINS_DIR.iterdir()):
        if not pack_dir.is_dir():
            continue
        pkg = _read_json(pack_dir / "package.json")
        plg = _read_json(pack_dir / ".claude-plugin" / "plugin.json")
        if pkg is None or plg is None:
            continue  # 非 plugin 目錄（如 README-only container），由 check 3 的反向檢查涵蓋
        if pkg.get("version") != plg.get("version"):
            errors.append(
                f"  plugins/{pack_dir.name}：package.json 版本 '{pkg.get('version')}' "
                f"!= plugin.json 版本 '{plg.get('version')}'。"
                f"兩者必須同步（make release 會自動處理；手動 bump 需自行同步）。"
            )
    return errors


# --- main ---------------------------------------------------------------------


def main() -> int:
    if not PLUGINS_DIR.is_dir():
        print(f"[FAIL] 找不到 plugins 目錄：{PLUGINS_DIR}", file=sys.stderr)
        return 2
    market = _read_json(MARKETPLACE)
    if market is None:
        print(f"[FAIL] 無法讀取或解析 {_rel(MARKETPLACE)}", file=sys.stderr)
        return 2
    entries = market.get("plugins")
    if not isinstance(entries, list) or not entries:
        print(f"[FAIL] {_rel(MARKETPLACE)} 未列出任何 plugin", file=sys.stderr)
        return 2

    sections = [
        ("頂層 symlink 可解析", check_root_symlinks()),
        ("pack 自我引用路徑與 cache key", check_pack_references()),
        ("marketplace 與 pack 目錄雙向一致", check_marketplace(entries)),
        ("package.json / plugin.json 版本 lockstep", check_version_lockstep()),
    ]

    failed = [(label, errs) for label, errs in sections if errs]
    if failed:
        total = sum(len(errs) for _, errs in failed)
        print(f"[FAIL] plugin pack 結構檢查未通過（{total} 個問題）：", file=sys.stderr)
        for label, errs in failed:
            print(f"\n[{label}]", file=sys.stderr)
            for e in errs:
                print(e, file=sys.stderr)
        return 1

    print(f"[OK] plugin pack 結構檢查通過（{len(entries)} 個已登記 pack，4 項斷言）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

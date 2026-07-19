#!/usr/bin/env python3
"""Lint：偵測 SKILL.md description 觸發詞高度重疊的 skill pair（over-trigger 風險）。

背景——yibi-stack 沒有 per-skill 觸發準確度 eval，只能靠作者人工在 description 裡寫
「請改用 X」互斥文字硬擋 over-trigger（見 rule 11「Trigger Coverage」一節）。
本 lint 是確定性靜態偵測器：抽取每個 skill description 的觸發關鍵字，兩兩算重疊分數，
超門檻的 pair 印出來讓作者人工複查是否需要補 negative-trigger 文字或收斂觸發詞。

**掃描範圍**：`skills/*/SKILL.md`（repo-root，含 symlink 到 plugin 的全域 skill）
與 `plugins/<plugin>/skills/` 底下任意深度的 SKILL.md（含巢狀 sub-skill，
plugin-only、未 symlink 到 `skills/` 的 project-scope skill），依 realpath 去重——
一份實體檔案只算一次，不會因為同時被 `skills/` symlink、plugin 真實路徑，或
plugin 內部另一個 symlink 命中而重複計分。

**已知限制（暫不修，MVP 範圍內尚未實際發生）**：輸出用的 skill 名稱只取目錄的
leaf name（如 `recap`），不含 plugin/路徑前綴。若未來出現兩個不同 plugin 底下
剛好同名的 skill 目錄，`[WARN]` 訊息會印出如 `recap <-> recap` 而無法從名稱本身
分辨是哪兩個檔案——目前 repo 內經驗證無此碰撞（見 mob review 討論）。真的發生時
再改成印相對路徑，不在此 MVP 提前處理。

**演算法**（無 CJK 斷詞依賴，純 regex）：
- 先剝除 negative-trigger redirect 子句（「請改用 /X」「退回 /X」）：被導向的兄弟 skill
  名是 over-trigger 的『解法』而非觸發詞，計入會讓互相 redirect 的 pair 因彼此的名字虛高。
- ASCII 詞：`[A-Za-z][A-Za-z0-9_-]+`，小寫化後整詞當關鍵字（如 PR、CI、LGTM、codex）。
- CJK：對連續中文字元跑滑動視窗抽 bigram（2 字元 shingle），濾掉一份常見「樣板虛詞」
  bigram 清單（觸發、情境、使用……這些字幾乎每份 description 都會出現，不濾會讓所有
  pair 都「重疊」，訊號消失）。
- 兩份 keyword set 算 Jaccard similarity（交集 / 聯集）；達到 `--threshold` 才列為風險 pair。

門檻與 stopword 清單是經驗法則，不是精確語意分析——用途是「提示人工複查」，不是自動判準。
覺得漏報/誤報時，用 `--threshold` 調整，或編輯 `_CJK_STOPWORDS`。

Usage:
  python3 scripts/lint_skill_overlap.py                  # warn-only（預設）
  python3 scripts/lint_skill_overlap.py --fail            # 有重疊達到門檻 -> exit 1
  python3 scripts/lint_skill_overlap.py --threshold 0.25  # 調整靈敏度（預設 0.12）

Exit code:
  0 -> 無重疊達到門檻，或未加 --fail（warn-only 模式恆回 0）
  1 -> --fail 模式且有重疊達到門檻
  2 -> 設定錯誤（skills 目錄缺失）
"""

import re
import sys
from itertools import combinations
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
PLUGINS_DIR = REPO_ROOT / "plugins"

DEFAULT_THRESHOLD = 0.12
MAX_SHARED_KEYWORDS_SHOWN = 12

_ASCII_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}")
_CJK_RUN_RE = re.compile(r"[一-鿿]{2,}")
# Negative-trigger redirect 子句（「請改用 /X」「退回 /X」）宣告的是「不要用本 skill、
# 改用兄弟 skill」——它是 over-trigger 的『解法』，不是本 skill 的觸發詞。若把被導向的
# 兄弟 skill 名（codex-review、pr-cycle-deep…）算進關鍵字，兩個互相 redirect 的 skill
# 會因為彼此的名字成為共享 token 而 Jaccard 虛高，等於懲罰 rule 11 指定的正確修法
# （作者被逼去刪 redirect 子句來讓 lint 過關）。故 tokenize 前先剝除從 redirect 標記到
# 子句結尾（。；或換行）的整段文字。標記前的條件描述（「小型 PR 或快速 lifecycle」）保留，
# 因為那是在描述『本 skill 的邊界』，屬於合法內容。
_REDIRECT_CLAUSE_RE = re.compile(r"(?:請改用|改用|請退回|退回|請用)[^。；\n]*")
# YAML block scalar header: `|`/`>` plus optional chomping (`+`/`-`) and indentation (1-9)
# indicators in either order (e.g. `|2`, `>1-`, `|-2`), not just the bare/chomping-only forms.
_BLOCK_SCALAR_RE = re.compile(r"^[|>][+\-1-9]*$")

# 常見「樣板虛詞」bigram：幾乎每份 SKILL.md description 都會出現，不濾會讓所有 pair
# 都顯得重疊、訊號消失。清單刻意保守（只濾語法性虛詞/描述觸發機制本身的用語），
# 不濾領域詞彙（如「審查」「重複」等）。
#
# 注意：_CJK_RUN_RE 只吃 CJK Unified Ideographs，全形標點（如「」）會截斷連續字元，
# 所以任何「跨標點」的 bigram（如 說「、」時）永遠不會被 extract_keywords 產生——
# 加進這份清單也是死條目，不要加。
_CJK_STOPWORDS = frozenset(
    {
        "觸發",
        "情境",
        "關鍵",
        "鍵字",
        "使用",
        "可以",
        "需要",
        "進行",
        "應該",
        "時候",
        "適用",
        "情況",
        "或是",
        "以及",
        "不要",
        "而是",
        "這個",
        "那個",
        "什麼",
        "怎麼",
        "如何",
        "是否",
        "已經",
        "目前",
        "的是",
        "也應",
        "也是",
        "才能",
        "只要",
        "只是",
        "但是",
        "因為",
        "所以",
        "如果",
        "當你",
        "當用",
        "用戶",
        "用者",
        "者說",
    }
)


def _collect_indented_continuation(lines: list[str], start: int) -> list[str]:
    """從 start 開始收集後續縮排行（略過空行），遇到未縮排行則停止。"""
    collected: list[str] = []
    for follow in lines[start:]:
        if follow.strip() == "":
            continue
        if follow.startswith((" ", "\t")):
            collected.append(follow.strip())
        else:
            break
    return collected


def parse_description(text: str) -> str | None:
    """取 SKILL.md frontmatter 的 description 值；支援單行、`>`/`|` block scalar，
    以及 plain scalar 的多行 folding（YAML 語意：後續縮排行會摺進同一個值）。

    frontmatter 缺結尾 `---`（格式錯誤）視為解析失敗，回傳 None——不 fallback 到整份
    文件內容，避免 body 裡剛好有一行 `description:` 開頭的文字被誤判為 frontmatter 值。
    """
    body = text.lstrip()
    if not body.startswith("---"):
        return None
    end = body.find("\n---", 3)
    if end == -1:
        return None
    front = body[:end]
    lines = front.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^description:\s*(.*)$", line)
        if not m:
            continue
        rest = m.group(1).strip()
        if _BLOCK_SCALAR_RE.match(rest):
            collected = _collect_indented_continuation(lines, i + 1)
            return " ".join(collected) or None
        # plain（無引號）scalar：YAML 會把後續縮排的延續行摺進同一個值，
        # 例如 `description: foo\n  bar` 語意上是 "foo bar"，不是只有 "foo"。
        collected = ([rest] if rest else []) + _collect_indented_continuation(lines, i + 1)
        return " ".join(collected) or None
    return None


def extract_keywords(description: str) -> set[str]:
    """從 description 抽觸發關鍵字 set：ASCII word token + CJK bigram shingle。

    先剝除 negative-trigger redirect 子句（見 `_REDIRECT_CLAUSE_RE`）——被導向的兄弟
    skill 名是『解法』不是觸發詞，計入會讓互相 redirect 的 pair 虛高。
    """
    description = _REDIRECT_CLAUSE_RE.sub(" ", description)
    keywords: set[str] = set()
    for m in _ASCII_WORD_RE.finditer(description):
        keywords.add(m.group(0).lower())
    for run in _CJK_RUN_RE.finditer(description):
        text = run.group(0)
        for i in range(len(text) - 1):
            bigram = text[i : i + 2]
            if bigram not in _CJK_STOPWORDS:
                keywords.add(bigram)
    return keywords


def jaccard(a: set[str], b: set[str]) -> float:
    """交集 / 聯集；任一邊為空回傳 0（避免除以零）。"""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def iter_global_skill_files(skills_dir: Path, plugins_dir: Path) -> list[tuple[str, Path]]:
    """列出 skills/*/SKILL.md（follow symlink dir）與 plugins/<plugin>/skills/ 底下任意深度
    的 SKILL.md（含巢狀 sub-skill，如 plugins/growth/skills/mycelium/recap/SKILL.md），
    依 realpath 去重——symlink 到 plugin 的 skill 只算一次，避免與其 plugin 真實路徑
    重複計分。回傳的第一個元素永遠是各 skill 自己的目錄名稱。

    plugins 端用 `**`（遞迴、可跨任意層 `/`）而非 `*`（只吃一層）：pathlib glob 的 `*`
    不像 regex 的 `.*` 會跨越路徑分隔符，只用 `*` 會漏掉巢狀 sub-skill。
    """
    found: list[tuple[str, Path]] = []
    seen_real: set[Path] = set()

    for entry in sorted(skills_dir.iterdir()):
        if entry.is_symlink() and not entry.exists():
            print(
                f"[WARN] skills/{entry.name} 是失效的 symlink（目標不存在），已排除",
                file=sys.stderr,
            )
            continue
        if not entry.is_dir():  # is_dir() follows symlink-to-dir
            continue
        skill_md = entry / "SKILL.md"
        if skill_md.is_file():
            found.append((entry.name, skill_md))
            seen_real.add(skill_md.resolve())

    if plugins_dir.is_dir():
        for skill_md in sorted(plugins_dir.glob("*/skills/**/SKILL.md")):
            real = skill_md.resolve()
            if real in seen_real:
                continue  # 已透過 skills/ symlink，或另一條 plugins/ glob 路徑掃過同一份實體檔案
            found.append((skill_md.parent.name, skill_md))
            seen_real.add(real)

    return found


def find_overlaps(
    skills: list[tuple[str, set[str]]], threshold: float
) -> list[tuple[str, str, float, list[str]]]:
    """兩兩算 Jaccard；回傳達到門檻的 (name_a, name_b, score, shared_keywords) 依 score 降冪。"""
    risky: list[tuple[str, str, float, list[str]]] = []
    for (name_a, kw_a), (name_b, kw_b) in combinations(skills, 2):
        score = jaccard(kw_a, kw_b)
        if score >= threshold:
            shared = sorted(kw_a & kw_b, key=lambda k: (-len(k), k))[:MAX_SHARED_KEYWORDS_SHOWN]
            risky.append((name_a, name_b, score, shared))
    risky.sort(key=lambda row: row[2], reverse=True)
    return risky


def main() -> int:
    fail_mode = "--fail" in sys.argv
    threshold = DEFAULT_THRESHOLD
    for i, arg in enumerate(sys.argv):
        if arg != "--threshold":
            continue
        if i + 1 >= len(sys.argv):
            print("[FAIL] --threshold 需要帶一個數值參數", file=sys.stderr)
            return 2
        try:
            threshold = float(sys.argv[i + 1])
        except ValueError:
            print(f"[FAIL] --threshold 的值不是合法數字：{sys.argv[i + 1]}", file=sys.stderr)
            return 2
        if not 0.0 <= threshold <= 1.0:
            print(f"[FAIL] --threshold 必須介於 0 與 1 之間，收到：{threshold}", file=sys.stderr)
            return 2

    if not SKILLS_DIR.is_dir():
        print(f"[FAIL] 找不到 skills 目錄：{SKILLS_DIR}", file=sys.stderr)
        return 2

    skills: list[tuple[str, set[str]]] = []
    checked = 0
    for skill_name, skill_md in iter_global_skill_files(SKILLS_DIR, PLUGINS_DIR):
        try:
            rel_path = skill_md.relative_to(REPO_ROOT)
        except ValueError:
            rel_path = skill_md  # SKILLS_DIR/PLUGINS_DIR 被覆寫成非 REPO_ROOT 底下的路徑時
        try:
            text = skill_md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"[WARN] 無法讀取 {rel_path}：{e}", file=sys.stderr)
            continue
        description = parse_description(text)
        if description is None:
            print(f"[WARN] {rel_path} 找不到 description 欄位", file=sys.stderr)
            continue
        checked += 1
        skills.append((skill_name, extract_keywords(description)))

    risky = find_overlaps(skills, threshold)

    if risky:
        print(
            f"[WARN] 偵測到 {len(risky)} 對觸發詞高度重疊的 skill（Jaccard >= {threshold}）：",
            file=sys.stderr,
        )
        for name_a, name_b, score, shared in risky:
            print(f"  {name_a} <-> {name_b}: {score:.2f}", file=sys.stderr)
            print(f"    共享: {'、'.join(shared)}", file=sys.stderr)
        print(
            "\n若重疊為刻意設計（如 PR lifecycle 家族的互斥導引），確認 description 已有"
            "明確的 negative-trigger 文字（「請改用 X」）；否則考慮收斂觸發詞或合併 skill。"
            "詳見 .claude/rules/11-skill-authoring.md「Trigger Coverage」一節。",
            file=sys.stderr,
        )
        if fail_mode:
            return 1
        print("提示：用 --fail 旗標可讓此 script 在有重疊達到門檻時 exit 1", file=sys.stderr)
        return 0

    print(f"[OK] 已檢查 {checked} 個 skill，無觸發詞重疊達到門檻（Jaccard >= {threshold}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

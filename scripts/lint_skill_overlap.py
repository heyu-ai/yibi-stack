#!/usr/bin/env python3
"""Lint：偵測 SKILL.md description 觸發詞高度重疊的 skill pair（over-trigger 風險）。

背景——yibi-stack 沒有 per-skill 觸發準確度 eval，只能靠作者人工在 description 裡寫
「請改用 X」互斥文字硬擋 over-trigger（見 rule 11「Trigger Coverage」一節）。
本 lint 是確定性靜態偵測器：抽取每個 skill description 的觸發關鍵字，兩兩算重疊分數，
超門檻的 pair 印出來讓作者人工複查是否需要補 negative-trigger 文字或收斂觸發詞。

**MVP 範圍**：只掃 repo-root `skills/*/SKILL.md`（本 repo 全域可用的 skill；plugin-only、
未 symlink 到 `skills/` 的 project-scope skill 不在此 MVP 掃描範圍內，理由見
issue #186 B1——先驗證偵測邏輯本身，plugin-wide 掃描留給後續視需要擴充）。

**演算法**（無 CJK 斷詞依賴，純 regex）：
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

DEFAULT_THRESHOLD = 0.12
MAX_SHARED_KEYWORDS_SHOWN = 12

_ASCII_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}")
_CJK_RUN_RE = re.compile(r"[一-鿿]{2,}")
# YAML block scalar header: `|`/`>` plus optional chomping (`+`/`-`) and indentation (1-9)
# indicators in either order (e.g. `|2`, `>1-`, `|-2`), not just the bare/chomping-only forms.
_BLOCK_SCALAR_RE = re.compile(r"^[|>][+\-1-9]*$")

# 常見「樣板虛詞」bigram：幾乎每份 SKILL.md description 都會出現，不濾會讓所有 pair
# 都顯得重疊、訊號消失。清單刻意保守（只濾語法性虛詞/描述觸發機制本身的用語），
# 不濾領域詞彙（如「審查」「重複」等）。
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
        "說「",
        "」時",
    }
)


def parse_description(text: str) -> str | None:
    """取 SKILL.md frontmatter 的 description 值；支援單行與 `>`/`|` block scalar。

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
            collected = []
            for follow in lines[i + 1 :]:
                if follow.strip() == "":
                    continue
                if follow.startswith((" ", "\t")):
                    collected.append(follow.strip())
                else:
                    break
            return " ".join(collected) or None
        return rest or None
    return None


def extract_keywords(description: str) -> set[str]:
    """從 description 抽觸發關鍵字 set：ASCII word token + CJK bigram shingle。"""
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


def iter_global_skill_files(skills_dir: Path) -> list[tuple[str, Path]]:
    """列出 repo-root skills/*/SKILL.md（follow symlink dir）。"""
    found: list[tuple[str, Path]] = []
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
    for skill_name, skill_md in iter_global_skill_files(SKILLS_DIR):
        try:
            text = skill_md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"[WARN] 無法讀取 skills/{skill_name}/SKILL.md：{e}", file=sys.stderr)
            continue
        description = parse_description(text)
        if description is None:
            print(f"[WARN] skills/{skill_name}/SKILL.md 找不到 description 欄位", file=sys.stderr)
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

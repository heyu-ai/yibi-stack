"""D10 scanner：Codebase Navigation（機械分 3/5）。

Anthropic best practices：
- Build codebase maps：輕量 markdown 描述目錄結構，幫助 agent 在大 repo 中導航。
- Reference specific files：CLAUDE.md 用 @-mentions 指向重要檔案。
"""

import re
from pathlib import Path

from ..models import MechanicalFinding

_MECH_MAX = 3
# 常見的 codebase map 檔名候選
_MAP_CANDIDATES = (
    "ARCHITECTURE.md",
    "REPO_MAP.md",
    "STRUCTURE.md",
    "CODEBASE.md",
    "docs/ARCHITECTURE.md",
    "docs/architecture.md",
    "docs/REPO_MAP.md",
    "docs/structure.md",
)
# @-mention pattern：@<path>，但要排除 email、@user 等
_AT_MENTION_RE = re.compile(r"(?:^|\s)@([./\w\-]+/[\w\-./]+|[\w\-]+\.\w+)")
# tree-drawing 字元，代表 CLAUDE.md 內含目錄結構描述
_TREE_CHARS = ("├──", "└──", "│   ", "├─", "└─")
# 替代 heuristic：多行 "dirname/ → 說明" 或 "dirname/ - 說明" 格式
_DIR_LISTING_RE = re.compile(r"^\s*[\w.\-]+/\s+[→\->]", re.MULTILINE)
_DIR_LISTING_MIN = 3


def _find_codebase_map(target_dir: Path) -> Path | None:
    for rel in _MAP_CANDIDATES:
        p = target_dir / rel
        if p.is_file():
            return p
    return None


def _has_at_mentions(content: str) -> int:
    """回傳 CLAUDE.md 中 @-mention 數量。"""
    matches = _AT_MENTION_RE.findall(content)
    # 過濾常見假陽性（如 email）
    filtered = [m for m in matches if "@" not in m and not m.startswith("http")]
    return len(filtered)


def _has_tree_structure(content: str) -> bool:
    """偵測 CLAUDE.md 是否含目錄結構說明。

    兩種命中方式：
    1. tree-drawing 字元（├── / └──）
    2. ≥3 行 "dirname/ → 說明" 風格的條列
    """
    if any(ch in content for ch in _TREE_CHARS):
        return True
    return len(_DIR_LISTING_RE.findall(content)) >= _DIR_LISTING_MIN


def scan_navigation(target_dir: Path) -> MechanicalFinding:
    """掃描 codebase map、@-mentions、目錄結構描述。語意分由 agent 補充。"""
    findings: list[str] = []
    semantic_targets: list[str] = []
    score = 0

    # 1. Codebase map（1 分）
    map_path = _find_codebase_map(target_dir)
    if map_path is not None:
        score += 1
        findings.append(f"codebase map 存在：{map_path.relative_to(target_dir)}")
        semantic_targets.append(str(map_path))
    else:
        findings.append(
            f"WARN: 無 codebase map（建議建立 ARCHITECTURE.md 描述目錄結構，"
            f"已查詢：{', '.join(_MAP_CANDIDATES[:4])}）"
        )

    # 2 + 3：CLAUDE.md 內的導航訊號
    project_md = target_dir / "CLAUDE.md"
    if project_md.is_file():
        try:
            content = project_md.read_text(encoding="utf-8")
        except OSError as e:
            findings.append(f"WARN: CLAUDE.md 無法讀取：{e}")
            content = ""

        # @-mentions（1 分）
        mention_count = _has_at_mentions(content)
        if mention_count >= 1:
            score += 1
            findings.append(
                f"CLAUDE.md 含 {mention_count} 個 @-mention（reference specific files）"
            )
        else:
            findings.append(
                "WARN: CLAUDE.md 未使用 @-mention 引用具體檔案"
                "（Anthropic 建議用 @<path> 指引 agent）"
            )

        # 目錄樹（1 分）
        if _has_tree_structure(content):
            score += 1
            findings.append("CLAUDE.md 含目錄樹/結構圖（layered file structure）")
        else:
            findings.append("WARN: CLAUDE.md 無目錄結構描述（建議加入 root 層的 directory map）")
    else:
        findings.append("WARN: CLAUDE.md 不存在，無法評估 @-mention / 結構描述")

    return MechanicalFinding(
        dimension="D10",
        label="Codebase Navigation",
        score=min(score, _MECH_MAX),
        max_score=_MECH_MAX,
        findings=findings,
        semantic_targets=semantic_targets,
    )

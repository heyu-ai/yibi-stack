"""D7 scanner：Rules 文件 & 路徑作用域（機械分 7/15）。"""

import re
from pathlib import Path

from ..models import MechanicalFinding

_MECH_MAX = 7
_NUMBER_RE = re.compile(r"^\d{2}-")

# rule 維護循環（prune / lesson 路由）在 rule 內容中的佐證 marker。
# prune 機制由**全域安裝的 plugin**（claude-md-prune）與週結流程（harness-queue /
# harness-batch）驅動；全域 plugin 不在 target repo 的任何目錄下，任何目錄掃描都看不到，
# 故以 rule 內容 marker 佐證。（vendored 進 repo 的 `plugins/*/skills/*prune*` 目錄則由
# `_has_prune_skill_dir` 另行偵測，兩者為 OR 疊加。）
# 只用**具體識別符**——泛用字（bare "prune" / "lesson routing"）會被偶然提及（`git remote
# prune`、討論 pruning 的散文）誤中而虛報維護循環存在，故不列入。
_PRUNE_CONTENT_MARKERS = (
    "harness-queue",
    "harness-batch",
    "claude-md-prune",
)


def _has_glob_frontmatter(md_file: Path) -> bool:
    try:
        content = md_file.read_text(encoding="utf-8")
    except OSError:
        return False
    if not content.startswith("---"):
        return False
    parts = content.split("---", 2)
    return len(parts) >= 3 and "glob:" in parts[1]


def _rule_content_has_prune_marker(rule_files: list[Path]) -> bool:
    """任一 rule 檔內容含維護循環 marker → 認定 prune / lesson 路由機制存在。"""
    for f in rule_files:
        try:
            content = f.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        if any(marker in content for marker in _PRUNE_CONTENT_MARKERS):
            return True
    return False


def _has_prune_skill_dir(target_dir: Path) -> bool:
    """任一 skill 根目錄下存在名稱含 prune 的 skill dir → prune 機制存在。

    掃 .claude/skills/、skills/、plugins/*/skills/，涵蓋 plugin 化與 symlink 掛載的 skill。
    """
    skill_roots = [
        target_dir / ".claude" / "skills",
        target_dir / "skills",
    ]
    plugins_dir = target_dir / "plugins"
    if plugins_dir.is_dir():
        try:
            plugin_entries = list(plugins_dir.iterdir())
        except OSError:
            plugin_entries = []
        for plugin in plugin_entries:
            if plugin.is_dir():
                skill_roots.append(plugin / "skills")
    for root in skill_roots:
        if not root.is_dir():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            # 不可讀的目錄（權限不足等）：略過，與 _rule_content_has_prune_marker 的容錯一致，
            # 不讓單一目錄讓整個 scan_rules 崩潰。
            continue
        for d in entries:
            if d.is_dir() and "prune" in d.name.lower():
                return True
    return False


def scan_rules(target_dir: Path) -> MechanicalFinding:
    """掃描 .claude/rules/ 結構品質。語意分（8 分）由 agent 補充。"""
    findings: list[str] = []
    semantic_targets: list[str] = []
    score = 0

    rules_dir = target_dir / ".claude" / "rules"
    rule_files = list(rules_dir.glob("*.md")) if rules_dir.exists() else []

    if not rule_files:
        findings.append("WARN: .claude/rules/ 不存在或無 .md 規則檔")
        return MechanicalFinding(
            dimension="D7",
            label="Rules 文件 & 路徑作用域",
            score=0,
            max_score=_MECH_MAX,
            findings=findings,
        )

    score = min(score + 2, _MECH_MAX)
    findings.append(f".claude/rules/ 存在，共 {len(rule_files)} 個規則檔")
    for f in rule_files[:5]:
        semantic_targets.append(str(f))

    numbered = [f for f in rule_files if _NUMBER_RE.match(f.name)]
    if numbered:
        score = min(score + 2, _MECH_MAX)
        findings.append(f"規則有編號分類（{len(numbered)}/{len(rule_files)} 個有 NN- 前綴）")
    else:
        findings.append("WARN: 規則未使用編號前綴（建議 01-*.md 格式）")

    has_glob = any(_has_glob_frontmatter(f) for f in rule_files)
    if has_glob:
        score = min(score + 3, _MECH_MAX)
        findings.append("規則含 glob frontmatter（path-scoped auto-load）")
    elif len(rule_files) >= 3:
        score = min(score + 2, _MECH_MAX)
        findings.append("規則使用 topic 命名分類（yibi-stack 編號 + 交叉引用模式）")

    # prune / lesson 路由機制：rule 內容 marker 佐證，或 skill 目錄佐證（任一即可）
    if _rule_content_has_prune_marker(rule_files):
        score = min(score + 2, _MECH_MAX)
        findings.append("規則維護循環存在（rule 內容引用維護佇列 / lesson 路由 marker）")
    elif _has_prune_skill_dir(target_dir):
        score = min(score + 2, _MECH_MAX)
        findings.append("規則維護循環存在（prune skill）")
    else:
        findings.append("WARN: 未找到 rule prune 機制")

    return MechanicalFinding(
        dimension="D7",
        label="Rules 文件 & 路徑作用域",
        score=score,
        max_score=_MECH_MAX,
        findings=findings,
        semantic_targets=semantic_targets,
    )

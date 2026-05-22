"""D4 scanner：Skills & Commands（機械分 8/12）。

新增（Anthropic best practices for large codebases）：
- plugins/ 分發單位偵測（plugins as installable bundles for org-wide rollout）
- SKILL.md frontmatter 是否含 `allowed-tools` 或 path-scoping 標記（progressive disclosure）
"""

import os
from collections.abc import Iterator
from pathlib import Path

from ..models import MechanicalFinding

_MECH_MAX = 8
_REQUIRED_KEYS = {"name", "type", "scope", "description"}
# 進階 scoping 欄位：有任一存在即視為「skill 有 path/tool scoping」
_SCOPING_KEYS = ("allowed-tools", "allowed_tools", "glob", "files", "paths")

# skills 可能的位置：.claude/skills/（symlink 安裝目標）或 skills/（source repo）
_SKILL_DIRS = [".claude/skills", "skills"]
# plugins 可能的位置：plugins/（marketplace repo）或 .claude/plugins/（消費者安裝）
_PLUGIN_DIRS = ["plugins", ".claude/plugins"]


def _has_valid_frontmatter(skill_md: Path) -> bool:
    try:
        # 逐行讀到第二個 "---" 結尾，避免截斷長 description
        lines: list[str] = []
        dash_count = 0
        with skill_md.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                lines.append(line)
                if line.strip() == "---":
                    dash_count += 1
                    if dash_count == 2:
                        break
    except OSError:
        return False

    if dash_count < 2:
        return False
    head = "".join(lines)
    parts = head.split("---", 2)
    if len(parts) < 3:
        return False
    return all(f"{key}:" in parts[1] for key in _REQUIRED_KEYS)


def _has_scoping_marker(skill_md: Path) -> bool:
    """判斷 frontmatter 是否含 path/tool scoping 欄位（progressive disclosure 訊號）。"""
    try:
        lines: list[str] = []
        dash_count = 0
        with skill_md.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                lines.append(line)
                if line.strip() == "---":
                    dash_count += 1
                    if dash_count == 2:
                        break
    except OSError:
        return False
    if dash_count < 2:
        return False
    parts = "".join(lines).split("---", 2)
    if len(parts) < 3:
        return False
    fm = parts[1]
    return any(f"{key}:" in fm for key in _SCOPING_KEYS)


def _iter_skill_mds(skills_dir: Path) -> Iterator[Path]:
    """遍歷 skills_dir 下所有 SKILL.md，跟隨 symlink 進入子目錄。"""
    for root, dirs, files in os.walk(skills_dir, followlinks=True):
        root_path = Path(root)
        rel_parts = root_path.relative_to(skills_dir).parts
        if any(part.startswith(".") for part in rel_parts):
            dirs.clear()
            continue
        if "SKILL.md" in files:
            yield root_path / "SKILL.md"


def _find_skill_mds(target_dir: Path) -> tuple[list[Path], str]:
    """在多個可能位置搜尋 SKILL.md，回傳（檔案清單, 來源描述）。"""
    for rel_dir in _SKILL_DIRS:
        skills_dir = target_dir / rel_dir
        if not skills_dir.exists():
            continue
        skill_mds = list(_iter_skill_mds(skills_dir))
        if skill_mds:
            return skill_mds, rel_dir
    return [], ""


def _find_plugin_packs(target_dir: Path) -> list[Path]:
    """搜尋 plugins/ 或 .claude/plugins/ 下含 package.json 的 plugin 子目錄。

    Anthropic 強調 plugins 是「分發單位」：bundle skills/hooks/MCP 給組織。
    判斷依據：子目錄含 package.json（Claude Code plugin manifest）。
    """
    for rel_dir in _PLUGIN_DIRS:
        plugins_dir = target_dir / rel_dir
        if not plugins_dir.is_dir():
            continue
        packs: list[Path] = []
        for child in plugins_dir.iterdir():
            if child.is_dir() and (child / "package.json").is_file():
                packs.append(child)
        if packs:
            return packs
    return []


def scan_skills(target_dir: Path) -> MechanicalFinding:
    """掃描 skills 目錄、commands、plugins、scoping markers。語意分由 agent 補充。"""
    findings: list[str] = []
    semantic_targets: list[str] = []
    score = 0

    skill_mds, source_dir = _find_skill_mds(target_dir)

    if not skill_mds:
        dirs_checked = ", ".join(_SKILL_DIRS)
        findings.append(f"WARN: 找不到 SKILL.md（已查詢：{dirs_checked}）")
    else:
        score += 2
        findings.append(f"skills/ 存在於 {source_dir}，共 {len(skill_mds)} 個 skill")
        if source_dir == "skills":
            findings.append("（源碼 repo 模式：技能從 skills/ 掃描）")

        valid = sum(1 for s in skill_mds if _has_valid_frontmatter(s))
        if valid == len(skill_mds):
            score += 2
            findings.append(
                f"所有 {valid} 個 skill frontmatter 完整（name/type/scope/description）"
            )
        elif valid > 0:
            score += 1
            findings.append(f"WARN: {valid}/{len(skill_mds)} skill frontmatter 完整")
        else:
            findings.append("WARN: 所有 skill 缺少完整 frontmatter")

        # scoping marker（progressive disclosure 訊號）
        scoped = sum(1 for s in skill_mds if _has_scoping_marker(s))
        if scoped > 0:
            score += 1
            findings.append(
                f"path/tool scoping：{scoped}/{len(skill_mds)} 個 skill 含 "
                f"allowed-tools/glob/files 欄位（progressive disclosure）"
            )
        else:
            findings.append(
                "WARN: 無 skill 含 allowed-tools/glob 等 scoping 欄位"
                "（Anthropic 建議將 skill 綁定到特定路徑/工具，避免 context bloat）"
            )

        for s in skill_mds[:3]:
            semantic_targets.append(str(s))

    # commands/ 目錄（slash command 快捷鍵）
    commands_dir = target_dir / ".claude" / "commands"
    if commands_dir.exists():
        cmds = list(commands_dir.glob("*.md"))
        if cmds:
            score += 2
            findings.append(f".claude/commands/ 存在（{len(cmds)} 個 slash command）")
        else:
            findings.append("WARN: .claude/commands/ 存在但無任何 slash command .md")
    else:
        findings.append("WARN: .claude/commands/ 不存在（slash command 未設定）")

    # plugins/ 分發單位（Anthropic: bundle/distribute skills+hooks+MCP）
    plugin_packs = _find_plugin_packs(target_dir)
    if plugin_packs:
        score += 1
        findings.append(f"plugin packs：{len(plugin_packs)} 個（含 package.json，可作分發單位）")
    else:
        findings.append(
            "WARN: 無 plugin packs（plugins/ 或 .claude/plugins/ 下無 package.json 子目錄）"
        )

    return MechanicalFinding(
        dimension="D4",
        label="Skills & Commands",
        score=min(score, _MECH_MAX),
        max_score=_MECH_MAX,
        findings=findings,
        semantic_targets=semantic_targets,
    )

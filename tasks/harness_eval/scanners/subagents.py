"""D9 scanner：Subagents 配置（機械分 4/6）。

Anthropic best practices：split exploration from editing。
- 隔離 subagent 做 read-only 探索，回傳發現給 parent agent。
- 平行工作分工：exploration vs editing 兩階段。

掃描：.claude/agents/*.md（Claude Code subagent definitions）。
"""

from pathlib import Path

from ..models import MechanicalFinding

_MECH_MAX = 4
# read-only tools：subagent 若僅含這些 tool，視為「exploration-only」設計
_READ_ONLY_TOOLS = {"Read", "Grep", "Glob", "WebFetch", "WebSearch", "Bash"}
# 若 tools 含這些 → 不是純 read-only
_WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}


def _parse_frontmatter(agent_md: Path) -> dict[str, str]:
    """解析 agent .md 的 frontmatter，回傳 key→raw_value 字典（不展開 list）。"""
    try:
        lines: list[str] = []
        dash_count = 0
        with agent_md.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                lines.append(line)
                if line.strip() == "---":
                    dash_count += 1
                    if dash_count == 2:
                        break
    except OSError:
        return {}
    if dash_count < 2:
        return {}
    parts = "".join(lines).split("---", 2)
    if len(parts) < 3:
        return {}
    result: dict[str, str] = {}
    for raw in parts[1].splitlines():
        if ":" in raw and not raw.strip().startswith("#"):
            key, _, value = raw.partition(":")
            result[key.strip()] = value.strip()
    return result


def _is_read_only(tools_value: str) -> bool:
    """從 frontmatter `tools:` raw 值判斷是否為純 read-only subagent。"""
    if not tools_value:
        return False
    # tools 可能是 "Read, Grep, Glob" 或 yaml list "[Read, Grep]"
    cleaned = tools_value.strip("[]")
    tokens = {t.strip() for t in cleaned.split(",") if t.strip()}
    if not tokens:
        return False
    # 含任何 write tool → 不是 read-only
    if tokens & _WRITE_TOOLS:
        return False
    # 至少含一個 read-only tool
    return bool(tokens & _READ_ONLY_TOOLS)


def scan_subagents(target_dir: Path) -> MechanicalFinding:
    """掃描 .claude/agents/ 下的 subagent 定義。語意分由 agent 補充。"""
    findings: list[str] = []
    semantic_targets: list[str] = []
    score = 0

    agents_dir = target_dir / ".claude" / "agents"
    if not agents_dir.is_dir():
        findings.append(
            "WARN: .claude/agents/ 不存在（建議建立 read-only exploration subagent，"
            "把探索/搜尋與編輯切開，保護 parent agent 的 context）"
        )
        return MechanicalFinding(
            dimension="D9",
            label="Subagents（探索/編輯隔離）",
            score=0,
            max_score=_MECH_MAX,
            findings=findings,
        )

    agent_files = list(agents_dir.glob("*.md"))
    if not agent_files:
        findings.append("WARN: .claude/agents/ 存在但無任何 .md 定義")
        return MechanicalFinding(
            dimension="D9",
            label="Subagents（探索/編輯隔離）",
            score=0,
            max_score=_MECH_MAX,
            findings=findings,
        )

    score += 2
    findings.append(f".claude/agents/ 存在（{len(agent_files)} 個 subagent 定義）")

    # tools 欄位 scoping 偵測（1 分）
    has_tools_scoping = 0
    read_only_count = 0
    for af in agent_files:
        fm = _parse_frontmatter(af)
        tools_raw = fm.get("tools", "")
        if tools_raw:
            has_tools_scoping += 1
            if _is_read_only(tools_raw):
                read_only_count += 1

    if has_tools_scoping:
        score += 1
        findings.append(
            f"tools scoping：{has_tools_scoping}/{len(agent_files)} 個 subagent 限制了工具集"
        )
    else:
        findings.append(
            "WARN: 無 subagent 設定 tools scoping（agent 可用全部工具，無 read-only 隔離）"
        )

    # read-only exploration subagent（1 分；Anthropic 明確主張）
    if read_only_count:
        score += 1
        findings.append(
            f"read-only exploration subagent：{read_only_count} 個"
            "（split exploration from editing）"
        )
    else:
        findings.append(
            "WARN: 無 read-only exploration subagent"
            "（建議至少建立 1 個僅含 Read/Grep/Glob 的 subagent）"
        )

    for af in agent_files[:3]:
        semantic_targets.append(str(af))

    return MechanicalFinding(
        dimension="D9",
        label="Subagents（探索/編輯隔離）",
        score=min(score, _MECH_MAX),
        max_score=_MECH_MAX,
        findings=findings,
        semantic_targets=semantic_targets,
    )

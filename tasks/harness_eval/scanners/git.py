"""D6 scanner：Git 工作流程 & Commit 品質（機械分 6/10）。"""

import subprocess  # nosec B404
from pathlib import Path

from ..models import MechanicalFinding

_MECH_MAX = 6


def _is_git_repo(target_dir: Path) -> bool:
    result = subprocess.run(  # nosec B603 B607
        ["git", "-C", str(target_dir), "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode == 0


def _get_recent_commits(target_dir: Path, n: int = 20) -> list[str]:
    result = subprocess.run(  # nosec B603 B607
        ["git", "-C", str(target_dir), "log", f"--max-count={n}", "--pretty=format:%s"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def scan_git(target_dir: Path) -> MechanicalFinding:
    """掃描 worktree 設定、branch 保護 hook。語意分（4 分）由 agent 補充。"""
    findings: list[str] = []
    semantic_targets: list[str] = []
    score = 0

    if not _is_git_repo(target_dir):
        findings.append("WARN: 非 git repo，跳過 D6 掃描")
        return MechanicalFinding(
            dimension="D6",
            label="Git 工作流程 & Commit",
            score=0,
            max_score=_MECH_MAX,
            findings=findings,
        )

    worktrees_dir = target_dir / ".claude" / "worktrees"
    if worktrees_dir.exists():
        score += 3
        findings.append(".claude/worktrees/ 存在（worktree 隔離已設定）")
    else:
        findings.append("WARN: .claude/worktrees/ 不存在")

    hooks_dir = target_dir / ".claude" / "hooks"
    has_protect = hooks_dir.exists() and any(
        "protect" in f.name.lower() for f in hooks_dir.iterdir() if f.is_file()
    )
    if has_protect:
        score += 3
        findings.append("branch 保護 hook 存在（.claude/hooks/ 含 protect-*.sh）")
    else:
        findings.append("WARN: 未找到 branch 保護 hook")

    commits = _get_recent_commits(target_dir)
    if commits:
        semantic_targets.append(f"__git_log__{target_dir}")
        findings.append(f"git log 取得最近 {len(commits)} 筆（供 agent 評估風格）")

    return MechanicalFinding(
        dimension="D6",
        label="Git 工作流程 & Commit",
        score=score,
        max_score=_MECH_MAX,
        findings=findings,
        semantic_targets=semantic_targets,
    )

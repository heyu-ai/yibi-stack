"""D1 scanner：CLAUDE.md 品質（機械分 8/14）。

新增（Anthropic best practices for large codebases）：
- subdirectory CLAUDE.md cascade 偵測（分層 / per-subdir 慣例）
- staleness 檢查（mtime > 180 天或內容含過時 model 名稱）
"""

import os
import time
from pathlib import Path

from ..models import MechanicalFinding

_MECH_MAX = 8
_STALE_DAYS = 180
# 過時 model 名稱：CLAUDE.md 若指名舊版 model 通常代表規則未隨升版更新
_STALE_MODEL_PATTERNS = (
    "claude-2",
    "claude-3-",
    "claude-3.5",
    "sonnet-3.5",
    "opus-3",
    "haiku-3",
)
_SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "dist",
    "build",
    ".claude",
    ".runtime",
    "output",
}
_MAX_SCAN_DEPTH = 4


def _find_subdir_claude_mds(target_dir: Path) -> list[Path]:
    """搜尋 target_dir 下的 sub-package CLAUDE.md（排除 root 本身）。

    Anthropic 建議分層：root 描述大圖、subdir 描述局部慣例。
    使用 os.walk(followlinks=True) 處理 symlink；限制深度避免效能問題。
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(target_dir, followlinks=True):
        rel = Path(dirpath).relative_to(target_dir)
        depth = len(rel.parts)
        if depth >= _MAX_SCAN_DEPTH:
            dirnames.clear()
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        # 排除 root 自己（depth=0）
        if depth > 0 and "CLAUDE.md" in filenames:
            found.append(Path(dirpath) / "CLAUDE.md")
    return found


def _check_staleness(project_md: Path) -> tuple[int, list[str]]:
    """判斷 CLAUDE.md 是否過時。

    回傳 (score, findings)：score=1 表示 fresh + 無過時 model 名；否則 0。
    """
    findings: list[str] = []
    fresh = True
    try:
        mtime = project_md.stat().st_mtime
    except OSError as e:
        return 0, [f"WARN: 無法取得 mtime：{e}"]
    age_days = (time.time() - mtime) / 86400
    if age_days > _STALE_DAYS:
        fresh = False
        findings.append(
            f"WARN: CLAUDE.md {int(age_days)} 天未更新（Anthropic 建議 3-6 個月 review）"
        )
    try:
        content_lower = project_md.read_text(encoding="utf-8").lower()
    except OSError:
        content_lower = ""
    stale_hits = [p for p in _STALE_MODEL_PATTERNS if p in content_lower]
    if stale_hits:
        fresh = False
        findings.append(
            f"WARN: CLAUDE.md 含過時 model 名稱 {stale_hits[:3]}（可能限制新版 model 推理）"
        )
    if fresh:
        findings.append(f"CLAUDE.md 新鮮度 OK（{int(age_days)} 天內更新、無過時 model 引用）")
        return 1, findings
    return 0, findings


def scan_claude_md(target_dir: Path) -> MechanicalFinding:
    """掃描 target_dir 下的 CLAUDE.md 存在性、行數、分層、新鮮度。語意分由 agent 補充。"""
    findings: list[str] = []
    semantic_targets: list[str] = []
    score = 0

    project_md = target_dir / "CLAUDE.md"

    if project_md.exists():
        score += 3
        findings.append(f"CLAUDE.md 存在：{project_md}")
        semantic_targets.append(str(project_md))

        try:
            lines = len(project_md.read_text(encoding="utf-8").splitlines())
            if lines <= 200:
                score += 3
                findings.append(f"行數 {lines} <= 200（OK）")
            else:
                findings.append(f"WARN: 行數 {lines} > 200（Anthropic 建議上限）")
        except OSError as e:
            findings.append(f"WARN: CLAUDE.md 無法讀取行數：{e}")

        # 分層 cascade：subdir 是否有 CLAUDE.md
        sub_mds = _find_subdir_claude_mds(target_dir)
        if sub_mds:
            score += 1
            findings.append(f"分層 cascade：{len(sub_mds)} 個 subdir CLAUDE.md（per-subdir 慣例）")
            for s in sub_mds[:3]:
                semantic_targets.append(str(s))
        else:
            findings.append(
                "WARN: 無 subdir CLAUDE.md（Anthropic 建議在子目錄初始化，scope 到該層）"
            )

        # 新鮮度
        stale_score, stale_findings = _check_staleness(project_md)
        score += stale_score
        findings.extend(stale_findings)
    else:
        findings.append("WARN: CLAUDE.md 不存在（project root 未找到）")

    return MechanicalFinding(
        dimension="D1",
        label="CLAUDE.md 品質",
        score=score,
        max_score=_MECH_MAX,
        findings=findings,
        semantic_targets=semantic_targets,
    )

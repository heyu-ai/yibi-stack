"""D8 scanner：Security & Trust（機械分 8/13）。"""

from pathlib import Path

from ..models import MechanicalFinding

_MECH_MAX = 7
_INJECTION_PATTERNS = [
    "ignore previous instruction",
    "ignore all instruction",
    "disregard previous",
    "you are now",
    "new persona",
]
_DANGEROUS_CMDS = ["rm -rf /", "rm -rf ~", "curl | bash", "curl|bash", "wget | bash"]
_SENSITIVE_GITIGNORE = [".env", "*.key", "*.pem", "*.secret", "credentials"]


def scan_security(target_dir: Path) -> MechanicalFinding:
    """掃描 .gitignore、hook 危險指令、prompt injection 指標。語意分（5 分）由 agent 補充。"""
    findings: list[str] = []
    semantic_targets: list[str] = []
    score = 0
    gitignore_ok = False

    gitignore = target_dir / ".gitignore"
    if gitignore.exists():
        try:
            gi_content = gitignore.read_text(encoding="utf-8").lower()
        except OSError as e:
            findings.append(f"WARN: .gitignore 無法讀取：{e}")
            gi_content = ""
        if gi_content:
            covered = [p for p in _SENSITIVE_GITIGNORE if p in gi_content]
            if covered:
                score += 2
                gitignore_ok = True
                findings.append(f".gitignore 含敏感檔模式：{', '.join(covered)}")
            else:
                findings.append("WARN: .gitignore 未涵蓋敏感模式（.env / *.key）")
    else:
        findings.append("WARN: .gitignore 不存在")

    # findings 無論 gitignore 結果均執行；score 僅在 gitignore_ok 時累積（gitignore 是安全基線門檻）
    hooks_dir = target_dir / ".claude" / "hooks"
    if hooks_dir.exists():
        dangerous: list[str] = []
        for script in hooks_dir.glob("*.sh"):
            try:
                content_lower = script.read_text(encoding="utf-8").lower()
            except OSError:
                continue
            for danger in _DANGEROUS_CMDS:
                if danger in content_lower:
                    dangerous.append(f"{script.name}: '{danger}'")
        if not dangerous:
            if gitignore_ok:
                score += 2
            findings.append("hook scripts 無危險指令")
        else:
            for d in dangerous:
                findings.append(f"FAIL: 危險指令 {d}")
    else:
        if gitignore_ok:
            score += 2
        findings.append("無 hook scripts（不適用危險指令檢查）")

    injection_hits: list[str] = []
    check_files: list[Path] = []
    if (target_dir / "CLAUDE.md").exists():
        check_files.append(target_dir / "CLAUDE.md")
    rules_dir = target_dir / ".claude" / "rules"
    if rules_dir.exists():
        check_files.extend(rules_dir.glob("*.md"))

    for md_path in check_files:
        try:
            content_lower = md_path.read_text(encoding="utf-8").lower()
        except OSError:
            continue
        for pattern in _INJECTION_PATTERNS:
            if pattern in content_lower:
                injection_hits.append(f"{md_path.name}: '{pattern}'")
                semantic_targets.append(str(md_path))
                break

    if not injection_hits:
        if gitignore_ok:
            score += 3
        findings.append("CLAUDE.md / rules 無 prompt injection 指標")
    else:
        for hit in injection_hits:
            findings.append(f"WARN: 疑似 injection 指標 → {hit}")

    settings_path = target_dir / ".claude" / "settings.json"
    if settings_path.exists():
        semantic_targets.append(str(settings_path))

    return MechanicalFinding(
        dimension="D8",
        label="Security & Trust",
        score=score,
        max_score=_MECH_MAX,
        findings=findings,
        semantic_targets=semantic_targets,
    )

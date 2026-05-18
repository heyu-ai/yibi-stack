"""D5 scanner：Testing & CI 整合（機械分 7/12）。"""

import json
from pathlib import Path

from ..models import MechanicalFinding

_MECH_MAX = 7


def scan_testing(target_dir: Path) -> MechanicalFinding:
    """掃描測試檔案、CI 設定、hook-test 連結。語意分（5 分）由 agent 補充。"""
    findings: list[str] = []
    score = 0

    test_files = list(target_dir.rglob("test_*.py")) + list(target_dir.rglob("*.test.ts"))
    if test_files:
        score += 3
        findings.append(f"測試檔案存在（{len(test_files)} 個）")
    else:
        findings.append("WARN: 未找到測試檔案（test_*.py / *.test.ts）")

    wf_dir = target_dir / ".github" / "workflows"
    has_github_ci = wf_dir.exists() and any(wf_dir.glob("*.yml"))
    has_makefile_ci = False
    makefile = target_dir / "Makefile"
    if makefile.exists():
        content = makefile.read_text(encoding="utf-8")
        has_makefile_ci = "ci:" in content or "test:" in content

    if has_github_ci:
        score += 2
        findings.append("CI 設定存在（.github/workflows/）")
    elif has_makefile_ci:
        score += 2
        findings.append("CI target 存在（Makefile）")
    else:
        findings.append("WARN: 未找到 CI 設定")

    settings_path = target_dir / ".claude" / "settings.json"
    hook_links_test = False
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            hook_str = json.dumps(data.get("hooks", {})).lower()
            hook_links_test = "pytest" in hook_str or "test" in hook_str
        except json.JSONDecodeError:
            pass

    if hook_links_test:
        score += 2
        findings.append("hook 已連結自動測試（PostToolUse 或 Stop 含 test/pytest）")
    else:
        findings.append("WARN: hook 未連結自動測試")

    return MechanicalFinding(
        dimension="D5",
        label="Testing & CI 整合",
        score=score,
        max_score=_MECH_MAX,
        findings=findings,
    )

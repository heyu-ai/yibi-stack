"""D5 scanner：Testing & CI 整合（機械分 7/12）。"""

import json
import os
import re
from pathlib import Path

from ..models import MechanicalFinding

_MECH_MAX = 7
_SEMANTIC_TARGET_LIMIT = 20
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist", "build", ".claude"}
_MAX_SCAN_DEPTH = 5


def _has_factory_helpers(test_file: Path) -> bool:
    """回傳 True 當測試含 column-0 的 `def make_` 行（縮排方法、注釋行、呼叫表達式均不符合）。

    OSError（無讀取權限、broken symlink 等）時靜默回傳 False，呼叫端不補 WARN。
    """
    try:
        for line in test_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("def make_"):
                return True
    except OSError:
        pass
    return False


def _find_test_files(target_dir: Path) -> list[Path]:
    """掃描測試檔案，限制深度並跳過已知大型目錄以避免全樹遍歷效能問題。"""
    result: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(target_dir):
        depth = len(Path(dirpath).relative_to(target_dir).parts)
        if depth >= _MAX_SCAN_DEPTH:
            dirnames.clear()
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if (name.startswith("test_") and name.endswith(".py")) or name.endswith(".test.ts"):
                result.append(Path(dirpath) / name)
    return result


def scan_testing(target_dir: Path) -> MechanicalFinding:
    """掃描測試檔案、CI 設定、hook-test 連結。語意分（5 分）由 agent 補充。"""
    findings: list[str] = []
    score = 0

    test_files = _find_test_files(target_dir)
    factory_helper_files = [
        str(tf.relative_to(target_dir)) for tf in test_files if _has_factory_helpers(tf)
    ]
    semantic_targets = [str(tf) for tf in test_files[:_SEMANTIC_TARGET_LIMIT]]

    if test_files:
        score += 3
        findings.append(f"測試檔案存在（{len(test_files)} 個）")
    else:
        findings.append("WARN: 未找到測試檔案（test_*.py / *.test.ts）")

    wf_dir = target_dir / ".github" / "workflows"
    has_github_ci = wf_dir.exists() and (any(wf_dir.glob("*.yml")) or any(wf_dir.glob("*.yaml")))
    has_makefile_ci = False
    makefile = target_dir / "Makefile"
    if makefile.exists():
        try:
            content = makefile.read_text(encoding="utf-8")
            has_makefile_ci = "ci:" in content or "test:" in content
        except OSError as e:
            findings.append(f"WARN: Makefile 無法讀取，略過 CI target 偵測：{e}")

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
            hook_links_test = bool(
                re.search(
                    r"\b(pytest|jest|vitest|go\s+test|cargo\s+test|npm\s+test|mocha|rspec)\b",
                    hook_str,
                )
            )
        except OSError as e:
            findings.append(f"WARN: settings.json 無法讀取，略過 hook-test 連結偵測：{e}")
        except json.JSONDecodeError as e:
            findings.append(f"WARN: settings.json 格式錯誤，無法判斷 hook-test 連結：{e}")

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
        semantic_targets=semantic_targets,
        extra={"factory_helper_files": factory_helper_files},
    )

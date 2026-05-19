"""D2 scanner：Hooks 設定（機械分 12/18）。"""

import json
from pathlib import Path

from ..models import MechanicalFinding

_MECH_MAX = 12

# lifecycle hook 三級重要性
_CRITICAL_HOOKS: dict[str, str] = {
    "PreToolUse": "安全閘（攔截危險操作）",
    "PostToolUse": "品質迴圈（lint/type-check）",
    "Stop": "驗證閘（完成前自我確認）",
}
_IMPORTANT_HOOKS: dict[str, str] = {
    "SessionStart": "session 恢復（handover-back）",
    "PreCompact": "context 壓縮前保存交班",
}


def _collect_hook_script_paths(hooks: dict[str, object]) -> list[str]:
    """從 hooks 設定中收集所有 run 指令裡的 script 路徑。"""
    paths: list[str] = []
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            run = entry.get("run", "")
            if isinstance(run, str):
                for token in run.split():
                    if token.endswith(".sh") or token.endswith(".py"):
                        paths.append(token)
    return paths


def scan_hooks(target_dir: Path) -> MechanicalFinding:
    """掃描 settings.json 的 hooks 設定。語意分（6 分）由 agent 補充。"""
    findings: list[str] = []
    semantic_targets: list[str] = []
    score = 0

    settings_path = target_dir / ".claude" / "settings.json"
    if not settings_path.exists():
        findings.append("WARN: .claude/settings.json 不存在")
        return MechanicalFinding(
            dimension="D2",
            label="Hooks 設定",
            score=0,
            max_score=_MECH_MAX,
            findings=findings,
        )

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        findings.append(f"FAIL: settings.json 格式錯誤：{e}")
        return MechanicalFinding(
            dimension="D2",
            label="Hooks 設定",
            score=0,
            max_score=_MECH_MAX,
            findings=findings,
        )

    hooks = data.get("hooks", {})
    if not hooks:
        findings.append("WARN: settings.json 無 hooks 區塊")
        return MechanicalFinding(
            dimension="D2",
            label="Hooks 設定",
            score=0,
            max_score=_MECH_MAX,
            findings=findings,
        )

    # 基礎分：hooks 區塊存在
    score += 2
    findings.append("hooks 區塊存在")
    semantic_targets.append(str(settings_path))

    # 關鍵 hook 各 2 分（共 6 分）
    for hook_name, label in _CRITICAL_HOOKS.items():
        if hooks.get(hook_name):
            score += 2
            findings.append(f"{hook_name} {label}")
        else:
            findings.append(f"WARN: {hook_name} 未設定（用途：{label}）")

    # 重要 hook 各 1 分（共 2 分）
    for hook_name, label in _IMPORTANT_HOOKS.items():
        if hooks.get(hook_name):
            score += 1
            findings.append(f"{hook_name} {label}")
        else:
            findings.append(f"WARN: {hook_name} 未設定（用途：{label}）")

    # hook script 檔案存在性交叉驗證（2 分）
    script_paths = _collect_hook_script_paths(hooks)
    if script_paths:
        missing: list[str] = []
        for sp in script_paths:
            resolved = Path(sp) if Path(sp).is_absolute() else target_dir / sp
            if not resolved.exists():
                missing.append(sp)
        if missing:
            findings.append(
                f"WARN: {len(missing)} 個 hook script 登記但檔案不存在：{missing[:3]}"
            )
        else:
            score += 2
            findings.append(f"hook script 檔案存在性驗證通過（{len(script_paths)} 個）")

    return MechanicalFinding(
        dimension="D2",
        label="Hooks 設定",
        score=min(score, _MECH_MAX),
        max_score=_MECH_MAX,
        findings=findings,
        semantic_targets=semantic_targets,
    )

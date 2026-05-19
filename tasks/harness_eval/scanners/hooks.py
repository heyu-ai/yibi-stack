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
    """從 hooks 設定中收集 script 路徑。

    支援兩種 Claude Code hook schema：
    - 新版：entries[].hooks[].command（嵌套格式，`command` 欄位）
    - 舊版：entries[].run（平坦格式，`run` 欄位）
    """
    paths: list[str] = []
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            # 新版 Claude Code schema: {matcher: ..., hooks: [{type: command, command: ...}]}
            for hook in entry.get("hooks", []) or []:
                if not isinstance(hook, dict):
                    continue
                cmd = hook.get("command", "")
                if isinstance(cmd, str):
                    for token in cmd.split():
                        if token.endswith(".sh") or token.endswith(".py"):
                            paths.append(token)
            # 舊版 / 部分使用者的 schema: {run: "script.sh ..."}
            run = entry.get("run", "")
            if isinstance(run, str):
                for token in run.split():
                    if token.endswith(".sh") or token.endswith(".py"):
                        paths.append(token)
    return paths


def _has_inline_hooks(hooks: dict[str, object]) -> bool:
    """判斷是否有使用 inline 指令的 hook（非 script 檔案）。"""
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for hook in entry.get("hooks", []) or []:
                if isinstance(hook, dict):
                    cmd = hook.get("command", "")
                    if isinstance(cmd, str) and cmd and not any(
                        t.endswith(".sh") or t.endswith(".py") for t in cmd.split()
                    ):
                        return True
            run = entry.get("run", "")
            if isinstance(run, str) and run and not any(
                t.endswith(".sh") or t.endswith(".py") for t in run.split()
            ):
                return True
    return False


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
    except OSError as e:
        findings.append(f"FAIL: settings.json 無法讀取：{e}")
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
                # 嘗試 basename 比對（處理 $(git rev-parse ...) 前綴）
                base = Path(sp).name
                hook_dir = target_dir / ".claude" / "hooks"
                if not (hook_dir / base).exists():
                    missing.append(sp)
        if missing:
            findings.append(
                f"WARN: {len(missing)} 個 hook script 登記但檔案不存在：{missing[:3]}"
            )
        else:
            score += 2
            findings.append(f"hook script 檔案存在性驗證通過（{len(script_paths)} 個）")
    elif _has_inline_hooks(hooks):
        # inline hook 使用者不依賴 script 檔案，直接給 script 驗證分
        score += 2
        findings.append("hook 使用 inline 指令（無 script 路徑需驗證）")

    return MechanicalFinding(
        dimension="D2",
        label="Hooks 設定",
        score=min(score, _MECH_MAX),
        max_score=_MECH_MAX,
        findings=findings,
        semantic_targets=semantic_targets,
    )

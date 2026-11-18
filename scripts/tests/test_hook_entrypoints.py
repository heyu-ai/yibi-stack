"""HOOKENTRY-* doc-guard：已註冊 hook 的 command 指到的檔案必須存在。

AGENTS.md Known Gotchas 記錄兩種「hook 註冊了卻默默失效」的情況：script 改名或刪掉後
settings 仍指著舊路徑，以及 Python module 改名後 `python -m tasks.<old>` 找不到 `__main__`。
兩者都只在 hook 觸發時才報錯，CI 看不到。這裡把可以靜態解析的入口逐一檢查：

- `.claude/settings.json`：`${CLAUDE_PROJECT_DIR}/<path>` 必須是存在的檔案；command 的第一個
  token 就是該檔案時（直接執行），還必須有執行權限。
- `plugins/*/hooks/hooks.json`：`${CLAUDE_PLUGIN_ROOT}/<path>` 以該 plugin 目錄為基準必須存在。
- 任一 command 裡的 `python -m tasks.<module>` 必須有 `tasks/<module>/__main__.py`。

只驗 repo 內可靜態解析的路徑；指向 repo 外（例如 `~/.agents`）或動態組出的路徑不在範圍。
"""

import json
import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROJECT_SETTINGS = REPO_ROOT / ".claude" / "settings.json"

_PROJECT_PATH = re.compile(r"\$\{CLAUDE_PROJECT_DIR\}/([^\s\"';|&)]+)")
_PLUGIN_PATH = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\s\"';|&)]+)")
_TASK_MODULE = re.compile(r"python3?\s+-m\s+tasks\.([A-Za-z_][A-Za-z0-9_]*)")


def hook_commands(settings: dict) -> list[str]:
    """回傳 settings 裡所有 hook command 字串。"""
    commands: list[str] = []
    for groups in (settings.get("hooks") or {}).values():
        for group in groups:
            for hook in group.get("hooks", []):
                command = hook.get("command")
                if isinstance(command, str):
                    commands.append(command)
    return commands


def missing_entrypoints(commands: list[str], base: Path, var: re.Pattern[str]) -> list[str]:
    """回傳指到不存在檔案、缺執行權限、或 module 沒有 __main__.py 的問題描述。"""
    problems: list[str] = []
    for command in commands:
        for rel in var.findall(command):
            target = base / rel
            if not target.is_file():
                problems.append(f"{command!r}: {rel} 不存在")
            elif var.match(command.lstrip()) and not os.access(target, os.X_OK):
                # command 的第一個 token 就是這個檔案（不是 python3 / bash 帶起），需要執行權限
                problems.append(f"{command!r}: {rel} 沒有執行權限")
        for module in _TASK_MODULE.findall(command):
            if not (REPO_ROOT / "tasks" / module / "__main__.py").is_file():
                problems.append(f"{command!r}: tasks/{module}/__main__.py 不存在")
    return problems


class TestProjectSettingsHooks:
    def test_hookentry_vl_001_all_project_hooks_resolve(self) -> None:
        """HOOKENTRY-VL-001: .claude/settings.json 的 hook 入口都存在、直接執行的有執行權限。"""
        commands = hook_commands(json.loads(PROJECT_SETTINGS.read_text(encoding="utf-8")))
        # 解析前提：至少要解析到 hook，否則這個 guard 永遠是空轉的綠燈
        assert any(_PROJECT_PATH.search(c) for c in commands), (
            "解析前提不成立：沒有找到任何 hook 入口"
        )
        assert missing_entrypoints(commands, REPO_ROOT, _PROJECT_PATH) == []


class TestPluginHooks:
    @pytest.mark.parametrize(
        "hooks_json",
        sorted(REPO_ROOT.glob("plugins/*/hooks/hooks.json")),
        ids=lambda p: p.parent.parent.name,
    )
    def test_hookentry_vl_002_plugin_hooks_resolve(self, hooks_json: Path) -> None:
        """HOOKENTRY-VL-002: 每個 plugin 的 hooks.json 入口以 plugin 目錄為基準都存在。"""
        commands = hook_commands(json.loads(hooks_json.read_text(encoding="utf-8")))
        assert commands, f"解析前提不成立：{hooks_json} 沒有任何 hook command"
        assert missing_entrypoints(commands, hooks_json.parent.parent, _PLUGIN_PATH) == []


class TestDetectsBrokenEntrypoints:
    """負向對照：guard 要先證明對已知壞輸入會失敗，綠燈才有意義。"""

    def test_hookentry_dt_001_missing_script(self, tmp_path: Path) -> None:
        """HOOKENTRY-DT-001: 指到不存在的 script -> 回報。"""
        problems = missing_entrypoints(
            ["python3 ${CLAUDE_PROJECT_DIR}/.claude/hooks/gone.py || exit 2"],
            tmp_path,
            _PROJECT_PATH,
        )
        assert problems and "gone.py 不存在" in problems[0]

    def test_hookentry_dt_002_not_executable(self, tmp_path: Path) -> None:
        """HOOKENTRY-DT-002: 直接執行的 script 沒有 +x -> 回報；由 python3 帶起則不需要。"""
        script = tmp_path / ".claude" / "hooks" / "x.sh"
        script.parent.mkdir(parents=True)
        script.write_text("#!/bin/bash\n", encoding="utf-8")
        script.chmod(0o644)
        direct = missing_entrypoints(
            ["${CLAUDE_PROJECT_DIR}/.claude/hooks/x.sh || exit 2"], tmp_path, _PROJECT_PATH
        )
        assert direct and "沒有執行權限" in direct[0]
        via_bash = missing_entrypoints(
            ['bash "${CLAUDE_PROJECT_DIR}/.claude/hooks/x.sh"'], tmp_path, _PROJECT_PATH
        )
        assert via_bash == []

    def test_hookentry_dt_003_renamed_task_module(self, tmp_path: Path) -> None:
        """HOOKENTRY-DT-003: `python -m tasks.<改名前的 module>` -> 回報。"""
        problems = missing_entrypoints(
            ["uv run python -m tasks.session_memory_renamed hook"], tmp_path, _PROJECT_PATH
        )
        assert problems and "__main__.py 不存在" in problems[0]

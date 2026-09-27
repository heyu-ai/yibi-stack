"""detect_voices.py 的測試：pr-cycle-deep Step 0 的外部 reviewer 偵測。

偵測原本是 SKILL.md 裡的 5 段 inline bash，agent 每次照抄重寫。搬進 script 後，
輸出格式（`CODEX_AUTH: KEY_SET` 等）仍是 SKILL.md Mode determination 表與
`~/.claude/mob-detection-cache` 依賴的介面，所以這裡逐一鎖住每個狀態的輸出字串。

兩層：
  * 函式層——直接餵 env mapping 與假 HOME，覆蓋每個 if/elif 分支。
  * 端到端——以 subprocess 執行 script，HOME／PATH 指向 tmp_path，確認 CLI 輸出與 exit code。
"""

from __future__ import annotations

import json
import os
import stat
import subprocess  # nosec B404
import sys
from pathlib import Path

import detect_voices as dv
import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "detect_voices.py"
AGY_SCRIPTS = ["agy-r1-stage1.sh", "agy-r1-stage2.sh", "agy-r2.sh"]


def _write_onboarding(home: Path, payload: object) -> Path:
    p = home / ".gemini" / "antigravity-cli" / "cache" / "onboarding.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(payload) if not isinstance(payload, str) else payload)
    return p


def _write_settings(home: Path, allow: list[str]) -> None:
    p = home / ".claude" / "settings.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"permissions": {"allow": allow}}))


def _agy_allow_entries(home: Path) -> list[str]:
    scripts = home / ".agents" / "skills" / "pr-cycle-deep" / "scripts"
    return [f"Bash(bash {scripts / name})" for name in AGY_SCRIPTS]


# --------------------------------------------------------------------------- #
# Codex auth
# --------------------------------------------------------------------------- #


class TestCodexAuth:
    @pytest.mark.parametrize("key", ["CODEX_API_KEY", "OPENAI_API_KEY"])
    def test_dv_dt_001_key_set(self, tmp_path: Path, key: str) -> None:
        """DV-DT-001: 任一 key 以非空白字元開頭即 KEY_SET。"""
        assert dv.codex_auth({key: "sk-abc"}, tmp_path) == "KEY_SET"

    def test_dv_dt_002_whitespace_prefix(self, tmp_path: Path) -> None:
        """DV-DT-002: key 以空白開頭（從終端機複製常見）回報 KEY_WHITESPACE_PREFIX。"""
        assert dv.codex_auth({"OPENAI_API_KEY": " sk-abc"}, tmp_path) == "KEY_WHITESPACE_PREFIX"

    def test_dv_dt_003_good_key_beats_whitespace_key(self, tmp_path: Path) -> None:
        """DV-DT-003: 一把好 key 就夠——另一把帶空白不應讓結果變成失敗。"""
        env = {"CODEX_API_KEY": " bad", "OPENAI_API_KEY": "good"}
        assert dv.codex_auth(env, tmp_path) == "KEY_SET"

    def test_dv_dt_004_auth_file(self, tmp_path: Path) -> None:
        """DV-DT-004: 無 key 但 ~/.codex/auth.json 非空 → FILE_EXISTS。"""
        (tmp_path / ".codex").mkdir()
        (tmp_path / ".codex" / "auth.json").write_text("{}")
        assert dv.codex_auth({}, tmp_path) == "FILE_EXISTS"

    def test_dv_dt_005_empty_auth_file_is_not_authed(self, tmp_path: Path) -> None:
        """DV-DT-005: 空的 auth.json 等同沒登入（對應原本 `test -s`）。"""
        (tmp_path / ".codex").mkdir()
        (tmp_path / ".codex" / "auth.json").write_text("")
        assert dv.codex_auth({}, tmp_path) == "NOT_AUTHED"

    def test_dv_dt_006_empty_key_falls_through(self, tmp_path: Path) -> None:
        """DV-DT-006: 空字串 key 不算設定，繼續看 auth.json，最後 NOT_AUTHED。"""
        assert dv.codex_auth({"CODEX_API_KEY": ""}, tmp_path) == "NOT_AUTHED"


# --------------------------------------------------------------------------- #
# Gemini (agy) auth
# --------------------------------------------------------------------------- #


class TestGeminiAuth:
    def test_dv_dt_010_onboarded(self, tmp_path: Path) -> None:
        """DV-DT-010: onboardingComplete: true → ONBOARDED（優先於 env key）。"""
        _write_onboarding(tmp_path, {"onboardingComplete": True})
        assert dv.gemini_auth({"GEMINI_API_KEY": " x"}, tmp_path) == "ONBOARDED"

    def test_dv_dt_011_onboarding_incomplete_falls_to_key(self, tmp_path: Path) -> None:
        """DV-DT-011: onboardingComplete: false 不算，改看 env key。"""
        _write_onboarding(tmp_path, {"onboardingComplete": False})
        assert dv.gemini_auth({"GOOGLE_API_KEY": "abc"}, tmp_path) == "KEY_SET"

    def test_dv_dt_012_whitespace_prefix(self, tmp_path: Path) -> None:
        """DV-DT-012: Gemini key 帶前導空白 → KEY_WHITESPACE_PREFIX。"""
        assert dv.gemini_auth({"GEMINI_API_KEY": "\tabc"}, tmp_path) == "KEY_WHITESPACE_PREFIX"

    def test_dv_dt_013_not_authed(self, tmp_path: Path) -> None:
        """DV-DT-013: 什麼都沒有 → NOT_AUTHED。"""
        assert dv.gemini_auth({}, tmp_path) == "NOT_AUTHED"

    def test_dv_dt_014_corrupt_onboarding_warns_and_falls_through(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """DV-DT-014: onboarding.json 壞掉不 crash，往下判斷，並在 stderr 留 [WARN]。"""
        _write_onboarding(tmp_path, "{not json")
        assert dv.gemini_auth({}, tmp_path) == "NOT_AUTHED"
        assert "[WARN]" in capsys.readouterr().err

    def test_dv_dt_015_non_dict_onboarding(self, tmp_path: Path) -> None:
        """DV-DT-015: onboarding.json 是合法 JSON 但不是 object，也不算 onboarded。"""
        _write_onboarding(tmp_path, [True])
        assert dv.gemini_auth({}, tmp_path) == "NOT_AUTHED"


# --------------------------------------------------------------------------- #
# agy allow-list
# --------------------------------------------------------------------------- #


class TestAllowList:
    def test_dv_dt_020_all_present(self, tmp_path: Path) -> None:
        """DV-DT-020: 三支 agy script 的絕對路徑 entry 都在 → OK。"""
        _write_settings(tmp_path, _agy_allow_entries(tmp_path))
        assert dv.agy_allow_list(tmp_path) == "OK"

    def test_dv_dt_021_one_missing(self, tmp_path: Path) -> None:
        """DV-DT-021: 少一支 → MISSING。"""
        _write_settings(tmp_path, _agy_allow_entries(tmp_path)[:2])
        assert dv.agy_allow_list(tmp_path) == "MISSING"

    def test_dv_dt_022_no_settings(self, tmp_path: Path) -> None:
        """DV-DT-022: 沒有 settings.json → MISSING。"""
        assert dv.agy_allow_list(tmp_path) == "MISSING"

    def test_dv_dt_023_corrupt_settings_warns(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """DV-DT-023: settings.json 壞掉 → MISSING + stderr [WARN]，不 crash。"""
        p = tmp_path / ".claude" / "settings.json"
        p.parent.mkdir(parents=True)
        p.write_text("{oops")
        assert dv.agy_allow_list(tmp_path) == "MISSING"
        assert "[WARN]" in capsys.readouterr().err

    def test_dv_dt_024_permissions_wrong_shape(self, tmp_path: Path) -> None:
        """DV-DT-024: permissions 不是 object 時不 crash，回 MISSING。"""
        p = tmp_path / ".claude" / "settings.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"permissions": ["x"]}))
        assert dv.agy_allow_list(tmp_path) == "MISSING"


# --------------------------------------------------------------------------- #
# End-to-end CLI
# --------------------------------------------------------------------------- #


def _fake_bin(bin_dir: Path, name: str) -> None:
    bin_dir.mkdir(exist_ok=True)
    p = bin_dir / name
    p.write_text("#!/bin/sh\nexit 0\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)


def _run(home: Path, path: str, *args: str, extra_env: dict[str, str] | None = None):
    env = {"HOME": str(home), "PATH": path}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(  # nosec B603
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )


class TestCli:
    def test_dv_dt_030_full_output_lines_in_order(self, tmp_path: Path) -> None:
        """DV-DT-030: 預設模式依序輸出 5 行，前綴與原 SKILL.md bash 區塊一致。"""
        bin_dir = tmp_path / "bin"
        _fake_bin(bin_dir, "codex")
        _fake_bin(bin_dir, "agy")
        _write_onboarding(tmp_path, {"onboardingComplete": True})
        _write_settings(tmp_path, _agy_allow_entries(tmp_path))
        result = _run(tmp_path, str(bin_dir), extra_env={"OPENAI_API_KEY": "sk"})
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [
            "CODEX: BINARY_OK",
            "CODEX_AUTH: KEY_SET",
            "GEMINI: BINARY_OK",
            "GEMINI_AUTH: ONBOARDED",
            "GEMINI_ALLOW_LIST: OK",
        ]

    def test_dv_dt_031_binaries_not_found(self, tmp_path: Path) -> None:
        """DV-DT-031: PATH 上沒有 codex／agy → NOT_FOUND（仍 exit 0：偵測結果不是錯誤）。"""
        empty = tmp_path / "empty"
        empty.mkdir()
        result = _run(tmp_path, str(empty))
        assert result.returncode == 0, result.stderr
        lines = result.stdout.splitlines()
        assert "CODEX: NOT_FOUND" in lines
        assert "GEMINI: NOT_FOUND" in lines

    def test_dv_dt_032_auth_only(self, tmp_path: Path) -> None:
        """DV-DT-032: --auth-only（Step 0a warm path）只輸出兩行 auth。"""
        empty = tmp_path / "empty"
        empty.mkdir()
        result = _run(tmp_path, str(empty), "--auth-only")
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [
            "CODEX_AUTH: NOT_AUTHED",
            "GEMINI_AUTH: NOT_AUTHED",
        ]

    def test_dv_dt_033_unknown_flag_is_usage_error(self, tmp_path: Path) -> None:
        """DV-DT-033: 未知參數 → exit 2，不輸出任何偵測結果。"""
        result = _run(tmp_path, os.defpath, "--bogus")
        assert result.returncode == 2
        assert result.stdout == ""

    def test_dv_dt_034_never_prints_key_value(self, tmp_path: Path) -> None:
        """DV-DT-034: 任何輸出都不得包含 key 本身（避免 key 進 session transcript）。"""
        secret = "sk-SECRET-VALUE-123"
        result = _run(
            tmp_path,
            os.defpath,
            extra_env={"CODEX_API_KEY": secret, "GEMINI_API_KEY": " " + secret},
        )
        assert secret not in result.stdout
        assert secret not in result.stderr


class TestSkillMdWiring:
    def test_dv_dt_040_skill_md_calls_script_not_inline_bash(self) -> None:
        """DV-DT-040: SKILL.md 不再內嵌 auth 偵測 bash，改呼叫 script——防止 inline 區塊回流。"""
        skill_md = SCRIPT.parent.parent / "SKILL.md"
        src = skill_md.read_text(encoding="utf-8")
        assert "detect_voices.py" in src
        assert 'echo "CODEX_AUTH:' not in src
        assert 'echo "GEMINI_AUTH:' not in src

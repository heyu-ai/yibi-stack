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
from collections.abc import Sequence
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


def _write_settings(home: Path, allow: Sequence[object]) -> None:
    p = home / ".claude" / "settings.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"permissions": {"allow": list(allow)}}))


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

    def test_dv_dt_007_unreadable_codex_dir_warns_not_authed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """DV-DT-007: ~/.codex 無權限（chmod 000）不 crash，視為沒有 auth.json。

        結果 NOT_AUTHED，stderr 留 [WARN]。

        對應原 bash 的 `test -s`：讀不到就是不成立，不會讓整段偵測失敗。
        """
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        (codex_dir / "auth.json").write_text("{}")
        codex_dir.chmod(0)
        try:
            assert dv.codex_auth({}, tmp_path) == "NOT_AUTHED"
        finally:
            codex_dir.chmod(stat.S_IRWXU)
        assert "[WARN]" in capsys.readouterr().err

    def test_dv_dt_008_whitespace_key_beats_auth_file(self, tmp_path: Path) -> None:
        """DV-DT-008: 帶前導空白的 key 優先於非空 auth.json → KEY_WHITESPACE_PREFIX。

        對應原 bash 的 elif 順序。

        使用者設了 key 卻設壞了，要讓他知道 key 壞掉，而不是被 auth.json 蓋過。
        """
        (tmp_path / ".codex").mkdir()
        (tmp_path / ".codex" / "auth.json").write_text("{}")
        assert dv.codex_auth({"OPENAI_API_KEY": " sk"}, tmp_path) == "KEY_WHITESPACE_PREFIX"

    @pytest.mark.parametrize("prefix", [" ", "\t", "\n", "\r", "\v", "\f"])
    def test_dv_dt_009_ascii_space_is_whitespace_prefix(self, tmp_path: Path, prefix: str) -> None:
        """DV-DT-009: ASCII 空白字元開頭都算 KEY_WHITESPACE_PREFIX。

        `\\n` 開頭是與原 `env | grep` 刻意的差異（見 `_key_state` docstring），
        其餘五個與原 bash 一致。
        """
        assert dv.codex_auth({"CODEX_API_KEY": prefix + "sk"}, tmp_path) == "KEY_WHITESPACE_PREFIX"

    def test_dv_dt_009b_nbsp_prefix_is_whitespace_prefix(self, tmp_path: Path) -> None:
        """DV-DT-009b: U+00A0 開頭 → KEY_WHITESPACE_PREFIX。

        原 inline bash 在使用者的 UTF-8 locale 下跑，macOS grep 的 `[[:space:]]` 會匹配 U+00A0
        （`LANG=en_US.UTF-8` 實測；只有 `LANG=C` 不匹配），所以原本也是判成 key 設壞了。
        """
        assert dv.codex_auth({"CODEX_API_KEY": "\u00a0sk"}, tmp_path) == "KEY_WHITESPACE_PREFIX"

    def test_dv_dt_009c_absent_auth_file_is_silent(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """DV-DT-009c: 沒有 key、也沒有 ~/.codex/auth.json 是正常情況（沒裝 codex），不 [WARN]。"""
        assert dv.codex_auth({}, tmp_path) == "NOT_AUTHED"
        assert capsys.readouterr().err == ""


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

    def test_dv_dt_015_non_dict_onboarding(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """DV-DT-015: onboarding.json 是合法 JSON 但不是 object → 不算 onboarded，stderr [WARN]。"""
        _write_onboarding(tmp_path, [True])
        assert dv.gemini_auth({}, tmp_path) == "NOT_AUTHED"
        err = capsys.readouterr().err
        assert "[WARN]" in err
        assert "onboarding.json" in err

    def test_dv_dt_016_non_utf8_onboarding_warns(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """DV-DT-016: onboarding.json 不是 UTF-8 → 不 crash，往下看 env key，stderr [WARN]。"""
        p = _write_onboarding(tmp_path, "{}")
        p.write_bytes(b"\xff\xfe{")
        assert dv.gemini_auth({"GEMINI_API_KEY": "abc"}, tmp_path) == "KEY_SET"
        assert "[WARN]" in capsys.readouterr().err

    def test_dv_dt_017_absent_onboarding_is_silent(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """DV-DT-017: onboarding.json 不存在是正常情況（沒裝 agy），不印任何 [WARN]。"""
        assert dv.gemini_auth({}, tmp_path) == "NOT_AUTHED"
        assert capsys.readouterr().err == ""

    def test_dv_dt_018_null_onboarding_warns(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """DV-DT-018: onboarding.json 內容是 JSON null → 形狀不對，[WARN]。

        不可與「檔案不存在」混為一談。
        """
        _write_onboarding(tmp_path, None)
        assert dv.gemini_auth({}, tmp_path) == "NOT_AUTHED"
        assert "[WARN]" in capsys.readouterr().err

    def test_dv_dt_019_unreadable_agy_cache_dir_warns(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """DV-DT-019: agy cache 目錄無權限 → [WARN]，不可靜默當成「不存在」。

        Python 3.14 的 `Path.is_file()` 遇到權限錯誤會回 False 而不 raise，
        所以判斷存在與否不能靠 `is_file()`。
        """
        p = _write_onboarding(tmp_path, {"onboardingComplete": True})
        p.parent.chmod(0)
        try:
            assert dv.gemini_auth({}, tmp_path) == "NOT_AUTHED"
        finally:
            p.parent.chmod(stat.S_IRWXU)
        assert "[WARN]" in capsys.readouterr().err


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

    @pytest.mark.parametrize(
        "payload",
        [
            ["x"],  # 頂層不是 object
            None,  # 頂層是 JSON null（檔案存在，不是「沒有檔案」）
            {"permissions": ["x"]},  # permissions 不是 object
            {"permissions": None},  # permissions 存在但是 null
            {"permissions": {"allow": "x"}},  # allow 不是 list
        ],
    )
    def test_dv_dt_024_wrong_shape_warns(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], payload: object
    ) -> None:
        """DV-DT-024: settings.json 形狀不對時不 crash，回 MISSING，stderr [WARN] 並指名檔案。"""
        p = tmp_path / ".claude" / "settings.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(payload))
        assert dv.agy_allow_list(tmp_path) == "MISSING"
        err = capsys.readouterr().err
        assert "[WARN]" in err
        assert "settings.json" in err

    @pytest.mark.parametrize("payload", [{}, {"permissions": {}}])
    def test_dv_dt_025_missing_key_is_silent_missing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], payload: object
    ) -> None:
        """DV-DT-025: 沒有 permissions／allow key 是「沒設 allow-list」，回 MISSING 但不警告。"""
        p = tmp_path / ".claude" / "settings.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(payload))
        assert dv.agy_allow_list(tmp_path) == "MISSING"
        assert capsys.readouterr().err == ""

    def test_dv_dt_026_unhashable_allow_entry(self, tmp_path: Path) -> None:
        """DV-DT-026: allow 內有 dict 等不可 hash 的元素也不 crash，其餘 entry 照常比對。"""
        _write_settings(tmp_path, [{"a": 1}, *_agy_allow_entries(tmp_path)])
        assert dv.agy_allow_list(tmp_path) == "OK"


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

    def test_dv_dt_035_unhashable_allow_entry_end_to_end(self, tmp_path: Path) -> None:
        """DV-DT-035: allow 含 dict → 仍 exit 0、5 行齊全，最後一行 MISSING（不 traceback）。"""
        p = tmp_path / ".claude" / "settings.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"permissions": {"allow": [{"a": 1}]}}))
        result = _run(tmp_path, os.defpath)
        assert result.returncode == 0, result.stderr
        lines = result.stdout.splitlines()
        assert len(lines) == 5
        assert lines[-1] == "GEMINI_ALLOW_LIST: MISSING"

    def test_dv_dt_036_non_utf8_settings_end_to_end(self, tmp_path: Path) -> None:
        """DV-DT-036: settings.json 不是 UTF-8 → exit 0、MISSING、stderr [WARN]。"""
        p = tmp_path / ".claude" / "settings.json"
        p.parent.mkdir(parents=True)
        p.write_bytes(b'{"permissions": "\xb4\xfa"}')
        result = _run(tmp_path, os.defpath)
        assert result.returncode == 0, result.stderr
        lines = result.stdout.splitlines()
        assert len(lines) == 5
        assert lines[-1] == "GEMINI_ALLOW_LIST: MISSING"
        assert "[WARN]" in result.stderr

    def test_dv_dt_037_non_utf8_onboarding_end_to_end(self, tmp_path: Path) -> None:
        """DV-DT-037: onboarding.json 不是 UTF-8 → exit 0、退回 env key 判斷、stderr [WARN]。"""
        p = _write_onboarding(tmp_path, "{}")
        p.write_bytes(b"\xff")
        result = _run(tmp_path, os.defpath, "--auth-only", extra_env={"GOOGLE_API_KEY": "k"})
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [
            "CODEX_AUTH: NOT_AUTHED",
            "GEMINI_AUTH: KEY_SET",
        ]
        assert "[WARN]" in result.stderr

    def test_dv_dt_038_unreadable_dirs_end_to_end(self, tmp_path: Path) -> None:
        """DV-DT-038: ~/.codex 與 ~/.claude 都無權限 → exit 0、5 行齊全、NOT_AUTHED／MISSING。

        兩個檔案都要在 stderr 各留一行 [WARN]（不能因為讀不到就當成不存在而靜默）。
        """
        locked = [tmp_path / ".codex", tmp_path / ".claude"]
        for d in locked:
            d.mkdir()
        (tmp_path / ".codex" / "auth.json").write_text("{}")
        (tmp_path / ".claude" / "settings.json").write_text("{}")
        try:
            for d in locked:
                d.chmod(0)
            result = _run(tmp_path, os.defpath)
        finally:
            for d in locked:
                d.chmod(stat.S_IRWXU)
        assert result.returncode == 0, result.stderr
        lines = result.stdout.splitlines()
        assert len(lines) == 5
        assert lines[1] == "CODEX_AUTH: NOT_AUTHED"
        assert lines[-1] == "GEMINI_ALLOW_LIST: MISSING"
        assert "auth.json" in result.stderr
        assert "settings.json" in result.stderr


SKILLS_DIR = SCRIPT.parent.parent.parent
WIRED_SKILL_MDS = [
    SKILLS_DIR / "pr-cycle-deep" / "SKILL.md",
    SKILLS_DIR / "mob-code-review-only" / "SKILL.md",
]
# 被 detect_voices.py 取代的舊 inline 偵測 bash 的特徵字串；任何一個回到 SKILL.md 就代表回流。
REMOVED_INLINE_MARKERS = [
    'echo "CODEX_AUTH:',
    'echo "GEMINI_AUTH:',
    'echo "GEMINI_ALLOW_LIST:',
    'echo "CODEX: BINARY_OK',
    "env | grep -qE",
]


class TestSkillMdWiring:
    @pytest.mark.parametrize("skill_md", WIRED_SKILL_MDS, ids=lambda p: p.parent.name)
    def test_dv_dt_040_skill_md_calls_script_not_inline_bash(self, skill_md: Path) -> None:
        """DV-DT-040: 兩份 SKILL.md 都呼叫 detect_voices.py，且不含舊 inline 偵測 bash 的特徵字串。

        只檢查字串層級的接線：script 名稱出現、舊區塊的 echo／env grep 形狀不出現。
        不驗證 agent 實際照做（那是執行期行為，文件測試證明不了）。
        """
        src = skill_md.read_text(encoding="utf-8")
        assert "detect_voices.py" in src
        for marker in REMOVED_INLINE_MARKERS:
            assert marker not in src, (
                f"{skill_md.parent.name}/SKILL.md 出現舊 inline 偵測：{marker}"
            )

    def test_dv_dt_041_step_0a_uses_auth_only(self) -> None:
        """DV-DT-041: pr-cycle-deep Step 0a warm path 實際呼叫 `detect_voices.py --auth-only`。

        比對完整的 `python3 ~/.agents/...` 呼叫字串，而不是只找 `--auth-only`——
        allow-list 說明段落也含 `detect_voices.py --auth-only`（`/Users/<you>/` 形式），
        只找片段的話 Step 0a 呼叫被刪掉測試仍會綠。
        """
        src = WIRED_SKILL_MDS[0].read_text(encoding="utf-8")
        assert "python3 ~/.agents/skills/pr-cycle-deep/scripts/detect_voices.py --auth-only" in src

"""Tests for plugins/dev-cycle/skills/pr-cycle-deep/scripts/codex_version_gate.py.

The review stages pin gpt-6-astra, which codex-cli 0.149.0 refuses with a 400 and
0.154.0-alpha.6.2 serves (both measured). The gate turns that deep-in-the-log failure into an
up-front [FAIL] naming the upgrade.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from codex_version_gate import main, parse_codex_version, parse_min_version


class TestParseCodexVersion:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("codex-cli 0.154.0\n", (0, 154, 0)),
            ("codex-cli 0.154.0-alpha.6.2\n", (0, 154, 0)),
            (
                "WARNING: proceeding, even though we could not create PATH aliases\n"
                "codex-cli 0.149.0\n",
                (0, 149, 0),
            ),
            ("codex-cli 1.2.3", (1, 2, 3)),
        ],
    )
    def test_cdxv_dt_001_parses_release_prerelease_and_noisy_output(
        self, text: str, expected: tuple[int, int, int]
    ) -> None:
        """CDXV-DT-001: the numeric core is extracted; prerelease suffix and warnings ignored."""
        assert parse_codex_version(text) == expected

    @pytest.mark.parametrize("text", ["", "codex 0.154", "something else 1.2.3"])
    def test_cdxv_dt_002_unparseable_returns_none(self, text: str) -> None:
        """CDXV-DT-002: output without a `codex-cli X.Y.Z` token yields None."""
        assert parse_codex_version(text) is None


class TestParseMinVersion:
    def test_cdxv_dt_003_valid(self) -> None:
        """CDXV-DT-003: X.Y.Z parses to a tuple."""
        assert parse_min_version("0.154.0") == (0, 154, 0)

    @pytest.mark.parametrize("raw", ["0.154", "v0.154.0", "0.154.0-alpha", ""])
    def test_cdxv_dt_004_invalid_raises(self, raw: str) -> None:
        """CDXV-DT-004: anything but a plain X.Y.Z is a caller bug -> ValueError."""
        with pytest.raises(ValueError):
            parse_min_version(raw)


def _fake_codex(bin_dir: Path, body: str, exit_code: int = 0) -> None:
    bin_dir.mkdir()
    codex = bin_dir / "codex"
    codex.write_text(
        # Absolute shebang: PATH is narrowed to bin_dir alone, so `env bash` would not resolve.
        f"#!/bin/bash\nprintf '%s\\n' '{body}'\nexit {exit_code}\n",
        encoding="utf-8",
    )
    codex.chmod(0o755)


def _run(monkeypatch: pytest.MonkeyPatch, bin_dir: Path, *extra: str) -> int:
    monkeypatch.setenv("PATH", str(bin_dir))
    return main(["--min-version", "0.154.0", "--model", "gpt-6-astra", "--label", "t", *extra])


class TestMain:
    @pytest.mark.parametrize("version", ["0.154.0", "0.154.0-alpha.6.2", "0.155.1", "1.0.0"])
    def test_cdxv_st_001_new_enough_passes(
        self, version: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CDXV-ST-001: >= 0.154.0 (prerelease of 0.154.0 included) exits 0."""
        _fake_codex(tmp_path / "bin", f"codex-cli {version}")
        assert _run(monkeypatch, tmp_path / "bin") == 0

    @pytest.mark.parametrize("version", ["0.149.0", "0.153.99"])
    def test_cdxv_st_002_too_old_exits_1_with_upgrade_hint(
        self,
        version: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """CDXV-ST-002: an older CLI exits 1 and names both versions, the model, and the fix."""
        _fake_codex(tmp_path / "bin", f"codex-cli {version}")
        assert _run(monkeypatch, tmp_path / "bin") == 1
        err = capsys.readouterr().err
        assert "[FAIL]" in err and version in err and "0.154.0" in err
        assert "gpt-6-astra" in err
        assert "npm install -g @openai/codex" in err

    def test_cdxv_st_003_missing_codex_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CDXV-ST-003: codex not on PATH cannot be judged -> exit 2, never a pass."""
        empty = tmp_path / "empty"
        empty.mkdir()
        assert _run(monkeypatch, empty) == 2
        assert "[FAIL]" in capsys.readouterr().err

    def test_cdxv_st_004_unparseable_output_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CDXV-ST-004: a --version output with no version token exits 2 and shows the output."""
        _fake_codex(tmp_path / "bin", "totally unexpected")
        assert _run(monkeypatch, tmp_path / "bin") == 2
        assert "totally unexpected" in capsys.readouterr().err

    def test_cdxv_st_005_nonzero_version_command_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CDXV-ST-005: `codex --version` failing is not trusted even if it printed a version."""
        _fake_codex(tmp_path / "bin", "codex-cli 0.154.0", exit_code=3)
        assert _run(monkeypatch, tmp_path / "bin") == 2

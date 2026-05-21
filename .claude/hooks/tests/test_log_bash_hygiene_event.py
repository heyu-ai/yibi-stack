"""log_bash_hygiene_event.py 的單元測試。"""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

# scripts/ 在 testpath 外，需手動加入 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))
import log_bash_hygiene_event as _m

_SCRIPT = Path(__file__).parent.parent.parent.parent / "scripts" / "log_bash_hygiene_event.py"


def make_log_path(tmp_path: Path) -> Path:
    return tmp_path / ".agents" / "bash-hygiene-events.jsonl"


class TestCmdName:
    def test_simple_command(self) -> None:
        """LOGEVENT-DT-001: 純指令名稱正確提取"""
        assert _m._cmd_name("git status") == "git"

    def test_env_prefix_stripped(self) -> None:
        """LOGEVENT-DT-002: KEY=value 前綴被剝除，只記錄指令名稱"""
        assert _m._cmd_name("FOO_TOKEN=abc123 bash script.sh") == "bash"

    def test_multiple_env_prefixes(self) -> None:
        """LOGEVENT-DT-003: 多個 KEY=value 前綴全部剝除"""
        assert _m._cmd_name("A=1 B=secret curl https://example.com") == "curl"

    def test_truncated_at_40(self) -> None:
        """LOGEVENT-DT-004: 超長指令名稱截斷至 40 字元"""
        long_name = "a" * 50
        assert _m._cmd_name(long_name) == "a" * 40

    def test_empty_command(self) -> None:
        """LOGEVENT-DT-005: 空字串不 crash"""
        assert _m._cmd_name("") == ""

    def test_only_env_vars(self) -> None:
        """LOGEVENT-DT-006: 只有 KEY=value 沒有指令（邊界情況）"""
        result = _m._cmd_name("FOO=bar ")
        assert isinstance(result, str)


class TestLogEvent:
    def test_writes_jsonl_record(self, tmp_path: Path) -> None:
        """LOGEVENT-ST-001: 寫入一行合法 JSONL，欄位齊全"""
        log_path = make_log_path(tmp_path)
        with patch.object(Path, "home", return_value=tmp_path):
            _m.log_event("ap1", "python_c_multiline", "python3 script.py")

        assert log_path.exists()
        rec = json.loads(log_path.read_text())
        assert rec["hook"] == "ap1"
        assert rec["pattern"] == "python_c_multiline"
        assert rec["cmd_name"] == "python3"
        assert rec["ts"].endswith("+00:00") or "T" in rec["ts"]

    def test_cmd_name_field_not_credential(self, tmp_path: Path) -> None:
        """LOGEVENT-ST-002: KEY=value 指令只記錄指令名稱，不含 token"""
        with patch.object(Path, "home", return_value=tmp_path):
            _m.log_event(
                "ap2", "unicode_U+02014", "SECRET_TOKEN=abc123 curl https://api.example.com"
            )

        log_path = make_log_path(tmp_path)
        rec = json.loads(log_path.read_text())
        assert rec["cmd_name"] == "curl"
        assert "SECRET_TOKEN" not in json.dumps(rec)
        assert "abc123" not in json.dumps(rec)

    def test_auto_creates_directory(self, tmp_path: Path) -> None:
        """LOGEVENT-ST-003: ~/.agents/ 目錄不存在時自動建立"""
        assert not (tmp_path / ".agents").exists()
        with patch.object(Path, "home", return_value=tmp_path):
            _m.log_event("ap1", "osascript_heredoc", "osascript <<EOF")
        assert (tmp_path / ".agents").is_dir()

    def test_appends_multiple_records(self, tmp_path: Path) -> None:
        """LOGEVENT-ST-004: 多次呼叫累加，每行獨立合法 JSON"""
        with patch.object(Path, "home", return_value=tmp_path):
            _m.log_event("ap1", "pattern_a", "cmd_a")
            _m.log_event("ap2", "pattern_b", "cmd_b")

        lines = make_log_path(tmp_path).read_text().strip().splitlines()
        assert len(lines) == 2
        recs = [json.loads(line) for line in lines]
        assert recs[0]["pattern"] == "pattern_a"
        assert recs[1]["pattern"] == "pattern_b"

    def test_fail_open_when_io_error(self, tmp_path: Path) -> None:
        """LOGEVENT-EG-001: 目錄是檔案（I/O 錯誤）時不 raise，hook 繼續正常運作"""
        agents_dir = tmp_path / ".agents"
        agents_dir.write_text("I am a file, not a directory")
        with patch.object(Path, "home", return_value=tmp_path):
            _m.log_event("ap1", "test", "cmd")  # 不應 raise


class TestMainEntrypoint:
    def test_missing_args_exits_0(self) -> None:
        """LOGEVENT-EG-002: 引數不足時 exit 0（fail-open，不影響 hook caller）"""
        result = subprocess.run(  # nosec B603
            [sys.executable, str(_SCRIPT)],
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_log_script_path_exists_in_repo(self) -> None:
        """LOGEVENT-EG-003: scripts/log_bash_hygiene_event.py 在 repo 內可被 hook 找到"""
        assert _SCRIPT.is_file(), f"log script not found at expected path: {_SCRIPT}"

"""每一個實際執行的 `codex exec` 指令都必須明確 pin 模型（issue #511）。

背景：未帶 `-m` 時，codex 依 `~/.codex/config.toml` 或 CLI 內建預設選模型。ChatGPT 帳號登入下
預設選到的 `gpt-6-sol` 直接回 400「not supported when using Codex with a ChatGPT account」，
skill 的 exit-code gate 停下，使用者拿不到任何答案。pr-cycle-deep 的 review stage 早已 pin
`gpt-6-astra`，但 3rd-tools 的 codex-consult／codex-review／codex-cli 沒跟上——兩處各自維護，
於是漂移。本測試掃描 `plugins/` 下所有 SKILL.md 與 `.sh`，讓下一個新增的呼叫處無法再漏 pin。

`--enable web_search_cached` 已被 codex-cli 標為 deprecated（web search 預設開啟），一併禁止。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_DIR = REPO_ROOT / "plugins"

# 與 pr-cycle-deep 的 test_codex_scripts.py `_FRONTIER_MODEL` 同值：所有 review／consult／實作
# 呼叫共用同一個 frontier slug，任一處改了而其他處沒改，本測試會轉紅。
FRONTIER_MODEL = "gpt-6-astra"
# 唯一的例外：pr-cycle-deep stage 2 的 raw→JSON 萃取是機械轉換，刻意 pin 便宜的模型（issue #444）。
EXTRACT_MODEL = "gpt-5.6-luna"

# 只比對「以 codex exec 開頭的指令行」（可帶 `if !` 前綴），排除散文裡用反引號提到的 `codex exec`。
_COMMAND_LINE = re.compile(r"^\s*(?:if\s+!\s+)?codex exec\b")
_MODEL_FLAG = re.compile(r"(?:^|\s)-m\s+(\S+)")


def _codex_exec_lines() -> list[tuple[Path, int, str]]:
    """回傳 plugins/ 下所有 SKILL.md 與 .sh 中的 `codex exec` 指令行。"""
    found: list[tuple[Path, int, str]] = []
    candidates = sorted(PLUGINS_DIR.rglob("SKILL.md")) + sorted(PLUGINS_DIR.rglob("*.sh"))
    for path in candidates:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _COMMAND_LINE.match(line):
                found.append((path, lineno, line))
    return found


def _where(path: Path, lineno: int) -> str:
    return f"{path.relative_to(REPO_ROOT)}:{lineno}"


class TestCodexExecModelPin:
    def test_cxpin_vl_001_scan_finds_known_call_sites(self) -> None:
        """CXPIN-VL-001: 掃描必須命中已知的呼叫處，否則下面的斷言是對空集合的空洞 PASS。"""
        sites = {str(p.relative_to(REPO_ROOT)) for p, _, _ in _codex_exec_lines()}
        expected = {
            "plugins/3rd-tools/skills/codex-consult/SKILL.md",
            "plugins/3rd-tools/skills/codex-review/SKILL.md",
            "plugins/3rd-tools/skills/codex-cli/SKILL.md",
            "plugins/dev-cycle/skills/pr-cycle-deep/scripts/codex-r1-stage1.sh",
            "plugins/dev-cycle/skills/pr-cycle-deep/scripts/codex-r2.sh",
        }
        missing = expected - sites
        assert not missing, f"掃描沒有命中這些已知呼叫處（regex 失效？）：{sorted(missing)}"

    def test_cxpin_dt_001_every_codex_exec_pins_a_model(self) -> None:
        """CXPIN-DT-001: 每一行 codex exec 指令都帶 `-m <slug>`。"""
        unpinned = [
            _where(p, n) for p, n, line in _codex_exec_lines() if not _MODEL_FLAG.search(line)
        ]
        assert not unpinned, f"codex exec 未 pin 模型（ChatGPT 帳號下會回 400）：{unpinned}"

    def test_cxpin_dt_002_pinned_model_is_frontier_or_extract(self) -> None:
        """CXPIN-DT-002: pin 的 slug 只能是共用的 frontier 或 extract 模型，防止各處漂移。"""
        allowed = {FRONTIER_MODEL, EXTRACT_MODEL}
        drift = []
        for path, lineno, line in _codex_exec_lines():
            match = _MODEL_FLAG.search(line)
            if match and match.group(1) not in allowed:
                drift.append(f"{_where(path, lineno)} -> {match.group(1)}")
        assert not drift, f"codex exec pin 了非預期的模型：{drift}"

    def test_cxpin_dt_003_no_deprecated_web_search_cached(self) -> None:
        """CXPIN-DT-003: 不再使用已 deprecated 的 `--enable web_search_cached`。"""
        stale = [_where(p, n) for p, n, line in _codex_exec_lines() if "web_search_cached" in line]
        assert not stale, f"仍使用 deprecated 的 web_search_cached：{stale}"

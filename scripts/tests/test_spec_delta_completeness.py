"""MODIFIED delta 必須完整帶齊已部署 requirement 的所有 scenario。

**為什麼需要這條測試**（PR #347 mob review Consensus Critical）：spectra 的 MODIFIED 在
archive 時是**整段取代**——delta 少抄一個 scenario，archive 就把它從已部署 spec 刪掉。
兩位 reviewer 各自發現，其中一位在拋棄式 spectra 2.3.1 專案**實跑 archive** 證明：
archive 前 deployed 有 3 個 scenario、archive 後剩 2 個，**exit 0、無任何警告**，
而 `spectra validate` 同樣回報 valid。兩個既有 gate 都攔不到。

第一版修正只用 `$CLAUDE_JOB_DIR` 裡的一次性腳本驗證，沒有留下 committed 的回歸鎖——
re-review 指出這正是 rule 11「Pin it with a test, not a convention」要防的形狀，故改為此測試。
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHANGES_DIR = ROOT / "openspec" / "changes"
DEPLOYED_DIR = ROOT / "openspec" / "specs"

_REQ_RE = re.compile(r"^### Requirement: (.+)$", re.MULTILINE)
_SCENARIO_RE = re.compile(r"^#### Scenario: (.+)$", re.MULTILINE)
_MODIFIED_HEADING_RE = re.compile(r"^##\s+MODIFIED Requirements\s*$", re.MULTILINE)


def _requirements_with_scenarios(text: str) -> dict[str, list[str]]:
    """把 spec 內容切成 {requirement 標題: [scenario 標題, ...]}。"""
    out: dict[str, list[str]] = {}
    reqs = list(_REQ_RE.finditer(text))
    for i, m in enumerate(reqs):
        end = reqs[i + 1].start() if i + 1 < len(reqs) else len(text)
        body = text[m.start() : end]
        out[m.group(1).strip()] = [s.group(1).strip() for s in _SCENARIO_RE.finditer(body)]
    return out


def _modified_section(text: str) -> str | None:
    """回傳 `## MODIFIED Requirements` 到下一個 `## ` 之間的內容；沒有該段則 None。"""
    m = _MODIFIED_HEADING_RE.search(text)
    if m is None:
        return None
    rest = text[m.end() :]
    nxt = re.search(r"^##\s+(?!#)", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def _delta_spec_files() -> list[Path]:
    """所有未 archive 的 change 底下的 delta spec。"""
    if not CHANGES_DIR.is_dir():
        return []
    return sorted(p for p in CHANGES_DIR.glob("*/specs/*/spec.md") if "archive" not in p.parts)


def test_spec_dt_001_delta_specs_are_discoverable():
    """SPEC-DT-001: 至少找得到一份 delta spec——找不到代表 glob 錨點失效，本檔等於沒跑"""
    assert _delta_spec_files(), (
        f"在 {CHANGES_DIR} 下找不到任何 */specs/*/spec.md——錨點失效，"
        "後面的參數化測試會在空集合上空洞通過"
    )


@pytest.mark.parametrize(
    "delta_path", _delta_spec_files(), ids=lambda p: f"{p.parts[-4]}/{p.parts[-2]}"
)
def test_spec_dt_002_modified_requirements_carry_every_deployed_scenario(delta_path: Path):
    """SPEC-DT-002: 每個 MODIFIED requirement 都帶齊已部署 spec 的全部 scenario

    只檢查 `## MODIFIED Requirements` 段落——ADDED requirement 在已部署 spec 裡不存在，
    本來就沒有要抄的東西。
    """
    capability = delta_path.parts[-2]
    deployed_path = DEPLOYED_DIR / capability / "spec.md"
    if not deployed_path.is_file():
        pytest.skip(f"{capability} 尚未部署（全新 capability），無 MODIFIED 對照對象")

    modified = _modified_section(delta_path.read_text(encoding="utf-8"))
    if modified is None:
        pytest.skip(f"{delta_path.parts[-4]}/{capability} 沒有 MODIFIED Requirements 段落")

    deployed = _requirements_with_scenarios(deployed_path.read_text(encoding="utf-8"))
    delta = _requirements_with_scenarios(modified)

    for req, delta_scenarios in delta.items():
        assert req in deployed, (
            f"{delta_path}：MODIFIED 的 '{req}' 在已部署 spec 中不存在——"
            "標題打錯，或它其實該放在 ADDED 段落"
        )
        missing = [s for s in deployed[req] if s not in delta_scenarios]
        assert not missing, (
            f"{delta_path}：MODIFIED '{req}' 漏抄已部署 scenario {missing}。"
            "MODIFIED 在 archive 時是整段取代，這些 scenario 會被靜默刪除"
            "（spectra validate 與 archive 都不會報錯）。請逐字抄回。"
        )

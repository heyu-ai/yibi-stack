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


def _requirements_with_scenarios(text: str) -> dict[str, dict[str, str]]:
    """把 spec 切成 `{requirement 標題: {scenario 標題: 正規化後的 body}}`。

    **連 body 一起帶**，不是只帶標題：archive 是整段取代，一份「標題照抄、內文全空」的
    delta 同樣會把已部署內容覆蓋掉，而只比對標題的 gate 會全綠。
    （PR #347 Round 2 以 mutation 實證：刪光所有 body → SURVIVED。）
    """
    out: dict[str, dict[str, str]] = {}
    reqs = list(_REQ_RE.finditer(text))
    for i, m in enumerate(reqs):
        end = reqs[i + 1].start() if i + 1 < len(reqs) else len(text)
        req_body = text[m.start() : end]
        scenarios: dict[str, str] = {}
        hits = list(_SCENARIO_RE.finditer(req_body))
        for j, s in enumerate(hits):
            s_end = hits[j + 1].start() if j + 1 < len(hits) else len(req_body)
            raw = req_body[s.end() : s_end]
            scenarios[s.group(1).strip()] = " ".join(raw.split())
        out[m.group(1).strip()] = scenarios
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


def _comparable_deltas() -> list[Path]:
    """真的會進入比對的 delta：對應 capability 已部署，且有 MODIFIED 段落。"""
    out: list[Path] = []
    for p in _delta_spec_files():
        if not (DEPLOYED_DIR / p.parts[-2] / "spec.md").is_file():
            continue
        if _modified_section(p.read_text(encoding="utf-8")) is None:
            continue
        out.append(p)
    return out


def test_spec_dt_001_delta_specs_are_discoverable():
    """SPEC-DT-001: 至少找得到一份 delta spec——找不到代表 glob 錨點失效，本檔等於沒跑"""
    assert _delta_spec_files(), (
        f"在 {CHANGES_DIR} 下找不到任何 */specs/*/spec.md——錨點失效，"
        "後面的參數化測試會在空集合上空洞通過"
    )


def test_spec_dt_003_at_least_one_delta_actually_reaches_the_comparison():
    """SPEC-DT-003: 必須至少有一份 delta 真的被比對過，否則本檔是「全 skip 但全綠」

    DT-001 只擋「glob 掃不到檔案」這一種空洞。真正會發生的是另一種：檔案都在，但每個案例
    都 `pytest.skip`（capability 尚未部署、或沒有 MODIFIED 段落），於是本檔報告成功卻做了
    零次比對。本 change 被 `/spectra-archive` 移出 `openspec/changes/` 是它的正常生命終點，
    屆時這個鎖就會靜默失效——正是 rule 11「Pin it with a test」要防的形狀。
    （PR #347 Round 2：test-analyzer 以兩個存活突變實證。）

    此斷言失敗時的正確處置**不是**刪掉它，而是確認「本 repo 現在真的沒有任何 MODIFIED
    delta」——若是，改用 `pytest.skip` 並在訊息裡說明；若不是，代表偵測邏輯壞了。
    """
    comparable = _comparable_deltas()
    assert comparable, (
        f"在 {CHANGES_DIR} 下有 {len(_delta_spec_files())} 份 delta spec，但沒有任何一份"
        "會進入 MODIFIED 比對（capability 未部署，或沒有 MODIFIED Requirements 段落）。"
        "本檔目前是「全 skip 但全綠」，等於沒有保護力。"
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
        # body 也要看，不能只比標題：「標題照抄、內文全空」的 delta 一樣會在 archive 時把
        # 已部署內容覆蓋掉，而只比標題的 gate 全綠。
        #
        # 但**不能**要求 delta 逐字包含已部署文字——MODIFIED 的用意就是改動 scenario 內容
        # （本 change 正是刻意把「access_count ≥ 3」加上 parked 條件）。逐字比對等於禁止
        # MODIFIED 做它該做的事。因此只斷言「有實質內容」，這是能在不牴觸語意的前提下
        # 擋掉掏空的最強條件。剩下的「內容改對了嗎」屬人類 review 範圍，不是機械 gate。
        for scenario, deployed_body in deployed[req].items():
            if not deployed_body:
                continue
            assert len(delta_scenarios[scenario]) >= 20, (
                f"{delta_path}：MODIFIED '{req}' 的 scenario '{scenario}' 標題抄了但內文"
                f"幾乎是空的（{len(delta_scenarios[scenario])} 字元）。archive 會用 delta 的"
                "內容整段取代已部署版本，掏空等同刪除。"
            )

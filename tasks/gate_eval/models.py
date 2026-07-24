"""gate_eval 資料模型：conformance fixture、disposition oracle、判定與報告。

skill_eval 的形狀在此沿用但語意不同：那裡 judge 產出布林（是否觸發），這裡 judge
產出 disposition 列舉（blocking / deferred / outside-contract / non-blocking），或執行失敗。
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator


class Severity(StrEnum):
    """finding 的嚴重度（對映 SKILL.md RFC 2119 三級）。"""

    CRITICAL = "critical"
    IMPORTANT = "important"
    NIT = "nit"


class EvidenceForm(StrEnum):
    """Evidence 欄位的形式，只分「良構」與「缺」。

    「invalid（evidence 本身壞掉）」是執行期結果而非 fixture 輸入因子，故不在此列舉；
    矩陣以 valid / none 為鍵。
    """

    VALID = "valid"
    NONE = "none"


class Round(StrEnum):
    """審查輪次；R2 只 block Critical。"""

    R1 = "r1"
    R2 = "r2"


class ContractMapping(StrEnum):
    """Contract mapping gate 的四種輸入形狀。"""

    VALID = "valid"  # AC-<id> | repo baseline | unaccepted risk（可進 evidence gate）
    MISSING = "missing"  # 完全沒有 mapping
    INVALID = "invalid"  # mapping 格式錯誤
    OUT_OF_SCOPE = "out_of_scope"  # Non-goal / accepted boundary / Follow-up


class Disposition(StrEnum):
    """封閉列舉：一筆 finding 最終落在 final.md 的哪個 section。"""

    BLOCKING = "blocking"  # Consensus Critical / Important
    DEFERRED = "deferred"  # Deferred for lack of evidence
    OUTSIDE_CONTRACT = "outside-contract"  # Outside contract
    NON_BLOCKING = "non-blocking"  # Actionable NIT


# oracle 條目除四個真值外，另可標 "disputed"：runbook 未能無歧義定義的格子。
# fixture 的 expected_disposition 不得為 disputed（無法對未定義答案評分）。
DISPUTED = "disputed"


class Factors(BaseModel):
    """判定所依據的四因子。"""

    severity: Severity
    evidence: EvidenceForm
    round: Round
    contract_mapping: ContractMapping

    def key(self) -> tuple[str, str, str, str]:
        """穩定的查表鍵（供 oracle 對位）。"""
        return (
            str(self.severity),
            str(self.evidence),
            str(self.round),
            str(self.contract_mapping),
        )


class OracleEntry(BaseModel):
    """disposition 矩陣的單一格轉錄。"""

    severity: Severity
    evidence: EvidenceForm
    round: Round
    contract_mapping: ContractMapping
    disposition: Disposition | Literal["disputed"]
    note: str = ""  # disposition == disputed 時必填，指向 discoveries

    @model_validator(mode="after")
    def check_disputed_note(self) -> "OracleEntry":
        if self.disposition == DISPUTED and not self.note.strip():
            raise ValueError(
                "disputed 的 oracle 條目必須提供 note（指向 discoveries 說明歧義來源）"
            )
        return self

    def factors(self) -> Factors:
        return Factors(
            severity=self.severity,
            evidence=self.evidence,
            round=self.round,
            contract_mapping=self.contract_mapping,
        )


class DispositionOracle(BaseModel):
    """四因子到期望 disposition 的查表；重複因子組合視為轉錄錯誤。"""

    version: str = "1.0"
    entries: list[OracleEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_no_duplicate_factors(self) -> "DispositionOracle":
        seen: set[tuple[str, str, str, str]] = set()
        for entry in self.entries:
            k = entry.factors().key()
            if k in seen:
                raise ValueError(f"oracle 有重複的因子組合：{k}（轉錄矩陣時同一格出現兩次）")
            seen.add(k)
        return self

    def lookup(self, factors: Factors) -> OracleEntry | None:
        """回傳匹配的 oracle 條目；查無回 None（呼叫端須 fail loud，不得補預設）。"""
        target = factors.key()
        for entry in self.entries:
            if entry.factors().key() == target:
                return entry
        return None


class MutationDescriptor(BaseModel):
    """對 SKILL.md 的單一變更，用來驗證 fixture 確實掛在某句規則上。"""

    anchors: list[str] = Field(min_length=1)
    replacement: str = ""  # 空字串代表刪除該 anchor

    @model_validator(mode="after")
    def check_single_anchor(self) -> "MutationDescriptor":
        if len(self.anchors) != 1:
            raise ValueError(
                f"mutation 必須恰好綁定一個 anchor（收到 {len(self.anchors)} 個）；"
                "複合突變會因錯的理由變紅，產生假的『已驗證』"
            )
        if not self.anchors[0].strip():
            raise ValueError("mutation 的 anchor 不可為空字串")
        return self

    @property
    def anchor(self) -> str:
        return self.anchors[0]


class ConformanceFixture(BaseModel):
    """單一合成 finding 及其正解與綁定的 mutation。"""

    version: str = "1.0"
    id: str
    finding_text: str  # 合成的 R1 finding 內文
    review_contract: str = ""  # 生效的 Review Contract 片段
    factors: Factors
    expected_disposition: Disposition  # 封閉列舉，且不得為 disputed
    mutation: MutationDescriptor
    tier: str = ""  # 選填：structure | form-mismatch | closed-enum（供驗收對照組二挑選）

    @model_validator(mode="after")
    def check_fields(self) -> "ConformanceFixture":
        if not self.id.strip():
            raise ValueError("fixture 的 id 不可為空")
        if not self.finding_text.strip():
            raise ValueError(f"fixture {self.id} 的 finding_text 不可為空")
        return self


class FixtureSet(BaseModel):
    """一組 fixture；集合層驗證放行方向的涵蓋。"""

    fixtures: list[ConformanceFixture] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_balance(self) -> "FixtureSet":
        if not self.fixtures:
            raise ValueError("fixture 集合不可為空（空集合須 fail loud，不得回報全數通過）")
        ids = [fx.id for fx in self.fixtures]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"fixture id 重複：{', '.join(dupes)}")
        expected = {fx.expected_disposition for fx in self.fixtures}
        if Disposition.BLOCKING not in expected:
            raise ValueError(
                "fixture 集合必須至少含一個期望為 blocking 的案例；"
                "只有 deferred 的集合會被『永遠回答 deferred』的退化行為全數通過"
            )
        if Disposition.NON_BLOCKING not in expected:
            raise ValueError(
                "fixture 集合必須至少含一個期望為 non-blocking 的案例，"
                "否則過度攔截與正確攔截無法區分"
            )
        return self


class StabilityVerdict(StrEnum):
    """三值穩定度判定；UNSTABLE 不併入 NONCONFORMANT（兩者修法不同）。"""

    CONFORMANT = "conformant"
    NONCONFORMANT = "nonconformant"
    UNSTABLE = "unstable"


class RunOutcome(BaseModel):
    """單次判定：一個 disposition，或執行失敗（disposition 為 None 且帶 error）。"""

    disposition: Disposition | None = None
    error: str = ""

    @model_validator(mode="after")
    def check(self) -> "RunOutcome":
        if self.disposition is None and not self.error.strip():
            raise ValueError(
                "執行失敗的 RunOutcome 必須帶 error 訊息，不得與『判定為 deferred』混淆"
            )
        if self.disposition is not None and self.error.strip():
            raise ValueError("成功的 RunOutcome 不應同時帶 error")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def failed(self) -> bool:
        return self.disposition is None


class FixtureVerdict(BaseModel):
    """單一 fixture 跑 n 次後的三值判定與分佈。"""

    fixture_id: str
    expected: Disposition
    verdict: StabilityVerdict
    majority_disposition: Disposition | None = None
    total_runs: int
    execution_failures: int = 0
    reran: bool = False
    distribution: dict[str, int] = Field(default_factory=dict)


class Finding(BaseModel):
    """守恆檢查用的最小 finding 表示（標題 + 描述）。"""

    title: str
    description: str


class ConservationResult(BaseModel):
    """守恆檢查結果：每筆輸入 finding 是否在輸出中恰好一次且原文保留。"""

    ok: bool
    missing: list[str] = Field(default_factory=list)  # 輸出缺少的 finding 標題
    duplicated: list[str] = Field(default_factory=list)  # 輸出重複的標題
    altered: list[str] = Field(default_factory=list)  # 標題在但描述被改寫


class AlertClass(StrEnum):
    """紅燈分類；未分類預設計為假警報（歧義的預設方向偏向 sunset）。"""

    TRUE = "true"  # 真警報：surfaced 了 gate 行為的真實回歸
    FALSE = "false"  # 假警報：fixture/oracle 過時或 SKILL.md 合法改寫
    UNCLASSIFIED = "unclassified"  # 尚未分類；求值時併入 false


class PruneAction(StrEnum):
    """fixture 層 prune 建議。"""

    KEEP = "keep"  # 保留常規頻率
    DEMOTE = "demote"  # 保留但降至每季
    REMOVE = "remove"  # 移除該 fixture
    REPAIR = "repair"  # 全為假警報且第一次，修正一次


class FixtureWindowRecord(BaseModel):
    """單一 fixture 在一個檢視窗口內的狀態，供 prune 求值。"""

    fixture_id: str
    mutation_kills: bool  # 綁定的 mutation 是否仍能使其由 CONFORMANT 轉 NONCONFORMANT
    alerts: list[AlertClass] = Field(default_factory=list)  # 窗口內每次紅燈的分類
    false_alarm_repaired_once: bool = False  # 此 fixture 是否已因假警報修正過一次


class PruneRecommendation(BaseModel):
    """對單一 fixture 的 prune 建議。"""

    fixture_id: str
    action: PruneAction
    reason: str


class SunsetTrigger(StrEnum):
    """suite 層 sunset 觸發條件。"""

    NO_ALERTS_TWO_WINDOWS = "no_alerts_two_windows"
    NOISE_DOMINANT = "noise_dominant"
    SUPERSEDED_BY_CODE = "superseded_by_code"


class SuiteWindow(BaseModel):
    """單一檢視窗口的彙總（僅由已記錄在檢視 issue 的窗口建構；未記錄者不計入）。"""

    true_alerts: int = 0
    false_alarms: int = 0  # 含未分類（未分類預設併入假警報）
    any_fixture_alerted: bool = False


class SuiteSunsetResult(BaseModel):
    """suite 層 sunset 求值結果。"""

    due_for_removal: bool
    triggers: list[SunsetTrigger] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

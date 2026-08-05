#!/usr/bin/env python3
"""彙整 /pr-retro-hard 的 mob review 結果——本模組是決策所有者。

SKILL.md **不得** 重新實作此處的彙整規則，只記錄「呼叫哪個 script、哪些回傳必須停止、
哪些欄位交給人裁決」。防 drift 靠 `--explain-policy` 輸出與 SKILL.md 摘要表的雙向交叉檢查
（見 `tests/test_skill_contract.py`）。

刻意只用標準函式庫：本 script 隨 growth plugin 派送，執行環境不保證有本 repo 的虛擬環境。

退出碼：
  0  彙整完成，stdout 是 JSON 結果
  2  輸入不合契約（未知列舉值、缺必要欄位、JSON 解析失敗）
  1  執行期失敗（讀不到輸入檔）
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"

#: settling check 欄位為此字面值時，代表「未提供可定案的檢查」。
#: 這是**合法解析值**，不是缺欄位——效力依 voice 種類而異（見 Effect）。
NO_CHECK = "(none)"


class Classification(StrEnum):
    """finding 分類。封閉列舉，**無 catch-all 成員**。

    retro 結論的失效方式與 code review 的 Critical/Important/NIT 不同，故不沿用後者。
    """

    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    OVERCLAIMED = "OVERCLAIMED"
    MISATTRIBUTED = "MISATTRIBUTED"
    ALTERNATIVE_CAUSE = "ALTERNATIVE-CAUSE"
    AGREE = "AGREE"


class CheckState(StrEnum):
    """settling check 的五種執行狀態，彼此不可折疊。

    `UNABLE_TO_EXECUTE` **不等於** `REFUTED`：證據無效不代表宣稱不成立。
    """

    NOT_EXECUTED = "not_executed"
    UNABLE_TO_EXECUTE = "unable_to_execute"
    INCONCLUSIVE = "inconclusive"
    CONFIRMED = "confirmed"
    REFUTED = "refuted"


class VoiceKind(StrEnum):
    EXTERNAL = "external"
    ADVERSARIAL = "adversarial"


class Round(StrEnum):
    R1 = "r1"
    R2 = "r2"


class Source(StrEnum):
    USER_STATED = "user-stated"
    CROSS_MODEL = "cross-model"
    INFERRED = "inferred"


#: 除 AGREE 以外皆為異議。
DISSENT = frozenset(c for c in Classification if c is not Classification.AGREE)


class MalformedInput(Exception):
    """輸入不符契約。訊息必須指名違規的 finding，不得只說「格式錯誤」。"""


@dataclass(frozen=True)
class Finding:
    id: str
    voice: str
    voice_kind: VoiceKind
    round: Round
    target: str
    classification: Classification
    settling_check: str
    statement: str
    draft_digest: str
    check_state: CheckState = CheckState.NOT_EXECUTED

    @property
    def has_settling_check(self) -> bool:
        return self.settling_check != NO_CHECK

    @property
    def is_dissent(self) -> bool:
        return self.classification in DISSENT


@dataclass(frozen=True)
class AggregationInput:
    draft_digest: str
    packet_digest: str
    original_confidence: int
    original_source: Source
    findings: tuple[Finding, ...]
    enable_demotion: bool = False


@dataclass
class FindingOutcome:
    finding_id: str
    target: str
    voice: str
    voice_kind: VoiceKind
    round: Round
    classification: Classification
    check_state: CheckState
    effect: str
    reason: str


class Effect(StrEnum):
    """一筆 finding 對彙整結果的實際效力。封閉列舉。

    每個成員都必須在 SKILL.md 的摘要表出現，且 SKILL.md 提到的每個 outcome 都必須是此列舉
    的成員——雙向由 `tests/test_skill_contract.py` 斷言。
    """

    #: 草稿語意已變更，此 finding 不套用。
    STALE = "stale"
    #: 首輪交白卷的 voice 在交叉輪沒有共識資格。
    NO_CONSENSUS_ELIGIBILITY = "no_consensus_eligibility"
    #: 交叉輪只能反證 / 降級 / 撤回 / 補 settling check，不新增獨立票。
    CROSS_ROUND_REFUTATION = "cross_round_refutation"
    #: 明確無異議。永不抬升任何評分。
    RECORDED_ONLY = "recorded_only"
    #: 針對「使用者自己說過的話」的異議：另行記錄，不降其 confidence 與 source。
    RECORDED_AGAINST_USER_STATED = "recorded_against_user_stated"
    #: 對抗 voice 未附 settling check：非作用性註解，仍呈現給人。
    NON_ACTIONABLE_COMMENTARY = "non_actionable_commentary"
    #: 對抗 voice 附了 settling check：假說，仍不計票，須由 lead 實跑該檢查。
    ADVERSARIAL_HYPOTHESIS = "adversarial_hypothesis"
    #: 外部 voice 未附 settling check：上限為未決，不產出降級建議。
    UNRESOLVED = "unresolved"
    #: 外部 voice 首輪異議且附 settling check：可降低 confidence。
    ACTIONABLE = "actionable"


#: 成立共識時計入的效力（對抗 voice 依建構不會落在這兩者）。
CONSENSUS_BEARING = frozenset({Effect.ACTIONABLE, Effect.UNRESOLVED})


@dataclass
class AggregationResult:
    confidence: int
    source: Source
    outcomes: list[FindingOutcome] = field(default_factory=list)
    consensus: dict[str, list[str]] = field(default_factory=dict)
    demotion_recommendations: list[str] = field(default_factory=list)
    demotion_applied: bool = False
    stale_finding_ids: list[str] = field(default_factory=list)


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise MalformedInput(f"[FAIL] {where} 缺少必要欄位 '{key}'")
    value = mapping[key]
    if isinstance(value, str) and not value.strip():
        raise MalformedInput(f"[FAIL] {where} 的 '{key}' 是空字串")
    return value


def _parse_enum(enum_cls: type[StrEnum], raw: Any, key: str, where: str) -> Any:
    try:
        return enum_cls(raw)
    except ValueError as exc:
        allowed = ", ".join(m.value for m in enum_cls)
        raise MalformedInput(
            f"[FAIL] {where} 的 '{key}' 值 {raw!r} 不在封閉列舉內；允許值：{allowed}。"
            "此列舉無 catch-all 成員，不套用預設值。"
        ) from exc


def parse_finding(raw: Any, index: int) -> Finding:
    if not isinstance(raw, dict):
        raise MalformedInput(f"[FAIL] findings[{index}] 不是物件")
    ident = raw.get("id")
    where = (
        f"findings[{index}]" if not isinstance(ident, str) or not ident else f"finding '{ident}'"
    )
    return Finding(
        id=str(_require(raw, "id", where)),
        voice=str(_require(raw, "voice", where)),
        voice_kind=_parse_enum(VoiceKind, _require(raw, "voice_kind", where), "voice_kind", where),
        round=_parse_enum(Round, _require(raw, "round", where), "round", where),
        target=str(_require(raw, "target", where)),
        classification=_parse_enum(
            Classification, _require(raw, "classification", where), "classification", where
        ),
        settling_check=str(_require(raw, "settling_check", where)),
        statement=str(_require(raw, "statement", where)),
        draft_digest=str(_require(raw, "draft_digest", where)),
        check_state=_parse_enum(
            CheckState, raw.get("check_state", CheckState.NOT_EXECUTED.value), "check_state", where
        ),
    )


def parse_input(raw: Any) -> AggregationInput:
    if not isinstance(raw, dict):
        raise MalformedInput("[FAIL] 輸入頂層不是物件")
    version = _require(raw, "version", "input")
    if version != SCHEMA_VERSION:
        raise MalformedInput(
            f"[FAIL] 不支援的 version {version!r}；本模組只接受 {SCHEMA_VERSION!r}"
        )
    confidence = _require(raw, "original_confidence", "input")
    if not isinstance(confidence, int) or isinstance(confidence, bool) or not 1 <= confidence <= 10:
        raise MalformedInput(f"[FAIL] original_confidence 必須是 1-10 的整數，收到 {confidence!r}")
    findings_raw = _require(raw, "findings", "input")
    if not isinstance(findings_raw, list):
        raise MalformedInput("[FAIL] findings 必須是陣列")
    seen: set[str] = set()
    findings: list[Finding] = []
    for index, item in enumerate(findings_raw):
        finding = parse_finding(item, index)
        if finding.id in seen:
            raise MalformedInput(f"[FAIL] finding id 重複：'{finding.id}'")
        seen.add(finding.id)
        findings.append(finding)
    enable = raw.get("enable_demotion", False)
    if not isinstance(enable, bool):
        raise MalformedInput(f"[FAIL] enable_demotion 必須是布林值，收到 {enable!r}")
    return AggregationInput(
        draft_digest=str(_require(raw, "draft_digest", "input")),
        packet_digest=str(_require(raw, "packet_digest", "input")),
        original_confidence=confidence,
        original_source=_parse_enum(
            Source, _require(raw, "original_source", "input"), "original_source", "input"
        ),
        findings=tuple(findings),
        enable_demotion=enable,
    )


def _classify_effect(
    finding: Finding,
    *,
    draft_digest: str,
    source: Source,
    r1_voices_with_findings: frozenset[str],
) -> tuple[Effect, str]:
    """決定單筆 finding 的效力。判定順序即優先序，先命中者勝。"""
    if finding.draft_digest != draft_digest:
        return Effect.STALE, "此 finding 產出時的草稿 digest 與現行草稿不符，不套用"

    if finding.round is Round.R2:
        if finding.voice not in r1_voices_with_findings:
            return (
                Effect.NO_CONSENSUS_ELIGIBILITY,
                "該 voice 首輪零 finding，在交叉輪沒有共識資格"
                "（看過他家結果後的附和是錨定，不是佐證）",
            )
        return (
            Effect.CROSS_ROUND_REFUTATION,
            "交叉輪只能反證 / 降級 / 撤回 / 補 settling check，不新增獨立票",
        )

    if finding.classification is Classification.AGREE:
        return Effect.RECORDED_ONLY, "明確無異議；一致永不抬升 confidence 或改寫 source"

    if finding.voice_kind is VoiceKind.ADVERSARIAL:
        if not finding.has_settling_check:
            return (
                Effect.NON_ACTIONABLE_COMMENTARY,
                "對抗 voice 未附可定案的檢查；仍呈現給人，但不影響評分、tier 與草稿",
            )
        return (
            Effect.ADVERSARIAL_HYPOTHESIS,
            "對抗 voice 依建構單邊，不計票；此假說須由 lead 實跑其 settling check 後才採信",
        )

    if source is Source.USER_STATED:
        return (
            Effect.RECORDED_AGAINST_USER_STATED,
            "標的的 source 是使用者陳述；異議另行記錄，不降其 confidence、不改寫其 source",
        )

    if not finding.has_settling_check:
        return Effect.UNRESOLVED, "外部 voice 未附可定案的檢查；上限為未決，不產出降級建議"

    return Effect.ACTIONABLE, "外部 voice 首輪異議且附可定案的檢查"


def aggregate(data: AggregationInput) -> AggregationResult:
    """純函式彙整。同一輸入永遠得到同一輸出，與 voice / finding 供入順序無關。"""
    r1_voices_with_findings = frozenset(
        f.voice
        for f in data.findings
        if f.round is Round.R1 and f.draft_digest == data.draft_digest
    )

    outcomes: list[FindingOutcome] = []
    for finding in data.findings:
        effect, reason = _classify_effect(
            finding,
            draft_digest=data.draft_digest,
            source=data.original_source,
            r1_voices_with_findings=r1_voices_with_findings,
        )
        outcomes.append(
            FindingOutcome(
                finding_id=finding.id,
                target=finding.target,
                voice=finding.voice,
                voice_kind=finding.voice_kind,
                round=finding.round,
                classification=finding.classification,
                check_state=finding.check_state,
                effect=effect.value,
                reason=reason,
            )
        )

    effect_of = {o.finding_id: Effect(o.effect) for o in outcomes}

    # 共識只由獨立首輪的外部異議建立。
    #
    # 這裡刻意不再加一道 `finding.is_dissent`：`_classify_effect` 的 AGREE 分支在
    # actionable / unresolved 之前，故 AGREE 依建構不可能落入 CONSENSUS_BEARING。多寫一道
    # 會遮蔽「AGREE 分支被移除」這個突變，讓它存活而看不出來。該不變量改由
    # AGG-DT-014 直接斷言（AGREE 永不得到 ACTIONABLE 或 UNRESOLVED）。
    consensus: dict[str, set[str]] = {}
    for finding in data.findings:
        if effect_of[finding.id] in CONSENSUS_BEARING:
            consensus.setdefault(finding.target, set()).add(finding.voice)

    # confidence 只能被降，且降幅是「有多少個不同的外部 voice 提出可作用異議」的函式——
    # 不是累加，故重跑同一集合結果相同。
    lowering_voices = {f.voice for f in data.findings if effect_of[f.id] is Effect.ACTIONABLE}
    confidence = max(1, data.original_confidence - len(lowering_voices))

    # 只有「證據不支持」且其 settling check **已執行且確認** 才產出降級建議。
    # 單純的分類標籤不足以觸發機械動作——未執行的標籤是價值判斷，屬人的裁決範圍。
    recommendations = sorted(
        {
            f.target
            for f in data.findings
            if effect_of[f.id] is Effect.ACTIONABLE
            and f.classification is Classification.UNSUPPORTED
            and f.check_state is CheckState.CONFIRMED
        }
    )

    return AggregationResult(
        confidence=confidence,
        # source 永不被彙整改寫：三個 voice 讀同一份草稿、同一套 prompt，依建構相關而非
        # 獨立，故其一致不構成 cross-model 證據。
        source=data.original_source,
        outcomes=sorted(outcomes, key=lambda o: (o.target, o.voice, o.finding_id)),
        consensus={t: sorted(v) for t, v in sorted(consensus.items())},
        demotion_recommendations=recommendations,
        demotion_applied=bool(recommendations) and data.enable_demotion,
        stale_finding_ids=sorted(f.id for f in data.findings if effect_of[f.id] is Effect.STALE),
    )


def result_to_dict(result: AggregationResult) -> dict[str, Any]:
    return {
        "confidence": result.confidence,
        "source": result.source.value,
        "consensus": result.consensus,
        "demotion_recommendations": result.demotion_recommendations,
        "demotion_applied": result.demotion_applied,
        "stale_finding_ids": result.stale_finding_ids,
        "outcomes": [
            {
                "finding_id": o.finding_id,
                "target": o.target,
                "voice": o.voice,
                "voice_kind": o.voice_kind.value,
                "round": o.round.value,
                "classification": o.classification.value,
                "check_state": o.check_state.value,
                "effect": o.effect,
                "reason": o.reason,
            }
            for o in result.outcomes
        ],
    }


#: 每個 Effect 的一行語意。這份 mapping 是 SKILL.md 摘要表的**唯一來源**，
#: 由 `--explain-policy` 輸出、由 contract test 雙向比對。
EFFECT_MEANING: dict[str, str] = {
    Effect.STALE.value: "草稿語意已變更，此 finding 不套用",
    Effect.NO_CONSENSUS_ELIGIBILITY.value: "首輪零 finding 的 voice 在交叉輪無共識資格",
    Effect.CROSS_ROUND_REFUTATION.value: "交叉輪僅反證 / 降級 / 撤回 / 補檢查，不新增獨立票",
    Effect.RECORDED_ONLY.value: "明確無異議；不抬升任何評分",
    Effect.RECORDED_AGAINST_USER_STATED.value: "針對使用者陳述的異議另行記錄，不降其評分",
    Effect.NON_ACTIONABLE_COMMENTARY.value: "對抗 voice 無檢查：僅呈現，零效力",
    Effect.ADVERSARIAL_HYPOTHESIS.value: "對抗 voice 有檢查：不計票，須 lead 實跑後採信",
    Effect.UNRESOLVED.value: "外部 voice 無檢查：上限未決，不產出降級建議",
    Effect.ACTIONABLE.value: "外部 voice 首輪異議且有檢查：可降低 confidence",
}


def explain_policy() -> dict[str, Any]:
    """輸出本模組能產生的所有 outcome，供 SKILL.md 摘要表雙向交叉檢查。"""
    return {
        "version": SCHEMA_VERSION,
        "effects": EFFECT_MEANING,
        "classifications": [c.value for c in Classification],
        "check_states": [s.value for s in CheckState],
        "sources": [s.value for s in Source],
        "invariants": [
            "agreement never raises confidence and never rewrites source",
            "consensus is established only by the independent first round",
            "adversarial findings never count toward consensus",
            "demotion requires classification UNSUPPORTED and check_state confirmed",
            "demotion is a recommendation consumed by the existing evidence gate",
            "draft items are annotated, never removed",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="彙整 pr-retro-hard 的 mob review 結果")
    parser.add_argument("--input", type=Path, help="輸入 JSON 檔路徑")
    parser.add_argument(
        "--explain-policy",
        action="store_true",
        help="輸出本模組能產生的 outcome 列舉，供 SKILL.md 摘要表雙向交叉檢查",
    )
    args = parser.parse_args(argv)

    if args.explain_policy:
        json.dump(explain_policy(), sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    if args.input is None:
        print("[FAIL] 需要 --input <file> 或 --explain-policy", file=sys.stderr)
        return 2

    try:
        raw_text = args.input.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[FAIL] 無法讀取輸入檔 {args.input}：{exc}", file=sys.stderr)
        return 1

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        print(f"[FAIL] 輸入不是合法 JSON：{exc}", file=sys.stderr)
        return 2

    try:
        parsed = parse_input(payload)
    except MalformedInput as exc:
        print(str(exc), file=sys.stderr)
        return 2

    result = aggregate(parsed)
    json.dump(result_to_dict(result), sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

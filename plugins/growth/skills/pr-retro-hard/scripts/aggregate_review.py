#!/usr/bin/env python3
"""彙整 /pr-retro-hard 的 mob review 結果——本模組是決策所有者。

SKILL.md **不得** 重新實作此處的彙整規則，只記錄「呼叫哪個 script、哪些回傳必須停止、
哪些欄位交給人裁決」。防 drift 靠 `--explain-policy` 輸出與 SKILL.md 摘要表的雙向交叉檢查
（見 `tests/test_skill_contract.py`）。

刻意只用標準函式庫：本 script 隨 growth plugin 派送，執行環境不保證有本 repo 的虛擬環境。

退出碼：
  0  彙整完成，stdout 是 JSON 結果
  2  輸入不合契約（未知列舉值、缺必要欄位、型別錯誤、JSON 解析失敗）
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
    `REFUTED` 意味著檢查真的跑過、宣稱不成立——它不得改變 confidence、不得計入 consensus、
    不得產出降級建議，效力上等同「未提供檢查」，而非「已確認」。
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


class MalformedInput(Exception):
    """輸入不符契約。訊息必須指名違規的 finding 或欄位，不得只說「格式錯誤」。"""


@dataclass(frozen=True)
class LessonScore:
    """一個 lesson target 的 confidence/source。輸入用來承接 original 值，輸出用來承接
    彙整後的值——欄位同形但語意不同，由呼叫端依上下文解讀。
    """

    confidence: int
    source: Source


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
    packet_digest: str
    check_state: CheckState = CheckState.NOT_EXECUTED

    @property
    def has_settling_check(self) -> bool:
        return self.settling_check != NO_CHECK


@dataclass(frozen=True)
class AggregationInput:
    draft_digest: str
    packet_digest: str
    lessons: dict[str, LessonScore]
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

    #: 草稿或審查包語意已變更，此 finding 不套用。
    STALE = "stale"
    #: 該 voice 對此 target 在首輪未曾發言，交叉輪不得為此 (target, voice) 建立新票。
    NO_CONSENSUS_ELIGIBILITY = "no_consensus_eligibility"
    #: 首輪 finding 被同一 (target, voice) 的合格交叉輪 finding 覆蓋，本身不再governing。
    SUPERSEDED_BY_R2 = "superseded_by_r2"
    #: 明確無異議。永遠不抬升任何評分。
    RECORDED_ONLY = "recorded_only"
    #: 針對「使用者自己說過的話」的異議：另行記錄，不降其 confidence 與 source。
    RECORDED_AGAINST_USER_STATED = "recorded_against_user_stated"
    #: 對抗 voice 未附 settling check：非作用性註解，仍呈現但不影響評分。
    NON_ACTIONABLE_COMMENTARY = "non_actionable_commentary"
    #: 對抗 voice 附了 settling check：假說，仍不計票，須由 lead 實跑該檢查。
    ADVERSARIAL_HYPOTHESIS = "adversarial_hypothesis"
    #: 外部 voice 未附 settling check，或 check 尚未確認：上限為未決，不產出降級建議。
    UNRESOLVED = "unresolved"
    #: settling check 已執行且結果為 refuted：宣稱不成立，記錄但零效力——與未附檢查同效力。
    NOT_REPRODUCED = "not_reproduced"
    #: 外部 voice 首輪（或合格交叉輪覆蓋）異議，且 settling check 已執行且確認。
    ACTIONABLE = "actionable"


#: 成立共識、且能降低 confidence 的效力。
CONSENSUS_BEARING = frozenset({Effect.ACTIONABLE, Effect.UNRESOLVED})


@dataclass
class AggregationResult:
    lessons: dict[str, LessonScore] = field(default_factory=dict)
    outcomes: list[FindingOutcome] = field(default_factory=list)
    consensus: dict[str, list[str]] = field(default_factory=dict)
    demotion_recommendations: list[str] = field(default_factory=list)
    demotion_applied: bool = False
    stale_finding_ids: list[str] = field(default_factory=list)


def _require_key(mapping: dict[str, Any], key: str, where: str) -> Any:
    """要求 key 存在，回傳其原始值——不對值的型別做任何假設。

    給非字串欄位（陣列、物件、布林）用；型別檢查由呼叫端自己做，因為每個欄位的正確型別
    都不同。**不要**把這個和 `_require_str` 搞混——這正是先前 null-coercion 那個問題的
    根源：一個函式若同時肩負「key 存在」與「值是非空字串」兩種語意，呼叫端會在只需要前者
    的地方誤用後者（或反之），而型別不合的值就會靜默通過。
    """
    if key not in mapping:
        raise MalformedInput(f"[FAIL] {where} 缺少必要欄位 '{key}'")
    return mapping[key]


def _require_str(mapping: dict[str, Any], key: str, where: str) -> str:
    """要求 key 存在且值是非空字串。`None`（JSON null）與其他非字串型別一律拒絕——

    `isinstance(value, str)` 為 False 時直接報錯，不落入「跳過空字串檢查、原樣回傳」的
    路徑。這正是修復 null-coercion（`str(None) == "None"` 被當成合法字串放行）的地方。
    """
    value = _require_key(mapping, key, where)
    if not isinstance(value, str):
        raise MalformedInput(
            f"[FAIL] {where} 的 '{key}' 必須是字串，收到 {type(value).__name__}：{value!r}"
        )
    if not value.strip():
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
        id=_require_str(raw, "id", where),
        voice=_require_str(raw, "voice", where),
        voice_kind=_parse_enum(
            VoiceKind, _require_str(raw, "voice_kind", where), "voice_kind", where
        ),
        round=_parse_enum(Round, _require_str(raw, "round", where), "round", where),
        target=_require_str(raw, "target", where),
        classification=_parse_enum(
            Classification, _require_str(raw, "classification", where), "classification", where
        ),
        settling_check=_require_str(raw, "settling_check", where),
        statement=_require_str(raw, "statement", where),
        draft_digest=_require_str(raw, "draft_digest", where),
        packet_digest=_require_str(raw, "packet_digest", where),
        check_state=_parse_enum(
            CheckState, raw.get("check_state", CheckState.NOT_EXECUTED.value), "check_state", where
        ),
    )


def _parse_lesson_score(raw: Any, key: str) -> LessonScore:
    if not isinstance(raw, dict):
        raise MalformedInput(f"[FAIL] lessons['{key}'] 不是物件")
    where = f"lessons['{key}']"
    confidence = raw.get("original_confidence")
    if not isinstance(confidence, int) or isinstance(confidence, bool) or not 1 <= confidence <= 10:
        raise MalformedInput(
            f"[FAIL] {where} 的 'original_confidence' 必須是 1-10 的整數，收到 {confidence!r}"
        )
    source = _parse_enum(
        Source, _require_str(raw, "original_source", where), "original_source", where
    )
    return LessonScore(confidence=confidence, source=source)


def parse_input(raw: Any) -> AggregationInput:
    if not isinstance(raw, dict):
        raise MalformedInput("[FAIL] 輸入頂層不是物件")
    version = _require_str(raw, "version", "input")
    if version != SCHEMA_VERSION:
        raise MalformedInput(
            f"[FAIL] 不支援的 version {version!r}；本模組只接受 {SCHEMA_VERSION!r}"
        )
    # findings 是陣列，用 _require_key（只驗 key 存在）而非 _require_str（會誤判非字串型別）。
    findings_raw = _require_key(raw, "findings", "input")
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

    lessons_raw = raw.get("lessons", {})
    if not isinstance(lessons_raw, dict):
        raise MalformedInput("[FAIL] lessons 必須是物件")
    lessons = {key: _parse_lesson_score(value, key) for key, value in lessons_raw.items()}

    enable = raw.get("enable_demotion", False)
    if not isinstance(enable, bool):
        raise MalformedInput(f"[FAIL] enable_demotion 必須是布林值，收到 {enable!r}")
    return AggregationInput(
        draft_digest=_require_str(raw, "draft_digest", "input"),
        packet_digest=_require_str(raw, "packet_digest", "input"),
        lessons=lessons,
        findings=tuple(findings),
        enable_demotion=enable,
    )


def _intrinsic_effect(finding: Finding, lessons: dict[str, LessonScore]) -> tuple[Effect, str]:
    """判定一筆 finding 若它是其 (target, voice) 的 governing finding，效力該是什麼。

    只看 finding 自身內容（分類、voice 種類、check 狀態）與其 target 的 lesson 設定，
    不涉及 round 或 supersession——那部分由呼叫端（aggregate）依上下文另行判定。
    """
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

    lesson = lessons.get(finding.target)
    if lesson is not None and lesson.source is Source.USER_STATED:
        return (
            Effect.RECORDED_AGAINST_USER_STATED,
            "標的的 source 是使用者陳述；異議另行記錄，不降其 confidence、不改寫其 source",
        )

    if not finding.has_settling_check:
        return Effect.UNRESOLVED, "外部 voice 未附可定案的檢查；上限為未決，不產出降級建議"

    if finding.check_state is CheckState.REFUTED:
        return (
            Effect.NOT_REPRODUCED,
            "settling check 已執行且宣稱不成立；記錄但零效力，與未附檢查同效力",
        )

    if finding.check_state is not CheckState.CONFIRMED:
        return (
            Effect.UNRESOLVED,
            "settling check 尚未執行或無定論；上限為未決，不產出降級建議、不影響評分",
        )

    return Effect.ACTIONABLE, "外部 voice 異議且其 settling check 已執行且確認"


def aggregate(data: AggregationInput) -> AggregationResult:
    """純函式彙整。同一輸入永遠得到同一輸出，與 voice / finding 供入順序無關。

    分三層判定，順序即優先序：
    1. 過期（草稿或審查包語意已變更）
    2. round / supersession（決定哪個 finding 是其 (target, voice) 的 governing finding）
    3. intrinsic effect（governing finding 本身的內容決定效力）
    """
    live = [
        f
        for f in data.findings
        if f.draft_digest == data.draft_digest and f.packet_digest == data.packet_digest
    ]
    live_ids = {f.id for f in live}

    # 首輪「已發言」的 (target, voice) 組合——交叉輪只能對這些組合覆蓋，不能新開。
    r1_by_key: dict[tuple[str, str], Finding] = {}
    for f in live:
        if f.round is Round.R1:
            r1_by_key[(f.target, f.voice)] = f

    # governing finding：交叉輪對「已在首輪發言」的 (target, voice) 覆蓋首輪版本；
    # 其餘一律以首輪版本為準。這不是新增獨立票——(target, voice) 這個組合本身
    # 已經在首輪建立，交叉輪只是更新它的證據基礎。
    governing_by_key: dict[tuple[str, str], Finding] = dict(r1_by_key)
    for f in live:
        if f.round is Round.R2 and (f.target, f.voice) in r1_by_key:
            governing_by_key[(f.target, f.voice)] = f
    governing_ids = {f.id for f in governing_by_key.values()}

    outcomes: list[FindingOutcome] = []
    effect_of: dict[str, Effect] = {}
    for f in data.findings:
        if f.id not in live_ids:
            effect, reason = (
                Effect.STALE,
                "此 finding 產出時的草稿或審查包 digest 與現行不符，不套用",
            )
        elif f.round is Round.R2 and (f.target, f.voice) not in r1_by_key:
            effect, reason = (
                Effect.NO_CONSENSUS_ELIGIBILITY,
                "該 voice 對此標的在首輪未曾發言，交叉輪不得為此 (target, voice) 建立新票"
                "（看過他家結果後才對新標的表態是錨定，不是佐證）",
            )
        elif f.id not in governing_ids:
            effect, reason = (
                Effect.SUPERSEDED_BY_R2,
                "此首輪 finding 已被同一 (target, voice) 的合格交叉輪 finding 覆蓋，"
                "評分依交叉輪版本計算",
            )
        else:
            effect, reason = _intrinsic_effect(f, data.lessons)

        effect_of[f.id] = effect
        outcomes.append(
            FindingOutcome(
                finding_id=f.id,
                target=f.target,
                voice=f.voice,
                voice_kind=f.voice_kind,
                round=f.round,
                classification=f.classification,
                check_state=f.check_state,
                effect=effect.value,
                reason=reason,
            )
        )

    governing = list(governing_by_key.values())

    # 共識只由 governing finding 中落在 CONSENSUS_BEARING 的異議建立，依 target 分組。
    consensus: dict[str, set[str]] = {}
    for f in governing:
        if effect_of[f.id] in CONSENSUS_BEARING:
            consensus.setdefault(f.target, set()).add(f.voice)

    # confidence 扣分依 target 獨立計算：每個 target 的扣分是「有多少個不同外部 voice
    # 對該 target 提出 ACTIONABLE 異議」，不是全域計數、不是累加 finding 數。
    lowering_voices_by_target: dict[str, set[str]] = {}
    for f in governing:
        if effect_of[f.id] is Effect.ACTIONABLE:
            lowering_voices_by_target.setdefault(f.target, set()).add(f.voice)

    result_lessons: dict[str, LessonScore] = {}
    for target, original in data.lessons.items():
        lowered = len(lowering_voices_by_target.get(target, set()))
        result_lessons[target] = LessonScore(
            confidence=max(1, original.confidence - lowered),
            # source 永不被彙整改寫：三個 voice 讀同一份草稿、同一套 prompt，依建構相關而非
            # 獨立，故其一致不構成 cross-model 證據。
            source=original.source,
        )

    # 只有「證據不支持」且其 settling check **已執行且確認** 才產出降級建議。
    # 單純的分類標籤不足以觸發機械動作——未執行或反駁過的標籤是價值判斷，屬人的裁決範圍。
    #
    # 這裡刻意不再加一道 `f.check_state is CheckState.CONFIRMED`：`_intrinsic_effect` 只有
    # 通過兩道 check_state 關卡後才會回傳 ACTIONABLE，故 `effect_of[f.id] is Effect.ACTIONABLE`
    # 本身已蘊含 `check_state == CONFIRMED`。多寫一道會遮蔽「check_state 關卡被移除」這個突變，
    # 讓它存活而看不出來（與本檔 aggregate() 早先移除 `f.is_dissent` 冗餘述詞是同一類問題）。
    # 該不變量改由 AGG-DT-066 直接斷言。
    recommendations = sorted(
        {
            f.target
            for f in governing
            if effect_of[f.id] is Effect.ACTIONABLE
            and f.classification is Classification.UNSUPPORTED
        }
    )

    return AggregationResult(
        lessons=result_lessons,
        outcomes=sorted(outcomes, key=lambda o: (o.target, o.voice, o.finding_id)),
        consensus={t: sorted(v) for t, v in sorted(consensus.items())},
        demotion_recommendations=recommendations,
        demotion_applied=bool(recommendations) and data.enable_demotion,
        stale_finding_ids=sorted(f.id for f in data.findings if f.id not in live_ids),
    )


def result_to_dict(result: AggregationResult) -> dict[str, Any]:
    return {
        "lessons": {
            key: {"confidence": v.confidence, "source": v.source.value}
            for key, v in sorted(result.lessons.items())
        },
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
    Effect.STALE.value: "草稿或審查包語意已變更，此 finding 不套用",
    Effect.NO_CONSENSUS_ELIGIBILITY.value: "該 voice 對此標的在首輪未曾發言，交叉輪不得新開票",
    Effect.SUPERSEDED_BY_R2.value: "首輪 finding 已被同一 (target, voice) 的交叉輪覆蓋",
    Effect.RECORDED_ONLY.value: "明確無異議；不抬升任何評分",
    Effect.RECORDED_AGAINST_USER_STATED.value: "針對使用者陳述的異議另行記錄，不降其評分",
    Effect.NON_ACTIONABLE_COMMENTARY.value: "對抗 voice 無檢查：僅呈現，零效力",
    Effect.ADVERSARIAL_HYPOTHESIS.value: "對抗 voice 有檢查：不計票，須 lead 實跑後採信",
    Effect.UNRESOLVED.value: "無檢查或檢查未確認：上限未決，不產出降級建議、不影響評分",
    Effect.NOT_REPRODUCED.value: "檢查已執行且宣稱不成立：記錄但零效力",
    Effect.ACTIONABLE.value: "異議且其檢查已執行且確認：可降低該 target 的 confidence",
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
            "consensus is established only by the independent first round, per (target, voice)",
            "adversarial findings never count toward consensus",
            "a refuted or unconfirmed check has the same zero effect as no check at all",
            "each lesson target is scored independently; a dissent never moves another target's"
            " score",
            "demotion requires classification UNSUPPORTED and check_state confirmed",
            "demotion is a recommendation consumed by the existing evidence gate",
            "draft items are annotated, never removed",
            "an r2 finding can supersede its own (target, voice) r1 finding, never add a new vote",
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

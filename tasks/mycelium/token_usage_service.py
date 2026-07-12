"""Token 用量 / 成本估算服務：從 Claude Code session transcript 推算 token 用量與成本。

計算範圍是「整個 session」（從 session 開始到呼叫當下），包含主 transcript 與所有
subagent（Task/Agent tool）transcript。這是 best-effort 估算，不是精確計費：
- 無法可靠取得「自己的 session id/transcript path」（未以 hook 身分執行時，
  Claude Code 不會把這些資訊透過環境變數提供），只能用「cwd 相符 + mtime 最新」
  的啟發式去猜；猜不準時回傳 ambiguous/unavailable，不硬猜一個可能錯的結果。
- subagent 層級的 effort level 不會持久寫進 transcript，因此只能回報主 session 的
  `$CLAUDE_EFFORT`，無法逐一列出每個 subagent 用了什麼 effort。
- 定價表為 module-level 常數快照（來源見下方），遇到表中沒有的 model id 時把
  status 標成 computed_partial 並在 warning 列出未定價的 model，避免靜默低估成本。
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # nosec B404
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# 定價來源：claude-api skill（鏡像 Anthropic 官方定價頁 anthropic.com/pricing）。
# 最後確認日期：2026-07-11。$/1M tokens：(input, output)。
# 遇到表中沒有的 model id 時不要用最接近的價格硬猜——交給呼叫端標記 computed_partial。
_PRICING_USD_PER_1M: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10.00, 50.00),
    "claude-mythos-5": (10.00, 50.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

# cache 倍率，乘在該 model 的 input 價格上。
_CACHE_READ_MULTIPLIER = 0.1
_CACHE_WRITE_5M_MULTIPLIER = 1.25
_CACHE_WRITE_1H_MULTIPLIER = 2.0

_EXPENSIVE_MODEL_PREFIXES = ("claude-opus-", "claude-fable-", "claude-mythos-")

_MUTATING_TOOLS = frozenset({"Write", "Edit", "Bash", "NotebookEdit"})
_READ_ONLY_TOOLS = frozenset({"Read", "Grep", "Glob", "WebFetch", "WebSearch"})

# 去掉 "[1m]" 這類 context-mode 後綴（例如 "claude-opus-4-8[1m]"）。
_MODEL_SUFFIX_RE = re.compile(r"\[.*?\]$")


@dataclass
class UsageAccumulator:
    """單一 model 的 token 用量累加器。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_5m_tokens: int = 0
    cache_creation_1h_tokens: int = 0


@dataclass
class ModelCostBreakdown:
    """單一 model 的用量與成本估算結果。"""

    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_usd: float | None
    priced: bool


@dataclass
class TranscriptLookupResult:
    """定位「目前 session 的 transcript」的結果。"""

    status: str  # "found" | "ambiguous" | "not_found"
    path: Path | None = None
    warning: str | None = None


@dataclass
class TokenUsageReport:
    """一次 compute_token_usage_report() 呼叫的完整結果。"""

    status: str  # "computed" | "computed_partial" | "ambiguous" | "unavailable"
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    total_cost_usd: float | None = None
    by_model: list[dict[str, Any]] = field(default_factory=list)
    session_effort: str | None = None
    optimization_notes: list[str] = field(default_factory=list)
    warning: str | None = None


def _normalize_model_id(model: str) -> str:
    """去掉 `[1m]` 這類後綴，並把 dated snapshot 前綴比對回定價表的 undated key。"""
    normalized = _MODEL_SUFFIX_RE.sub("", model).strip()
    if normalized in _PRICING_USD_PER_1M:
        return normalized
    for key in _PRICING_USD_PER_1M:
        if normalized.startswith(key + "-"):
            return key
    return normalized


def _project_slug_for_cwd(cwd: Path) -> str:
    """把 git repo 根目錄路徑轉成 `~/.claude/projects/<slug>` 的目錄名稱。

    沿用 `bash_hygiene_audit/cli.py` 的轉換邏輯。**不可**改用
    `registry.resolve_project_slug()`——那個回傳的是 handover 用的純 repo 名稱
    （如 "yibi-stack"），不是這裡要的 transcript 目錄 slug
    （如 "-Users-howie-Workspace-github-yibi-stack"）。
    """
    try:
        result = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(cwd), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        repo_root = Path(result.stdout.strip()).parent if result.returncode == 0 else cwd
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        repo_root = cwd
    return re.sub(r"[/\\]", "-", str(repo_root))


def _first_record_cwd(path: Path) -> str | None:
    """讀取 transcript 第一筆有 `cwd` 欄位的記錄。

    Session 的 cwd 在建立時就固定（repo 慣例避免 stateful cd），讀第一筆即可，
    不需要掃完整個 transcript。
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:  # nosec B112
                    continue
                cwd = obj.get("cwd")
                if isinstance(cwd, str) and cwd:
                    return cwd
    except OSError:
        return None
    return None


def find_current_transcript(
    working_dir: Path,
    *,
    projects_dir: Path | None = None,
    ambiguity_window_seconds: float = 60.0,
) -> TranscriptLookupResult:
    """在 `~/.claude/projects/<slug>/` 下找「屬於目前工作目錄、最新」的 transcript。

    啟發式：篩出「第一筆記錄的 cwd 等於 working_dir」的候選檔案，取 mtime 最新者。
    若最新與次新的候選 mtime 差距小於 `ambiguity_window_seconds`（代表可能有另一個
    Claude Code session 同時在同一目錄工作），回傳 ambiguous 而不硬猜。
    """
    base = projects_dir or CLAUDE_PROJECTS_DIR
    slug = _project_slug_for_cwd(working_dir)
    project_dir = base / slug
    if not project_dir.is_dir():
        return TranscriptLookupResult(
            status="not_found",
            warning=f"找不到 project transcript 目錄：{project_dir}",
        )

    target = str(working_dir.resolve())
    candidates: list[tuple[float, Path]] = []
    for jsonl_path in project_dir.glob("*.jsonl"):
        if _first_record_cwd(jsonl_path) != target:
            continue
        try:
            mtime = jsonl_path.stat().st_mtime
        except OSError:
            continue
        candidates.append((mtime, jsonl_path))

    if not candidates:
        return TranscriptLookupResult(
            status="not_found",
            warning=f"在 {project_dir} 找不到符合目前工作目錄的 transcript",
        )

    candidates.sort(key=lambda item: item[0], reverse=True)
    newest_mtime, newest_path = candidates[0]
    if len(candidates) > 1 and (newest_mtime - candidates[1][0]) < ambiguity_window_seconds:
        return TranscriptLookupResult(
            status="ambiguous",
            warning=(
                "偵測到多個可能是目前 session 的 transcript（mtime 太接近），"
                "可能有另一個 Claude Code session 同時在此目錄工作，無法可靠判斷。"
            ),
        )

    return TranscriptLookupResult(status="found", path=newest_path)


def _accumulate_usage_by_model(path: Path) -> dict[str, UsageAccumulator]:
    """逐行掃描單一 transcript，依 model 加總 assistant 訊息的 usage。"""
    result: dict[str, UsageAccumulator] = {}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:  # nosec B112
                    continue
                message = obj.get("message")
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue
                model = message.get("model")
                usage = message.get("usage")
                if not isinstance(model, str) or not isinstance(usage, dict):
                    continue
                acc = result.setdefault(model, UsageAccumulator())
                acc.input_tokens += int(usage.get("input_tokens") or 0)
                acc.output_tokens += int(usage.get("output_tokens") or 0)
                acc.cache_read_tokens += int(usage.get("cache_read_input_tokens") or 0)
                cache_creation = usage.get("cache_creation")
                if isinstance(cache_creation, dict):
                    acc.cache_creation_5m_tokens += int(
                        cache_creation.get("ephemeral_5m_input_tokens") or 0
                    )
                    acc.cache_creation_1h_tokens += int(
                        cache_creation.get("ephemeral_1h_input_tokens") or 0
                    )
                else:
                    # 舊格式只有攤平的 cache_creation_input_tokens，沒有 5m/1h 拆分；
                    # 保守歸入 5m（倍率較低，避免高估成本）。
                    acc.cache_creation_5m_tokens += int(
                        usage.get("cache_creation_input_tokens") or 0
                    )
    except OSError:
        pass
    return result


def _find_subagent_transcripts(main_transcript: Path) -> list[Path]:
    """找出 main transcript 對應的 subagent transcript 檔案。

    位置：`<main_transcript stem>/subagents/agent-*.jsonl`。刻意不去讀 parent
    transcript 裡 `tool_result.toolUseResult` 的 usage rollup——那個只有同步呼叫
    才完整，背景呼叫是粗略值，一律直接讀 subagent 自己的檔案，避免重複計算。
    """
    subagents_dir = main_transcript.parent / main_transcript.stem / "subagents"
    if not subagents_dir.is_dir():
        return []
    return sorted(subagents_dir.glob("agent-*.jsonl"))


def _read_subagent_meta(agent_path: Path) -> dict[str, Any]:
    """讀取 subagent 的 `.meta.json`（agentType/description/toolUseId/spawnDepth）。"""
    meta_path = agent_path.with_name(agent_path.stem + ".meta.json")
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _count_tool_uses(agent_path: Path) -> dict[str, int]:
    """數 subagent 自己 transcript 裡的 tool_use，分成 mutating / read_only / total。

    `Bash` 一律歸類 mutating（保守但不精確——例如純 read-only 的 `git log` 也會被
    算進去；已知限制，v2 可以再依指令內容細分）。
    """
    counts = {"mutating": 0, "read_only": 0, "total": 0}
    try:
        with agent_path.open("r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:  # nosec B112
                    continue
                message = obj.get("message")
                if not isinstance(message, dict):
                    continue
                for block in message.get("content") or []:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    counts["total"] += 1
                    name = block.get("name")
                    if name in _MUTATING_TOOLS:
                        counts["mutating"] += 1
                    elif name in _READ_ONLY_TOOLS:
                        counts["read_only"] += 1
    except OSError:
        pass
    return counts


def _is_zero_usage(acc: UsageAccumulator) -> bool:
    """判斷是否為全零用量（如 Claude Code 內部的 `<synthetic>` 標記記錄）。"""
    return (
        acc.input_tokens == 0
        and acc.output_tokens == 0
        and acc.cache_read_tokens == 0
        and acc.cache_creation_5m_tokens == 0
        and acc.cache_creation_1h_tokens == 0
    )


def _dominant_model(usage_by_model: dict[str, UsageAccumulator]) -> str:
    """挑出加總 token 數最多的 model（subagent 理論上只會有一個 model，保守起見用此法挑）。"""
    if not usage_by_model:
        return ""
    return max(
        usage_by_model,
        key=lambda m: usage_by_model[m].input_tokens + usage_by_model[m].output_tokens,
    )


def _generate_optimization_notes(subagent_summaries: list[dict[str, Any]]) -> list[str]:
    """對「昂貴 model + 零 mutating tool call」的 subagent 產生 best-effort 建議。"""
    notes: list[str] = []
    for summary in subagent_summaries:
        normalized = _normalize_model_id(summary.get("model") or "")
        if not normalized.startswith(_EXPENSIVE_MODEL_PREFIXES):
            continue
        tool_counts = summary.get("tool_counts") or {}
        if tool_counts.get("total", 0) == 0 or tool_counts.get("mutating", 0) != 0:
            continue
        agent_type = summary.get("agent_type") or "unknown"
        notes.append(
            f"[best-effort] subagent（agentType={agent_type}）用了 {normalized}，"
            f"但這次呼叫沒有任何 mutating tool call"
            f"（{tool_counts.get('read_only', 0)} 個 read-only tool call），"
            "像是純讀取/搜尋類任務——下次可以考慮改用較便宜的 model（如 sonnet）。"
        )
    return notes


def _model_cost(model: str, acc: UsageAccumulator) -> ModelCostBreakdown:
    """套用定價表計算單一 model 的成本；表中沒有的 model 回傳 `priced=False`。"""
    normalized = _normalize_model_id(model)
    prices = _PRICING_USD_PER_1M.get(normalized)
    cache_creation_tokens = acc.cache_creation_5m_tokens + acc.cache_creation_1h_tokens
    if prices is None:
        return ModelCostBreakdown(
            model=model,
            input_tokens=acc.input_tokens,
            output_tokens=acc.output_tokens,
            cache_read_tokens=acc.cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cost_usd=None,
            priced=False,
        )
    input_price, output_price = prices
    cost = (
        acc.input_tokens * input_price
        + acc.cache_creation_5m_tokens * input_price * _CACHE_WRITE_5M_MULTIPLIER
        + acc.cache_creation_1h_tokens * input_price * _CACHE_WRITE_1H_MULTIPLIER
        + acc.cache_read_tokens * input_price * _CACHE_READ_MULTIPLIER
        + acc.output_tokens * output_price
    ) / 1_000_000
    return ModelCostBreakdown(
        model=model,
        input_tokens=acc.input_tokens,
        output_tokens=acc.output_tokens,
        cache_read_tokens=acc.cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cost_usd=cost,
        priced=True,
    )


def _compute_report_for_transcript(main_transcript: Path) -> TokenUsageReport:
    per_model: dict[str, UsageAccumulator] = _accumulate_usage_by_model(main_transcript)

    subagent_summaries: list[dict[str, Any]] = []
    for agent_path in _find_subagent_transcripts(main_transcript):
        agent_usage = _accumulate_usage_by_model(agent_path)
        for model, acc in agent_usage.items():
            merged = per_model.setdefault(model, UsageAccumulator())
            merged.input_tokens += acc.input_tokens
            merged.output_tokens += acc.output_tokens
            merged.cache_read_tokens += acc.cache_read_tokens
            merged.cache_creation_5m_tokens += acc.cache_creation_5m_tokens
            merged.cache_creation_1h_tokens += acc.cache_creation_1h_tokens

        meta = _read_subagent_meta(agent_path)
        subagent_summaries.append(
            {
                "model": _dominant_model(agent_usage),
                "agent_type": meta.get("agentType"),
                "tool_counts": _count_tool_uses(agent_path),
            }
        )

    # Claude Code 會在 transcript 中插入 model="<synthetic>"、usage 全 0 的內部標記
    # 記錄（非真實 API 呼叫）；濾掉零用量的 model，避免它被誤判成「未定價」而觸發
    # 不必要的 computed_partial/WARN，也不汙染 by_model 輸出。
    breakdowns = [
        _model_cost(model, acc) for model, acc in per_model.items() if not _is_zero_usage(acc)
    ]

    priced_costs = [b.cost_usd for b in breakdowns if b.priced and b.cost_usd is not None]
    unpriced_models = sorted({b.model for b in breakdowns if not b.priced})

    status = "computed"
    warning = None
    if unpriced_models:
        status = "computed_partial"
        warning = f"以下 model 沒有定價資料，成本為部分估算：{', '.join(unpriced_models)}"

    return TokenUsageReport(
        status=status,
        total_input_tokens=sum(b.input_tokens for b in breakdowns),
        total_output_tokens=sum(b.output_tokens for b in breakdowns),
        total_cache_read_tokens=sum(b.cache_read_tokens for b in breakdowns),
        total_cache_creation_tokens=sum(b.cache_creation_tokens for b in breakdowns),
        total_cost_usd=sum(priced_costs) if priced_costs else None,
        by_model=[
            {
                "model": b.model,
                "input_tokens": b.input_tokens,
                "output_tokens": b.output_tokens,
                "cache_read_tokens": b.cache_read_tokens,
                "cache_creation_tokens": b.cache_creation_tokens,
                "cost_usd": b.cost_usd,
                "priced": b.priced,
            }
            for b in breakdowns
        ],
        session_effort=os.environ.get("CLAUDE_EFFORT"),
        optimization_notes=_generate_optimization_notes(subagent_summaries),
        warning=warning,
    )


def compute_token_usage_report(
    working_dir: Path,
    *,
    projects_dir: Path | None = None,
) -> TokenUsageReport:
    """計算目前 session（含所有 subagent）的 token 用量與成本估算。永不 raise。"""
    try:
        lookup = find_current_transcript(working_dir, projects_dir=projects_dir)
    except Exception as e:  # noqa: BLE001  最外層防護，絕不讓例外往外拋
        return TokenUsageReport(status="unavailable", warning=f"transcript 定位失敗：{e}")

    if lookup.status != "found" or lookup.path is None:
        # TranscriptLookupResult 用 "not_found"；TokenUsageReport/TokenUsageSource
        # 統一用 "unavailable"（"ambiguous" 兩邊共用，直接 passthrough）。
        status = "unavailable" if lookup.status == "not_found" else lookup.status
        return TokenUsageReport(status=status, warning=lookup.warning)

    try:
        return _compute_report_for_transcript(lookup.path)
    except Exception as e:  # noqa: BLE001
        return TokenUsageReport(status="unavailable", warning=f"token 用量計算失敗：{e}")


def compute_auto_token_fields(effective_dir: Path, enabled: bool) -> dict[str, Any]:
    """Best-effort 計算 token 用量欄位；任何失敗都回傳空 dict，不影響呼叫端主流程。

    供 retrospective_service.write_retrospective() 等寫入端呼叫，回傳的 dict
    可直接以 `**fields` 合併進對應 Pydantic record 的建構參數。
    """
    if not enabled:
        return {}

    import warnings

    try:
        report = compute_token_usage_report(effective_dir)
    except Exception as e:  # noqa: BLE001  token 用量計算失敗不可影響呼叫端主寫入流程
        warnings.warn(f"token 用量自動計算失敗：{e}", stacklevel=2)
        return {}

    fields: dict[str, Any] = {"token_usage_source": report.status}
    if report.status in ("computed", "computed_partial"):
        fields.update(
            token_input_tokens=report.total_input_tokens,
            token_output_tokens=report.total_output_tokens,
            token_cache_read_tokens=report.total_cache_read_tokens,
            token_cache_creation_tokens=report.total_cache_creation_tokens,
            token_total_cost_usd=report.total_cost_usd,
            token_cost_by_model=report.by_model,
            session_effort=report.session_effort,
            token_optimization_notes=report.optimization_notes,
        )
    return fields

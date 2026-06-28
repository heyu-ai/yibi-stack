"""知識蒸餾 service：定期收割 typed lessons，聚類反覆出現的模式，輸出 skill candidate digest。

對映 NousResearch/hermes-agent 的 Skills System：

- **periodic nudge**：只在「累積了 watermark 之後的新教訓」時，才把反覆出現的 cluster
  升為 skill candidate。沒有新證據就回傳空清單，避免每次重跑都重複 surface 同一批。
- **autonomous skill creation 的前置**：CLI 只負責機械式收割與聚類，產出 candidate；
  「要不要變成 skill / rule、以及怎麼寫」由下游 `knowledge-distill` skill（人類 gate）決定。
  注意：該下游 skill 住在另一個 repo（`ainization-skill` 的 `skills/knowledge-distill/`），
  本 CLI 的 entrypoint 是 `uv run python -m tasks.mycelium distill run`。

clustering 目前用**確定性 token 相似度（lexical）**：ASCII word + CJK bigram 的 Jaccard，
搭配 type 與 key 領域前綴。`semantic_index.SqliteVecIndex.embed()` 在 Phase 4 embedding
pipeline 落地前永遠回傳 []（語意向量尚未可用），故 `_similarity()` 暫以 lexical 實作；
等真正的 embedding 落地後可在 `_similarity()` 換成向量距離以提升語意聚類品質。

唯讀原則：本 service **只讀 lessons 資料列**，不寫入任何 lesson row（不 insert/update/delete）。
唯一的 DB 寫入是 harvest 的 `init_db()`（`CREATE TABLE IF NOT EXISTS`，schema 層、冪等），
其餘寫入只發生在 watermark state.json 與 digest 輸出檔。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import DigestReport, DistilledCluster, SkillCandidate


@dataclass
class HarvestResult:
    """harvest 輸出：視窗內 lessons + 可觀測性指標（讓 silent drop / 截斷不再隱形）。"""

    lessons: list[dict[str, Any]] = field(default_factory=list)
    dropped_unparseable_ts: int = 0  # ts 無法解析而被跳過的筆數
    truncated: bool = False  # 是否撞到 _HARVEST_SCAN_LIMIT（視窗可能含更舊但未掃到的 lesson）


# ─── 門檻常數（保守預設；跑幾輪後依 false-positive 率調整）──────────────────
DEFAULT_SINCE_DAYS = 90
MIN_CLUSTER_SIZE = 3  # cluster 至少 N 條 lesson
MIN_DISTINCT_PRS = 2  # 至少跨 N 個不同 retro_pr（= 反覆出現，非一次性）
MIN_AVG_CONFIDENCE = 7.0  # cluster 平均 confidence 門檻
CANDIDATE_TYPES = ("pattern", "operational", "tool")  # procedural 型（對映 Hermes「長程序」）
SIMILARITY_THRESHOLD = 0.34  # Jaccard 相似度門檻
# 同 key 領域前綴時放寬到此較低門檻（prefix 只「降低」門檻，不無條件併團，
# 避免所有 bash-* 因共用前綴卻零 token 重疊就塌成一個 grab-bag mega-cluster）
PREFIX_SIMILARITY_FLOOR = 0.15
_HARVEST_SCAN_LIMIT = 2000  # 單次掃描的 lesson 上限（O(n^2) 聚類的安全上界）

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")
_CJK_RUN_RE = re.compile("[一-鿿]+")
# key 領域前綴若為以下泛用詞則視為無前綴，不據此強制聚類
_GENERIC_KEY_PREFIXES = {"legacy", "lesson", "the", "a", "an"}


def _tokenize(text: str) -> set[str]:
    """切出比對用 token：ASCII word（len>=2）+ 連續 CJK run 內的相鄰雙字。

    單一 CJK 字（如「的」「是」）雜訊太高，故只取 CJK bigram；
    bigram 只在**連續** CJK run 內組，跨非 CJK 間隔不組（避免假相鄰）。
    """
    lowered = text.lower()
    tokens = {t for t in _TOKEN_RE.findall(lowered) if len(t) >= 2}
    for run in _CJK_RUN_RE.findall(lowered):
        for i in range(len(run) - 1):
            tokens.add(run[i : i + 2])
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    """兩個 token set 的 Jaccard 相似度（0.0–1.0）。"""
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _similarity(a: set[str], b: set[str]) -> float:
    """目前以 lexical Jaccard 實作；embedding 落地後可換成向量距離。"""
    return _jaccard(a, b)


def _key_prefix(key: str) -> str:
    """取 key 的領域前綴（第一個 '-' 前的 token）；泛用詞或純數字回空字串。"""
    head = key.split("-", 1)[0].lower()
    if not head or head in _GENERIC_KEY_PREFIXES or head.isdigit():
        return ""
    return head


def _parse_ts(ts: str | None) -> datetime | None:
    """解析 ISO 時間戳；無時區補 UTC。格式錯誤回 None（呼叫端跳過）。"""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _parse_since(since: str, now: datetime) -> datetime:
    """解析 --since：'<N>d' 相對天數，或 ISO 絕對時間。"""
    s = since.strip().lower()
    if s.endswith("d") and s[:-1].isdigit():
        return now - timedelta(days=int(s[:-1]))
    parsed = _parse_ts(since)
    if parsed is None:
        raise ValueError(f"--since 格式錯誤，需為 '<N>d' 或 ISO 時間：{since!r}")
    return parsed


def harvest(
    since: str = f"{DEFAULT_SINCE_DAYS}d",
    project: str | None = None,
    db_path: str | Path | None = None,
    now: datetime | None = None,
) -> HarvestResult:
    """讀取 since 視窗內的 typed lessons（只讀 lesson 資料列）。

    復用 AgentsDB.query_lessons_typed（SELECT * FROM lessons），再以 ts 在 Python 端過濾。
    回傳 HarvestResult，含 dropped_unparseable_ts 與 truncated 兩個可觀測性指標。
    """
    from .db import AgentsDB

    _now = now if now is not None else datetime.now(UTC)
    cutoff = _parse_since(since, _now)

    db = AgentsDB(db_path=db_path)
    try:
        db.init_db()
        rows = db.query_lessons_typed(project=project, limit=_HARVEST_SCAN_LIMIT)
    finally:
        db.close()

    out: list[dict[str, Any]] = []
    dropped = 0
    for row in rows:
        ts = _parse_ts(row.get("ts", ""))
        if ts is None:
            dropped += 1  # ts 解析失敗：與「視窗外」分開計數，避免靜默丟失
            continue
        if ts < cutoff:
            continue
        out.append(row)
    return HarvestResult(
        lessons=out,
        dropped_unparseable_ts=dropped,
        truncated=len(rows) >= _HARVEST_SCAN_LIMIT,
    )


class _UnionFind:
    """簡單 union-find（path compression）。"""

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra


def _cluster_id(lesson_ids: list[str]) -> str:
    """以排序後 lesson id 的 sha256 前綴產生穩定 cluster id（非加密用途）。"""
    digest = hashlib.sha256("|".join(sorted(lesson_ids)).encode("utf-8")).hexdigest()
    return f"cl-{digest[:12]}"


def _build_cluster(members: list[dict[str, Any]]) -> DistilledCluster:
    """把一群 lesson dict 組成 DistilledCluster。"""
    lesson_ids = [str(m.get("id", "")) for m in members]
    confidences = [int(m.get("confidence", 0)) for m in members]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    # representative = confidence 最高者的 insight
    rep = max(members, key=lambda m: int(m.get("confidence", 0)))
    retro_prs = sorted({int(m["retro_pr"]) for m in members if m.get("retro_pr") is not None})
    subject_skills = sorted({str(m["skill"]) for m in members if m.get("skill")})
    trimmed = [
        {
            "id": m.get("id"),
            "key": m.get("key"),
            "type": m.get("type"),
            "insight": m.get("insight"),
            "confidence": m.get("confidence"),
            "retro_pr": m.get("retro_pr"),
            "skill": m.get("skill"),
            "project": m.get("project"),
            "ts": m.get("ts"),
        }
        for m in members
    ]
    return DistilledCluster(
        cluster_id=_cluster_id(lesson_ids),
        lesson_ids=lesson_ids,
        member_keys=sorted({str(m.get("key", "")) for m in members}),
        types=sorted({str(m.get("type", "")) for m in members}),
        retro_prs=retro_prs,
        subject_skills=subject_skills,
        avg_confidence=round(avg_conf, 2),
        representative_insight=str(rep.get("insight", "")),
        member_lessons=trimmed,
    )


def cluster(
    lessons: list[dict[str, Any]],
    threshold: float = SIMILARITY_THRESHOLD,
) -> list[DistilledCluster]:
    """把 lessons 聚成 cluster：同 type 且（key 領域前綴相同 或 token 相似度 >= 門檻）即併團。"""
    n = len(lessons)
    if n == 0:
        return []

    toks = [_tokenize(str(le.get("insight", ""))) for le in lessons]
    types = [str(le.get("type", "")) for le in lessons]
    prefixes = [_key_prefix(str(le.get("key", ""))) for le in lessons]

    uf = _UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            if types[i] != types[j]:
                continue
            sim = _similarity(toks[i], toks[j])
            same_prefix = bool(prefixes[i]) and prefixes[i] == prefixes[j]
            # prefix 只降低門檻，仍要求最低 token 重疊；否則純靠相似度門檻
            effective = PREFIX_SIMILARITY_FLOOR if same_prefix else threshold
            if sim >= effective:
                uf.union(i, j)

    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for idx in range(n):
        groups[uf.find(idx)].append(lessons[idx])

    return [_build_cluster(members) for members in groups.values()]


def _slug_title(cluster_obj: DistilledCluster) -> str:
    """從 member keys 推一個 candidate 標題（取最常見的領域前綴 + 代表 key）。"""
    prefixes = [_key_prefix(k) for k in cluster_obj.member_keys]
    prefixes = [p for p in prefixes if p]
    head = cluster_obj.member_keys[0] if cluster_obj.member_keys else cluster_obj.cluster_id
    if prefixes:
        top = max(set(prefixes), key=prefixes.count)
        # 避免雙前綴（member_keys[0] 已以 top 開頭時不再前綴，如 bash-bash-cd）
        title = head if head.startswith(f"{top}-") else f"{top}-{head}"
        return title[:60]
    return head[:60]


def score(
    clusters: list[DistilledCluster],
    watermark: str | None = None,
    min_cluster: int = MIN_CLUSTER_SIZE,
) -> list[SkillCandidate]:
    """依門檻把 cluster 篩成 skill candidate。

    門檻：size >= min_cluster 且 跨 >= MIN_DISTINCT_PRS 個 retro_pr
    且 avg_confidence >= MIN_AVG_CONFIDENCE 且 type 含 procedural 型
    且 **含至少一條 ts > watermark 的新教訓**（periodic nudge）。
    """
    wm = _parse_ts(watermark)
    candidates: list[SkillCandidate] = []

    for c in clusters:
        if len(c.lesson_ids) < min_cluster:
            continue
        if len(c.retro_prs) < MIN_DISTINCT_PRS:
            continue
        if c.avg_confidence < MIN_AVG_CONFIDENCE:
            continue
        if not any(t in CANDIDATE_TYPES for t in c.types):
            continue

        if wm is None:
            has_new = True
        else:
            has_new = any(
                (mts := _parse_ts(m.get("ts"))) is not None and mts > wm for m in c.member_lessons
            )
        if not has_new:
            continue

        candidates.append(
            SkillCandidate(
                candidate_id=c.cluster_id,
                title=_slug_title(c),
                recurrence_pr_count=len(c.retro_prs),
                has_new_evidence=has_new,
                cluster=c,
            )
        )

    candidates.sort(
        key=lambda x: (x.recurrence_pr_count, x.cluster.avg_confidence),
        reverse=True,
    )
    return candidates


def load_watermark(path: str | Path | None) -> str | None:
    """讀取 watermark state.json 的 last_run；不存在回 None。

    **損壞**（JSON 解析失敗）與**缺失**語意不同：損壞會被當成首跑而 re-flood，
    且隨後被覆寫抹除證據，故損壞時印 stderr 警告再回 None，讓異常可見。
    """
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        import sys

        print(f"[WARN] watermark state.json 損壞，本次視為首跑：{p}（{e}）", file=sys.stderr)
        return None
    last_run = data.get("last_run")
    return str(last_run) if last_run else None


def save_watermark(path: str | Path, ts: str) -> None:
    """寫入 watermark state.json。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"last_run": ts}, indent=2) + "\n", encoding="utf-8")


def run_distill(  # noqa: PLR0913
    since: str = f"{DEFAULT_SINCE_DAYS}d",
    project: str | None = None,
    db_path: str | Path | None = None,
    watermark_path: str | Path | None = None,
    out_path: str | Path | None = None,
    now: datetime | None = None,
    update_watermark: bool = True,
    min_cluster: int = MIN_CLUSTER_SIZE,
) -> DigestReport:
    """完整 distill 流程：harvest → cluster → score → 輸出 digest + 更新 watermark。"""
    _now = now if now is not None else datetime.now(UTC)
    wm = load_watermark(watermark_path)

    harvested = harvest(since=since, project=project, db_path=db_path, now=_now)
    clusters = cluster(harvested.lessons)
    candidates = score(clusters, watermark=wm, min_cluster=min_cluster)

    report = DigestReport(
        generated_at=_now.isoformat(),
        since=since,
        project=project,
        watermark=wm,
        total_lessons_scanned=len(harvested.lessons),
        dropped_unparseable_ts=harvested.dropped_unparseable_ts,
        truncated=harvested.truncated,
        candidate_count=len(candidates),
        candidates=candidates,
    )

    if out_path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")

    if update_watermark and watermark_path:
        save_watermark(watermark_path, _now.isoformat())

    return report

"""Friction Clusterer：用 Jaccard keyword 相似度將同類 friction events 分群。"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict

from .models import FrictionCluster, FrictionEvent, FrictionType


# Stopwords to exclude from keyword extraction
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "and",
        "or",
        "is",
        "was",
        "be",
        "by",
        "it",
        "this",
        "that",
        "with",
        "from",
        "as",
        "are",
        "not",
        "no",
        "i",
        "my",
        "me",
        "we",
        "have",
        "has",
        "had",
        "let",
        "do",
        "did",
        "can",
        "will",
        "would",
        "should",
        "could",
        "may",
        "when",
        "where",
        "what",
        "how",
        "which",
        "who",
    }
)


def _extract_keywords(text: str) -> frozenset[str]:
    """從文字萃取小寫英文關鍵字（去除停用詞）。"""
    tokens = re.findall(r"\b[a-z]{3,}\b", text.lower())
    return frozenset(t for t in tokens if t not in _STOPWORDS)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard 相似度：交集 / 聯集。"""
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _description_keywords(event: FrictionEvent) -> frozenset[str]:
    """結合 description 和 raw_text 的關鍵字。"""
    return _extract_keywords(event.description + " " + event.raw_text)


class FrictionClusterer:
    """依 friction_type 分組，再用 Jaccard threshold 合並相近事件。"""

    def __init__(self, threshold: float = 0.25, min_cluster_size: int = 2) -> None:
        self.threshold = threshold
        self.min_cluster_size = min_cluster_size

    def cluster(self, events: list[FrictionEvent]) -> list[FrictionCluster]:
        """回傳所有 cluster（含 count < min_cluster_size 的，方便 caller 自行過濾）。"""
        # Group by friction_type first
        by_type: dict[FrictionType, list[FrictionEvent]] = defaultdict(list)
        for event in events:
            by_type[event.friction_type].append(event)

        all_clusters: list[FrictionCluster] = []
        for ftype, type_events in by_type.items():
            clusters = self._cluster_within_type(ftype, type_events)
            all_clusters.extend(clusters)

        return all_clusters

    def _cluster_within_type(
        self, ftype: FrictionType, events: list[FrictionEvent]
    ) -> list[FrictionCluster]:
        """Greedy single-linkage clustering within one friction type."""
        if not events:
            return []

        # Build keyword sets for each event
        kw_sets = [_description_keywords(e) for e in events]

        # Greedy assignment: each event goes into the first cluster it's similar enough to
        cluster_events: list[list[FrictionEvent]] = []
        cluster_kws: list[frozenset[str]] = []

        for event, kw_set in zip(events, kw_sets):
            placed = False
            for i, ckw in enumerate(cluster_kws):
                if _jaccard(kw_set, ckw) >= self.threshold:
                    cluster_events[i].append(event)
                    # Expand cluster keyword set (union)
                    cluster_kws[i] = cluster_kws[i] | kw_set
                    placed = True
                    break
            if not placed:
                cluster_events.append([event])
                cluster_kws.append(kw_set)

        clusters: list[FrictionCluster] = []
        for ev_list, ckw in zip(cluster_events, cluster_kws):
            # Top 10 common keywords (by frequency across events in cluster)
            freq: dict[str, int] = {}
            for e in ev_list:
                for k in _description_keywords(e):
                    freq[k] = freq.get(k, 0) + 1
            top_kws = sorted(freq, key=lambda k: -freq[k])[:10]

            clusters.append(
                FrictionCluster(
                    id=str(uuid.uuid4()),
                    friction_type=ftype,
                    events=ev_list,
                    common_keywords=top_kws,
                )
            )

        return clusters

    def eligible(self, clusters: list[FrictionCluster]) -> list[FrictionCluster]:
        """回傳 count >= min_cluster_size 的 clusters。"""
        return [c for c in clusters if c.count >= self.min_cluster_size]

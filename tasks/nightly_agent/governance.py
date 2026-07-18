"""跨夜 friction 去重與持久化治理。"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess  # nosec B404
from datetime import datetime
from pathlib import Path

from .models import FrictionCluster


def friction_fingerprint(cluster: FrictionCluster) -> str:
    """產生不受 nightly UUID 影響的穩定 fingerprint。"""
    tokens = _cluster_tokens(cluster)
    canonical = f"{cluster.friction_type}|{'|'.join(sorted(tokens))}"
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _cluster_tokens(cluster: FrictionCluster) -> set[str]:
    text = " ".join(cluster.common_keywords + [event.description for event in cluster.events])
    return set(re.findall(r"[a-z0-9_]{2,}", text.casefold()))


class FrictionRegistry:
    """記錄已處理 friction，並檢查 state、branch 與 open PR。"""

    def __init__(self, state_file: str | Path, main_repo: Path, github_repo: str = "") -> None:
        path = Path(state_file)
        self.state_file = path if path.is_absolute() else main_repo / path
        self.main_repo = main_repo
        self.github_repo = github_repo
        self.records = self._load()

    def find_duplicate(self, cluster: FrictionCluster, threshold: float = 0.75) -> str | None:
        fingerprint = friction_fingerprint(cluster)
        candidate_tokens = _cluster_tokens(cluster)
        for record in self.records:
            if not isinstance(record, dict):
                continue
            if record.get("fingerprint") == fingerprint:
                return "跨夜 friction state"
            tokens = record.get("tokens")
            if isinstance(tokens, list):
                stored = {token for token in tokens if isinstance(token, str)}
                union = candidate_tokens | stored
                similarity = len(candidate_tokens & stored) / len(union) if union else 0.0
                if (
                    record.get("friction_type") == str(cluster.friction_type)
                    and similarity >= threshold
                ):
                    return "相似的跨夜 friction state"

        haystack = self._existing_branch_and_pr_text()
        searchable = {token for token in candidate_tokens if len(token) >= 4}
        matching_tokens = {token for token in searchable if token in haystack}
        if fingerprint in haystack or len(matching_tokens) >= 2:
            return "既有 branch／open PR"
        return None

    def record(self, cluster: FrictionCluster, status: str) -> None:
        self.records.append(
            {
                "fingerprint": friction_fingerprint(cluster),
                "friction_type": str(cluster.friction_type),
                "tokens": sorted(_cluster_tokens(cluster)),
                "status": status,
                "seen_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.state_file.write_text(
                json.dumps({"version": 1, "frictions": self.records}, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
        except OSError as e:
            raise RuntimeError(f"無法寫入 friction state：{self.state_file}") from e

    def _load(self) -> list[dict[str, object]]:
        if not self.state_file.is_file():
            return []
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, dict) or not isinstance(data.get("frictions"), list):
            return []
        return [item for item in data["frictions"] if isinstance(item, dict)]

    def _existing_branch_and_pr_text(self) -> str:
        parts: list[str] = []
        try:
            branch_result = subprocess.run(  # nosec B603
                [
                    "git",
                    "-C",
                    str(self.main_repo),
                    "branch",
                    "--all",
                    "--format=%(refname:short)",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if branch_result.returncode == 0:
                parts.append(branch_result.stdout.casefold())
        except (OSError, subprocess.TimeoutExpired):
            pass
        if self.github_repo:
            try:
                pr_result = subprocess.run(  # nosec B603 B607
                    [
                        "gh",
                        "pr",
                        "list",
                        "--repo",
                        self.github_repo,
                        "--state",
                        "open",
                        "--json",
                        "title,headRefName",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if pr_result.returncode == 0:
                    parts.append(pr_result.stdout.casefold())
            except (OSError, subprocess.TimeoutExpired):
                pass
        return "\n".join(parts)

"""跨夜 friction 去重與持久化治理。"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess  # nosec B404
import sys
from datetime import datetime
from pathlib import Path
from typing import cast

from .models import FrictionCluster


def friction_fingerprint(cluster: FrictionCluster) -> str:
    """產生不受 nightly UUID 影響的穩定 fingerprint。"""
    tokens = _cluster_tokens(cluster)
    canonical = f"{cluster.friction_type}|{'|'.join(sorted(tokens))}"
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _cluster_tokens(cluster: FrictionCluster) -> set[str]:
    text = " ".join(cluster.common_keywords + [event.description for event in cluster.events])
    tokens: set[str] = set()
    for chunk in re.findall(r"[\w\u3040-\u30ff\u3400-\u9fff]+", text.casefold(), re.UNICODE):
        latin = re.fullmatch(r"[a-z0-9_]+", chunk)
        if latin:
            if len(chunk) >= 2:
                tokens.add(chunk)
            continue
        # CJK／kana 沒有空白分詞；保留單字並加入 bigram，避免整句 token 讓近似判斷失真。
        characters = [char for char in chunk if char == "_" or char.isalnum()]
        tokens.update(characters)
        tokens.update(
            "".join(characters[index : index + 2]) for index in range(len(characters) - 1)
        )
    return tokens


def _is_searchable_token(token: str) -> bool:
    return len(token) >= 4 or (
        len(token) >= 2 and any("\u3040" <= char <= "\u9fff" for char in token)
    )


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
            if record.get("status") not in {"pr_opened", "resolved"}:
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
        searchable = {token for token in candidate_tokens if _is_searchable_token(token)}
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
        except (OSError, json.JSONDecodeError) as e:
            self._quarantine(f"無法讀取或解析：{e}")
            return []
        if not isinstance(data, dict) or not isinstance(data.get("frictions"), list):
            self._quarantine("資料格式不符（需要包含 frictions 陣列）")
            return []
        if any(not isinstance(item, dict) for item in data["frictions"]):
            self._quarantine("資料格式不符（frictions 項目必須是物件）")
            return []
        return cast(list[dict[str, object]], data["frictions"])

    def _quarantine(self, reason: str) -> None:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = self.state_file.with_name(f"{self.state_file.name}.corrupt-{timestamp}")
        suffix = 1
        while candidate.exists():
            candidate = self.state_file.with_name(
                f"{self.state_file.name}.corrupt-{timestamp}-{suffix}"
            )
            suffix += 1
        try:
            self.state_file.rename(candidate)
        except OSError as e:
            print(
                f"[WARN] friction state 損壞（{reason}），且隔離失敗：{e}",
                file=sys.stderr,
            )
            return
        print(f"[WARN] friction state 損壞（{reason}），已隔離至 {candidate}", file=sys.stderr)

    def _existing_branch_and_pr_text(self) -> str:
        parts: list[str] = []
        try:
            branch_result = subprocess.run(  # nosec B603 B607
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
            else:
                print(
                    f"[WARN] git branch 去重檢查失敗（exit {branch_result.returncode}）："
                    f"{branch_result.stderr.strip()}",
                    file=sys.stderr,
                )
        except FileNotFoundError as e:
            print(f"[WARN] git branch 去重檢查跳過（git 未安裝）：{e}", file=sys.stderr)
        except subprocess.TimeoutExpired as e:
            print(f"[WARN] git branch 去重檢查逾時：{e}", file=sys.stderr)
        except OSError as e:
            print(f"[WARN] git branch 去重檢查無法執行：{e}", file=sys.stderr)
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
                else:
                    print(
                        f"[WARN] GitHub PR 去重檢查失敗（exit {pr_result.returncode}）："
                        f"{pr_result.stderr.strip()}",
                        file=sys.stderr,
                    )
            except FileNotFoundError as e:
                print(f"[WARN] GitHub PR 去重檢查跳過（gh 未安裝）：{e}", file=sys.stderr)
            except subprocess.TimeoutExpired as e:
                print(f"[WARN] GitHub PR 去重檢查逾時：{e}", file=sys.stderr)
            except OSError as e:
                print(f"[WARN] GitHub PR 去重檢查無法執行：{e}", file=sys.stderr)
        else:
            print("[WARN] 未設定 GitHub repo，跳過 open PR 去重檢查", file=sys.stderr)
        return "\n".join(parts)

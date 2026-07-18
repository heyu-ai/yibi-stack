"""PR Orchestrator 設定載入與儲存。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click
from pydantic import BaseModel

from .._paths import RUNTIME_DIR

if TYPE_CHECKING:
    from .models import OrchestratorState

_STATE_DIR = RUNTIME_DIR / "pr_orchestrator"
_ARCHIVE_BASE = Path.home() / ".claude" / "pr_orchestrator"
_CONFIG_PATH = _STATE_DIR / "config.json"


class OrchestratorConfig(BaseModel):
    version: str = "1.0"
    max_fix_iterations: int = 3
    allow_fork_fix: bool = False
    base_branch: str = "main"
    auto_merge: bool = False


def _safe_repo(repo: str) -> str:
    # Known collision: a/b-c and a-b/c map to the same directory. The state repo
    # mismatch guard contains this as a fail-loud lockout; use a hash encoding in
    # a future migration of both active and archive paths.
    return repo.replace("/", "-").replace("\\", "-")


def state_path(repo: str, pr_number: int) -> Path:
    return _STATE_DIR / _safe_repo(repo or "unknown") / f"{pr_number}.json"


def archive_path(repo: str, pr_number: int) -> Path:
    return _ARCHIVE_BASE / _safe_repo(repo or "unknown") / f"{pr_number}.json"


def migrate_flat_state_files() -> None:
    """將舊版扁平 state 檔依其 repo 欄位遷移至隔離目錄。"""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    for src in _STATE_DIR.glob("*.json"):
        if not src.is_file() or not src.stem.isdigit():
            continue
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[WARN] 舊版 State 檔無法讀取，保留原檔：{src}：{e}", file=sys.stderr)
            continue

        value = data.get("repo") if isinstance(data, dict) else None
        repo = value.strip() if isinstance(value, str) else ""

        dest = state_path(repo or "unknown", int(src.stem))
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_file():
            try:
                if src.read_bytes() != dest.read_bytes():
                    print(
                        f"[WARN] 舊版 State 檔與既有隔離檔衝突；保留目的檔並移除來源檔："
                        f"{src} → {dest}",
                        file=sys.stderr,
                    )
                src.unlink(missing_ok=True)
            except OSError as e:
                raise RuntimeError(f"舊版 State 衝突檔清理失敗：{src} → {dest}") from e
            continue
        try:
            os.replace(src, dest)
        except OSError as e:
            raise RuntimeError(f"舊版 State 檔遷移失敗：{src} → {dest}") from e


def load_config(path: Path | None = None) -> OrchestratorConfig:
    config_path = path or _CONFIG_PATH
    if not config_path.is_file():
        return OrchestratorConfig()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"設定檔讀取失敗：{config_path}") from e
    return OrchestratorConfig.model_validate(data)


def save_config(cfg: OrchestratorConfig, path: Path | None = None) -> None:
    config_path = path or _CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(cfg.model_dump_json(indent=2) + "\n", encoding="utf-8")


def load_state_file(repo: str, pr_number: int) -> dict:  # type: ignore[type-arg]
    from .models import OrchestratorState

    migrate_flat_state_files()
    p = state_path(repo, pr_number)
    if not p.is_file():
        raise RuntimeError(f"找不到 PR #{pr_number} 的 state 檔：{p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"State 檔讀取失敗：{p}") from e
    state = OrchestratorState.model_validate(data)
    state_repo = state.repo.strip()
    current_repo = repo.strip()
    if not state_repo or not current_repo or state_repo != current_repo:
        raise RuntimeError(
            f"PR #{pr_number} 的 State repo 不一致：檔案記錄為「{state.repo or '空白'}」，"
            f"目前 repo 為「{repo or '空白'}」。可能發生 state 檔碰撞，已停止操作。"
        )
    return state.model_dump()


def persist_state(state: OrchestratorState) -> None:
    """原子寫入 state file（tmp + os.replace）。"""
    from .models import OrchestratorState as _S

    if not isinstance(state, _S):
        raise TypeError(f"expect OrchestratorState, got {type(state)}")
    if not state.repo.strip():
        raise RuntimeError(
            "無法解析 repo slug（GH_REPO 未設定且 gh repo view 失敗），"
            "無法安全隔離 state。請設定 GH_REPO=<owner>/<repo> 或確認 gh 已登入"
        )

    p = state_path(state.repo, state.pr_number)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    try:
        tmp.write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, p)
    except OSError as e:
        raise RuntimeError(f"State 檔寫入失敗：{p}") from e
    finally:
        if tmp.is_file():
            tmp.unlink(missing_ok=True)


def archive_state(state: OrchestratorState) -> None:
    """CLEANED 後把 state file 搬到 ~/.claude/pr_orchestrator/<repo>/ 作為歸檔。"""

    if not state.repo.strip():
        raise RuntimeError(
            "無法解析 repo slug（GH_REPO 未設定且 gh repo view 失敗），"
            "無法安全隔離 state。請設定 GH_REPO=<owner>/<repo> 或確認 gh 已登入"
        )
    dest = archive_path(state.repo, state.pr_number)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = state_path(state.repo, state.pr_number)
    if src.is_file():
        import shutil as _sh
        import sys  # noqa: PLC0415

        try:
            _sh.copy2(str(src), str(dest))
        except OSError as e:
            print(f"[WARN] State 歸檔複製失敗：{e}", file=sys.stderr)
            return
        try:
            src.unlink()
        except OSError as e:
            print(
                f"[WARN] 歸檔後刪除原始 state 失敗（已成功歸檔至 {dest}）：{e}\n"
                f"       請手動執行：python -m tasks.pr_orchestrator gc --pr {state.pr_number}",
                file=sys.stderr,
            )
            return
        click.echo(f"State 已歸檔：{dest}")


def find_latest_state(repo: str) -> int | None:
    """找到最新（last_transition_at 最大）的 active state file，回傳 PR 號碼。"""
    import json as _json

    migrate_flat_state_files()
    repo_dir = state_path(repo, 0).parent
    candidates = [p for p in repo_dir.glob("*.json") if p.is_file() and p.stem.isdigit()]
    if not candidates:
        return None

    best_pr: int | None = None
    best_ts = ""
    for p in candidates:
        try:
            data = _json.loads(p.read_text(encoding="utf-8"))
        except (OSError, _json.JSONDecodeError) as e:
            print(f"[WARN] State 檔無法讀取，略過：{p}：{e}", file=sys.stderr)
            continue
        ts = data.get("last_transition_at", "")
        if ts > best_ts:
            best_ts = ts
            best_pr = int(p.stem)
    return best_pr

"""REGSKILL-* tests for scripts/register_skill_repo.py。

驗證 issue #197 的 per-repo map 根治：多 repo `make install` 不再互相覆寫單一
skill_repo，且首次升級會把 legacy 頂層值遷移進 skill_repos map。
scripts/ 非 package，故以 importlib 依路徑載入模組，不污染 pythonpath。
"""

import importlib.util
import json
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parent.parent / "register_skill_repo.py"
_spec = importlib.util.spec_from_file_location("register_skill_repo", _MOD_PATH)
assert _spec is not None and _spec.loader is not None
register_skill_repo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(register_skill_repo)

register = register_skill_repo.register


def _read(cfg: Path) -> dict:
    return json.loads(cfg.read_text(encoding="utf-8"))


class TestRegister:
    def test_regskill_st_001_creates_map_from_empty(self, tmp_path: Path) -> None:
        """REGSKILL-ST-001: 無 config 時建立 skill_repos map 並補頂層 legacy。"""
        cfg = tmp_path / "config.json"
        register("/home/u/yibi-stack", cfg)
        data = _read(cfg)
        assert data["skill_repos"] == {"yibi-stack": "/home/u/yibi-stack"}
        assert data["skill_repo"] == "/home/u/yibi-stack"

    def test_regskill_st_002_migrates_legacy_top_level(self, tmp_path: Path) -> None:
        """REGSKILL-ST-002: 首次新版 register 把現有頂層 skill_repo 搬進 map。"""
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"skill_repo": "/home/u/yibi-stack"}) + "\n", encoding="utf-8")
        # 另一個 repo 先以新版 register 安裝，仍應保留 yibi-stack 的 legacy entry。
        register("/home/u/ainization-skill", cfg)
        data = _read(cfg)
        assert data["skill_repos"] == {
            "yibi-stack": "/home/u/yibi-stack",
            "ainization-skill": "/home/u/ainization-skill",
        }

    def test_regskill_dt_001_second_repo_preserves_first(self, tmp_path: Path) -> None:
        """REGSKILL-DT-001: 防回歸——安裝 repo B 後 repo A 的 entry 原封不動。"""
        cfg = tmp_path / "config.json"
        register("/home/u/yibi-stack", cfg)
        register("/home/u/ainization-skill", cfg)
        data = _read(cfg)
        assert data["skill_repos"]["yibi-stack"] == "/home/u/yibi-stack"
        assert data["skill_repos"]["ainization-skill"] == "/home/u/ainization-skill"

    def test_regskill_dt_002_top_level_not_overwritten(self, tmp_path: Path) -> None:
        """REGSKILL-DT-002: 已存在的頂層 skill_repo 不被後續 register 覆寫。"""
        cfg = tmp_path / "config.json"
        register("/home/u/yibi-stack", cfg)
        register("/home/u/ainization-skill", cfg)
        assert _read(cfg)["skill_repo"] == "/home/u/yibi-stack"

    def test_regskill_dt_003_reinstall_updates_own_entry(self, tmp_path: Path) -> None:
        """REGSKILL-DT-003: 同 repo 換路徑重裝，只更新自己的 entry。"""
        cfg = tmp_path / "config.json"
        register("/old/yibi-stack", cfg)
        register("/new/yibi-stack", cfg)
        data = _read(cfg)
        assert data["skill_repos"]["yibi-stack"] == "/new/yibi-stack"

    def test_regskill_eg_001_preserves_other_keys(self, tmp_path: Path) -> None:
        """REGSKILL-EG-001: 不動 config 其他欄位（device_id 等）。"""
        cfg = tmp_path / "config.json"
        cfg.write_text(
            json.dumps({"device_id": "MacBook", "operator": "howie"}) + "\n",
            encoding="utf-8",
        )
        register("/home/u/yibi-stack", cfg)
        data = _read(cfg)
        assert data["device_id"] == "MacBook"
        assert data["operator"] == "howie"

    def test_regskill_eg_002_corrupt_skill_repos_reseeded(self, tmp_path: Path) -> None:
        """REGSKILL-EG-002: skill_repos 非 dict（損毀）時重建並遷移 legacy。"""
        cfg = tmp_path / "config.json"
        cfg.write_text(
            json.dumps({"skill_repos": "oops", "skill_repo": "/home/u/yibi-stack"}) + "\n",
            encoding="utf-8",
        )
        register("/home/u/ainization-skill", cfg)
        data = _read(cfg)
        assert data["skill_repos"] == {
            "yibi-stack": "/home/u/yibi-stack",
            "ainization-skill": "/home/u/ainization-skill",
        }

    def test_regskill_dt_004_explicit_key_overrides_basename(self, tmp_path: Path) -> None:
        """REGSKILL-DT-004: 顯式 repo_name 蓋過 dir basename——從 worktree 目錄安裝也用 canonical key。

        對應 issue #199 mob review Critical：writer 的 key 必須與 reader 硬編碼的 "yibi-stack"
        一致，不因 checkout 目錄改名 / worktree 而漂掉。
        """
        cfg = tmp_path / "config.json"
        register("/home/u/.claude/worktrees/fix-197", cfg, repo_name="yibi-stack")
        data = _read(cfg)
        assert data["skill_repos"] == {"yibi-stack": "/home/u/.claude/worktrees/fix-197"}
        assert "fix-197" not in data["skill_repos"]

    def test_regskill_eg_003_relative_path_normalized_absolute(self, tmp_path: Path) -> None:
        """REGSKILL-EG-003: 相對路徑被 anchor 成絕對路徑（避免寫入相對路徑後 Pydantic 驗證失敗）。"""
        cfg = tmp_path / "config.json"
        register("some/relative/dir", cfg, repo_name="yibi-stack")
        stored = _read(cfg)["skill_repos"]["yibi-stack"]
        assert Path(stored).is_absolute()
        assert stored.endswith("some/relative/dir")

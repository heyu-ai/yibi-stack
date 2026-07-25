"""LINTLAYOUT-* tests for scripts/lint_plugin_layout.py。

**這些測試的用途是證明 lint 會對已知壞輸入 FAIL**——不是證明它在乾淨 repo 上會過。
一個檢查在你證明它擋得住壞輸入之前，它的「零命中」沒有資訊量；happy-path 測試單獨存在
只會給出虛假的信心（見 .claude/rules 與 CLAUDE.md 對正向對照的要求）。

每個測試在 tmp_path 建一個最小但結構正確的假 repo，注入單一缺陷，再以 subprocess 執行
真正的 CLI 進入點（而非 import 內部函式）——因為要驗的契約包含 exit code，那是呼叫端
（pre-commit / CI）唯一讀得到的訊號。

每次只注入一個缺陷：複合突變會因為錯的理由變紅，於是給出假的「已驗證」。
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "lint_plugin_layout.py"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _make_pack(root: Path, name: str, skills: list[str], version: str = "1.0.0") -> None:
    _write_json(root / "plugins" / name / "package.json", {"name": name, "version": version})
    _write_json(
        root / "plugins" / name / ".claude-plugin" / "plugin.json",
        {"name": name, "version": version},
    )
    for skill in skills:
        skill_md = root / "plugins" / name / "skills" / skill / "SKILL.md"
        skill_md.parent.mkdir(parents=True, exist_ok=True)
        skill_md.write_text(
            f"---\nname: {skill}\ntype: know\nscope: global\ndescription: demo\n---\n\n# {skill}\n",
            encoding="utf-8",
        )


def _make_repo(tmp_path: Path, packs: dict[str, list[str]] | None = None) -> Path:
    """建一個通過全部四項斷言的最小 repo，供各測試注入單一缺陷。"""
    root = tmp_path / "repo"
    packs = packs if packs is not None else {"alpha": ["foo"], "beta": ["bar"]}

    (root / "scripts").mkdir(parents=True)
    shutil.copy2(_SCRIPT, root / "scripts" / _SCRIPT.name)
    (root / "skills").mkdir()
    (root / "commands").mkdir()

    for name, skills in packs.items():
        _make_pack(root, name, skills)
        for skill in skills:
            os.symlink(f"../plugins/{name}/skills/{skill}", root / "skills" / skill)

    _write_json(
        root / ".claude-plugin" / "marketplace.json",
        {
            "name": "yibi-stack",
            "plugins": [{"name": n, "source": f"./plugins/{n}"} for n in packs],
        },
    )
    return root


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "lint_plugin_layout.py")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


class TestHappyPath:
    def test_lintlayout_ok_001_clean_repo_passes(self, tmp_path: Path) -> None:
        """LINTLAYOUT-OK-001: 結構正確的 repo -> exit 0

        這是對照組的基準線：若它不過，後面所有「壞輸入會 FAIL」的斷言都無法歸因。
        """
        result = _run(_make_repo(tmp_path))
        assert result.returncode == 0, result.stderr
        assert "[OK]" in result.stdout


class TestRootSymlink:
    def test_lintlayout_sl_001_dangling_symlink_fails(self, tmp_path: Path) -> None:
        """LINTLAYOUT-SL-001: 頂層 skills/ 有斷掉的 symlink -> exit 1 並指名該路徑"""
        root = _make_repo(tmp_path)
        os.symlink("../plugins/nope/skills/ghost", root / "skills" / "ghost")

        result = _run(root)
        assert result.returncode == 1
        assert "skills/ghost" in result.stderr

    def test_lintlayout_sl_002_dangling_command_symlink_fails(self, tmp_path: Path) -> None:
        """LINTLAYOUT-SL-002: 頂層 commands/*.md 斷掉 -> exit 1

        與 SL-001 分開：commands/ 與 skills/ 是兩條獨立的掃描路徑，
        只測其中一條會讓另一條的迴歸沒有防護。
        """
        root = _make_repo(tmp_path)
        os.symlink("../plugins/nope/commands/ghost.md", root / "commands" / "ghost.md")

        result = _run(root)
        assert result.returncode == 1
        assert "commands/ghost.md" in result.stderr


class TestSelfReference:
    def test_lintlayout_sr_001_stale_self_path_fails(self, tmp_path: Path) -> None:
        """LINTLAYOUT-SR-001: 自我引用路徑指向舊 pack -> exit 1

        模擬 pack 改名/搬動後漏改 self-locate fallback 最後一段。真實行為是靜默降級，
        故這是本 lint 存在的主要理由。
        """
        root = _make_repo(tmp_path)
        skill_md = root / "plugins" / "alpha" / "skills" / "foo" / "SKILL.md"
        skill_md.write_text(
            skill_md.read_text(encoding="utf-8")
            + "\n關鍵路徑：plugins/beta/skills/foo/scripts/bootstrap.sh\n",
            encoding="utf-8",
        )

        result = _run(root)
        assert result.returncode == 1
        assert "自我引用" in result.stderr

    def test_lintlayout_sr_002_cross_pack_reference_allowed(self, tmp_path: Path) -> None:
        """LINTLAYOUT-SR-002: 引用「別的 skill」的路徑 -> 放行（不是自我引用）

        負面對照：若少了這條，lint 會把 codex-review 引用 pr-cycle-deep 測試路徑
        這類合法跨 pack 引用誤判成違規，於是作者被迫加白名單，白名單再遮蔽真違規。
        """
        root = _make_repo(tmp_path)
        skill_md = root / "plugins" / "alpha" / "skills" / "foo" / "SKILL.md"
        skill_md.write_text(
            skill_md.read_text(encoding="utf-8") + "\n參見 plugins/beta/skills/bar/SKILL.md\n",
            encoding="utf-8",
        )

        result = _run(root)
        assert result.returncode == 0, result.stderr

    def test_lintlayout_sr_003_nonexistent_path_fails(self, tmp_path: Path) -> None:
        """LINTLAYOUT-SR-003: 引用磁碟上不存在的 plugin 路徑 -> exit 1"""
        root = _make_repo(tmp_path)
        skill_md = root / "plugins" / "alpha" / "skills" / "foo" / "SKILL.md"
        skill_md.write_text(
            skill_md.read_text(encoding="utf-8") + "\n參見 plugins/ghost/skills/nope/SKILL.md\n",
            encoding="utf-8",
        )

        result = _run(root)
        assert result.returncode == 1
        assert "不存在的路徑" in result.stderr

    def test_lintlayout_sr_004_stale_cache_key_fails(self, tmp_path: Path) -> None:
        """LINTLAYOUT-SR-004: cache key 指向別的 pack -> exit 1

        這一條抓的是 prose 裡的 `<pack>@yibi-stack`——包含 [FAIL] 訊息內的那些。
        錯誤訊息只有「已經出事」時才會被看到，平時任何測試都測不出來。
        """
        root = _make_repo(tmp_path)
        skill_md = root / "plugins" / "alpha" / "skills" / "foo" / "SKILL.md"
        skill_md.write_text(
            skill_md.read_text(encoding="utf-8")
            + "\n請執行 claude plugin install beta@yibi-stack\n",
            encoding="utf-8",
        )

        result = _run(root)
        assert result.returncode == 1
        assert "beta@yibi-stack" in result.stderr

    def test_lintlayout_sr_005_own_cache_key_allowed(self, tmp_path: Path) -> None:
        """LINTLAYOUT-SR-005: cache key 指向自己所屬 pack -> 放行"""
        root = _make_repo(tmp_path)
        skill_md = root / "plugins" / "alpha" / "skills" / "foo" / "SKILL.md"
        skill_md.write_text(
            skill_md.read_text(encoding="utf-8")
            + "\n請執行 claude plugin install alpha@yibi-stack\n",
            encoding="utf-8",
        )

        result = _run(root)
        assert result.returncode == 0, result.stderr


class TestMarketplace:
    def test_lintlayout_mp_001_missing_source_dir_fails(self, tmp_path: Path) -> None:
        """LINTLAYOUT-MP-001: marketplace 的 source 目錄不存在 -> exit 1

        模擬 `git mv plugins/<old> plugins/<new>` 但沒改 marketplace.json。
        """
        root = _make_repo(tmp_path)
        shutil.move(str(root / "plugins" / "beta"), str(root / "plugins" / "renamed"))

        result = _run(root)
        assert result.returncode == 1
        assert "source" in result.stderr

    def test_lintlayout_mp_002_name_mismatch_fails(self, tmp_path: Path) -> None:
        """LINTLAYOUT-MP-002: plugin.json 的 name 與 marketplace 登記不符 -> exit 1"""
        root = _make_repo(tmp_path)
        plugin_json = root / "plugins" / "beta" / ".claude-plugin" / "plugin.json"
        _write_json(plugin_json, {"name": "wrong-name", "version": "1.0.0"})

        result = _run(root)
        assert result.returncode == 1
        assert "wrong-name" in result.stderr

    def test_lintlayout_mp_003_unregistered_pack_fails(self, tmp_path: Path) -> None:
        """LINTLAYOUT-MP-003: 有 package.json 的 pack 未登記進 marketplace -> exit 1

        反向檢查。未登記的 pack 會被 lint_skill_scope.py 當成「外部 plugin」而豁免其
        namespace 檢查——那是個靜默破洞，不是大聲的失敗。
        """
        root = _make_repo(tmp_path)
        _make_pack(root, "orphan", ["solo"])
        os.symlink("../plugins/orphan/skills/solo", root / "skills" / "solo")

        result = _run(root)
        assert result.returncode == 1
        assert "orphan" in result.stderr


class TestVersionLockstep:
    def test_lintlayout_vl_001_version_mismatch_fails(self, tmp_path: Path) -> None:
        """LINTLAYOUT-VL-001: package.json 與 plugin.json 版本不一致 -> exit 1"""
        root = _make_repo(tmp_path)
        _write_json(
            root / "plugins" / "beta" / "package.json", {"name": "beta", "version": "9.9.9"}
        )

        result = _run(root)
        assert result.returncode == 1
        assert "9.9.9" in result.stderr


class TestConfigErrors:
    def test_lintlayout_cf_001_missing_marketplace_exits_2(self, tmp_path: Path) -> None:
        """LINTLAYOUT-CF-001: marketplace.json 缺失 -> exit 2（設定錯誤，與違規的 1 區分）

        區分 2 與 1 很重要：exit 1 代表「檢查跑完且發現問題」，exit 2 代表「檢查根本沒能跑」。
        兩者混用會讓「沒問題」與「沒檢查」在呼叫端看起來一樣。
        """
        root = _make_repo(tmp_path)
        (root / ".claude-plugin" / "marketplace.json").unlink()

        result = _run(root)
        assert result.returncode == 2

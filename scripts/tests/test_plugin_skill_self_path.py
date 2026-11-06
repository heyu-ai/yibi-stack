"""plugin 提供的 skill 不可在文件裡寫死「自己的」~/.claude/skills/<自己>/ 路徑。

背景：bump-version 這類 skill 由 plugin 提供。PR #627 之後 `make install` 不再把這些 skill 連到
`~/.claude/skills/`（會與 plugin 重複列出），於是文件裡寫的
`~/.claude/skills/<自己>/scripts/...` 在乾淨安裝下指向不存在的目錄。`make release`（透過
scripts/release-full.sh 的預設路徑）就是這樣壞掉的；同一類寫法還散在好幾個 SKILL.md。

正確寫法：SKILL.md 本文用 `${CLAUDE_SKILL_DIR}`（Claude Code 載入 skill 時展開成實際載入目錄，
repo 內 pr-retrospective 等已採用，見 test_skill_step0_loaded_dir.py）。references/ 底下的檔案不會被
展開，改寫成「skill 目錄下的 scripts/...」。會被持久化進設定檔的指令（排程 JSON）不能用
`${CLAUDE_SKILL_DIR}`，因為它展開成帶版本號的 plugin cache 路徑，plugin 一更新就失效，
改用 make install 管理的穩定路徑 ~/.agents/skills/<name>/。

只掃 plugins/ 底下的 skill：repo 根目錄 skills/ 內的實體目錄（scope: project）由
`make install-project` 同時連到兩個目錄，不受影響。

Test ID 規則見 .claude/rules/09-test-conventions.md（PSP = plugin skill self path）。
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # nosec B404
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS = REPO_ROOT / "plugins"

# 豁免：文件裡刻意保留的自我參照路徑，必須附理由。過期的豁免（檔案不存在、或已不含該路徑）
# 會讓 PSP-ST-002 失敗，避免豁免清單悄悄變成永久的洞。
EXEMPT: dict[str, str] = {
    "plugins/growth/skills/pr-retro-hard/SKILL.md": (
        "三段式備援路徑：plugin cache -> ~/.claude/skills -> repo 內相對路徑，"
        "~/.claude/skills 只是其中一段備援，找不到會繼續往下一段"
    ),
}


def _self_path_re(skill_name: str) -> re.Pattern[str]:
    """匹配 `~`、`$HOME`、`${HOME}`（可帶收尾引號，如 `"$HOME"/`）或 `/Users/<任何>` 開頭、
    指向 ~/.claude/skills/<skill_name>/ 的路徑。"""
    return re.compile(
        r"(?:~|\$HOME|\$\{HOME\}|/Users/[^/\s]+)\"?/\.claude/skills/"
        + re.escape(skill_name)
        + r"(?![\w-])"
    )


def _skill_docs() -> list[tuple[str, Path]]:
    """(skill 名稱, 文件路徑)：每個 plugin skill 的 SKILL.md 與 references/ 底下的 .md。

    用 os.walk(followlinks=True)：rule 02 記載 rglob 不跟 symlink、glob 的 `*` 不跨層，
    會悄悄漏掉巢狀 skill。
    """
    docs: list[tuple[str, Path]] = []
    for root, _dirs, files in os.walk(PLUGINS, followlinks=True):
        if "SKILL.md" not in files:
            continue
        skill_dir = Path(root)
        name = skill_dir.name
        docs.append((name, skill_dir / "SKILL.md"))
        for ref_root, _ref_dirs, ref_files in os.walk(skill_dir / "references", followlinks=True):
            docs.extend((name, Path(ref_root) / f) for f in sorted(ref_files) if f.endswith(".md"))
    return docs


def _violations() -> dict[str, list[str]]:
    """相對路徑 -> 含自我參照路徑的行（含行號）。"""
    found: dict[str, list[str]] = {}
    for name, path in _skill_docs():
        pattern = _self_path_re(name)
        hits = [
            f"{i}: {line.strip()}"
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
            if pattern.search(line)
        ]
        if hits:
            found[str(path.relative_to(REPO_ROOT))] = hits
    return found


# 偵測器的正向對照：這些必須被抓到，否則下面的「沒有違規」沒有資訊量。
_KNOWN_BAD = (
    ("bump-version", "~/.claude/skills/bump-version/scripts/bump.sh minor"),
    ("bump-version", 'python3 "$HOME/.claude/skills/bump-version/scripts/x.py"'),
    ("harness-weekly-review", '"/Users/<you>/.claude/skills/harness-weekly-review/scripts/a.py"'),
    ("plugin-cache-prune", "python3 ~/.claude/skills/plugin-cache-prune"),
    ("bump-version", "bash ${HOME}/.claude/skills/bump-version/scripts/bump.sh"),
    ("bump-version", 'bash "$HOME"/.claude/skills/bump-version/scripts/bump.sh'),
    ("bump-version", 'bash "${HOME}"/.claude/skills/bump-version/scripts/bump.sh'),
)
# 負向對照：這些是合法寫法，被誤抓會讓人學會關掉這個測試。
_KNOWN_GOOD = (
    ("learn", "~/.claude/skills/gstack/bin/gstack-slug"),
    ("bump-version", "~/.agents/skills/bump-version/scripts/bump.sh"),
    ("bump-version", '"${CLAUDE_SKILL_DIR}/scripts/bump.sh"'),
    ("bump-version", "~/.claude/skills/bump-version-extra/scripts/x"),
)


@pytest.mark.parametrize(("name", "text"), _KNOWN_BAD)
def test_psp_dt_001_detector_flags_known_bad(name: str, text: str) -> None:
    """PSP-DT-001: 偵測器必須抓到各種寫死形式（~、$HOME、/Users/<名>）。"""
    assert _self_path_re(name).search(text)


@pytest.mark.parametrize(("name", "text"), _KNOWN_GOOD)
def test_psp_dt_002_detector_ignores_legitimate_forms(name: str, text: str) -> None:
    """PSP-DT-002: 外部 gstack 路徑、~/.agents 路徑、${CLAUDE_SKILL_DIR}、同前綴的別名都不算。"""
    assert not _self_path_re(name).search(text)


def test_psp_vl_001_scan_actually_covers_the_plugin_skills() -> None:
    """PSP-VL-001: 掃描範圍的前提——找不到足夠的 skill 或漏掉已知的違規來源時要失敗。

    否則路徑寫錯、目錄改名之後，下面的 PASS 只是因為什麼都沒掃。
    """
    docs = _skill_docs()
    names = {name for name, _ in docs}
    assert len(names) >= 20, f"只掃到 {len(names)} 個 skill，掃描範圍可能壞了：{sorted(names)}"
    for expected in ("bump-version", "harness-weekly-review", "plugin-cache-prune"):
        assert expected in names, f"{expected} 不在掃描範圍內"
    assert any(p.name != "SKILL.md" for _, p in docs), "references/ 底下的 .md 沒有被掃到"


def test_psp_st_001_no_plugin_skill_hardcodes_its_own_claude_skills_path() -> None:
    """PSP-ST-001: 除明確豁免者外，plugin skill 的文件不得寫死 ~/.claude/skills/<自己>/。"""
    bad = {k: v for k, v in _violations().items() if k not in EXEMPT}
    assert not bad, (
        "這些 plugin skill 寫死了自己的 ~/.claude/skills/<名稱>/ 路徑；乾淨安裝下該目錄不存在。"
        "SKILL.md 本文改用 ${CLAUDE_SKILL_DIR}，references/ 改寫成 skill 目錄下的相對路徑，"
        "會被持久化的設定指令改用 ~/.agents/skills/<名稱>/：\n"
        + "\n".join(f"{path}\n  " + "\n  ".join(lines) for path, lines in sorted(bad.items()))
    )


def test_psp_st_003_init_commit_hook_runs_from_the_plugin_dir_without_any_install(
    tmp_path: Path,
) -> None:
    """PSP-ST-003: bump-version SKILL.md 叫使用者從 skill 目錄執行 init-commit-hook.sh，
    所以它必須以自己的位置找 hook 來源，不能預設去 $HOME/.agents/skills/bump-version
    （只有跑過 make install 的機器才有）。HOME 指向空目錄就是沒裝過的狀態。"""
    script = REPO_ROOT / "plugins/dev-cycle/skills/bump-version/scripts/init-commit-hook.sh"
    target = tmp_path / "target-repo"
    target.mkdir()
    empty_home = tmp_path / "empty-home"
    empty_home.mkdir()
    # pre-commit 的 hook context 會 export GIT_DIR 等變數，蓋掉 tmp repo（rule 17）
    git_keys = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "SKILL_DIR")
    env = {k: v for k, v in os.environ.items() if k not in git_keys}
    env["HOME"] = str(empty_home)
    subprocess.run(  # nosec B603 B607
        ["git", "init", "-q", str(target)], check=True, capture_output=True, timeout=30, env=env
    )

    result = subprocess.run(  # nosec B603 B607
        ["bash", str(script)],
        cwd=target,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (target / ".git/hooks/commit-msg").is_file()
    assert (target / ".claude/hooks/commit-msg-parse.py").is_file()
    # 沒有任何東西寫進（空的）HOME：安裝只動目標 repo
    assert list(empty_home.iterdir()) == []


_WEEKLY_REVIEW_SKILL = PLUGINS / "harness/skills/harness-weekly-review/SKILL.md"
_SCHEDULE_HEADING = "## 排程（每週自動量測，不含 LLM 判讀）"
_STABLE_SCRIPT_RE = re.compile(
    r"^(?:~|/Users/[^/\s]+)/\.agents/skills/harness-weekly-review/scripts/"
)


def _section(text: str, heading: str) -> str:
    """擷取 `heading`（整行比對）到下一個 `## ` 標題之間的內容；找不到或不唯一就失敗。

    code fence 內的 `## ` 不算標題。不可回傳空字串或退回整檔，否則後面的斷言會變成空轉。
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line == heading]
    assert len(starts) == 1, f"解析前提不成立：標題 {heading!r} 出現 {len(starts)} 次"
    body: list[str] = []
    in_fence = False
    for line in lines[starts[0] + 1 :]:
        if line.startswith("```"):
            in_fence = not in_fence
        elif not in_fence and line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body)


def test_psp_st_004_schedule_json_uses_stable_agents_path_not_skill_dir() -> None:
    """PSP-ST-004: harness-weekly-review 的排程 JSON 會被持久化進 .runtime/schedules.json，
    所以 command 裡的腳本必須是 make install 管理的穩定路徑 ~/.agents/skills/<自己>/，
    不能用 ${CLAUDE_SKILL_DIR}（展開成帶版本號的 plugin cache 路徑，plugin 更新後即失效）。

    只掃該節的 json code fence：說明散文與 bash fence 合理地提到 ${CLAUDE_SKILL_DIR}。
    """
    section = _section(_WEEKLY_REVIEW_SKILL.read_text(encoding="utf-8"), _SCHEDULE_HEADING)
    fences = re.findall(r"^```json\n(.*?)^```", section, flags=re.DOTALL | re.MULTILINE)
    assert fences, "排程一節沒有任何 json code fence，解析前提不成立"

    stable_scripts: list[str] = []
    for fence in fences:
        assert "CLAUDE_SKILL_DIR" not in fence, "排程 JSON 不可使用 ${CLAUDE_SKILL_DIR}"
        assert ".claude/skills/" not in fence, "排程 JSON 不可使用 ~/.claude/skills/"
        command = json.loads(fence).get("command")
        assert isinstance(command, list) and command, "排程 JSON 缺少 command 陣列"
        stable_scripts += [arg for arg in command if _STABLE_SCRIPT_RE.match(str(arg))]
    assert stable_scripts, (
        "排程 JSON 的 command 沒有指向 ~/.agents/skills/harness-weekly-review/scripts/"
    )


def test_psp_st_002_exemptions_are_not_stale() -> None:
    """PSP-ST-002: 每個豁免都必須仍然存在、且仍含自我參照路徑，否則就該移除。"""
    found = _violations()
    for rel, reason in EXEMPT.items():
        assert (REPO_ROOT / rel).is_file(), f"豁免的檔案不存在：{rel}（{reason}）"
        assert rel in found, f"豁免已過期，該檔案不再含自我參照路徑，請移除：{rel}（{reason}）"

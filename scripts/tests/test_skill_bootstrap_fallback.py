"""BOOTSTRAP-* tests：SKILL.md 的 self-locate fallback 最後一段必須指向自己所在的目錄。

**為什麼需要執行期測試，而不是只靠 lint_plugin_layout.py 的靜態檢查**

靜態檢查比對字串，抓得到 typo 與過期的 pack 名。抓不到的是「整條 fallback 鏈的語意壞掉」
——例如判斷式與賦值指向不同路徑、或 `-r` 檢查的檔名與實際 script 名不符。那類缺陷在靜態
層面完全合法。

**這些 skill 的三段 fallback 實際上只有兩段可用**

  tier-1  plugin cache（讀 ~/.claude/plugins/installed_plugins.json 的 <pack>@yibi-stack）
  tier-2  $HOME/.claude/skills/<name>/scripts/...   <-- 死的
  tier-3  plugins/<pack>/skills/<name>/scripts/...  <-- 唯一備援

tier-2 之所以是死的：`make install` 只為「頂層 skills/ 有 symlink」的 skill 建
`~/.claude/skills/<name>`，而 pr-retrospective / pr-control-log / pr-cycle-fast 三者都是
plugin-only（無頂層 symlink）。所以那一段從來不會命中。多出來的那層讓人以為還有餘裕，
實際上一旦 tier-1 miss 就直接落到 tier-3。

本測試以「空 HOME」強制 tier-1 與 tier-2 必定 miss，讓 tier-3 成為唯一路徑，再斷言它
解析到的目錄**等於該 SKILL.md 自己所在的目錄**。

期望值由檔案自身位置推導，不寫死 pack 名——所以 pack 改名後測試依然成立（不需要跟著改），
但只要 fallback 裡的路徑沒跟著改名，就會立刻紅。這正是要抓的那個缺陷。
"""

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"

_BASH_FENCE = re.compile(r"^```bash\s*\n(.*?)\n```", re.DOTALL | re.MULTILINE)
# 例：CL_ROOT="plugins/pr-flow/skills/pr-control-log"
_TIER3_ASSIGN = re.compile(
    r'(?P<var>[A-Z][A-Z0-9_]*)="(?P<path>plugins/[a-z0-9-]+/skills/[a-z0-9-]+)"'
)


def _discover() -> list[tuple[Path, str, str]]:
    """找出所有含 tier-3 in-repo fallback 的 SKILL.md。

    回傳 [(SKILL.md 路徑, 變數名, 該 skill 自己的相對目錄), ...]。
    動態探索而非寫死清單：日後有 skill 採用同一 pattern 會自動納入保護。
    """
    found: list[tuple[Path, str, str]] = []
    for skill_md in sorted(PLUGINS_DIR.glob("*/skills/**/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        for block in _BASH_FENCE.findall(text):
            m = _TIER3_ASSIGN.search(block)
            if m:
                own_dir = str(skill_md.parent.relative_to(REPO_ROOT))
                found.append((skill_md, m.group("var"), own_dir))
                break
    return found


_CASES = _discover()


def test_bootstrap_dc_001_discovery_is_not_empty() -> None:
    """BOOTSTRAP-DC-001: 探索到至少一個 fallback 區塊

    沒有這條，探索 regex 一旦過期就會靜默地把整個測試檔變成零個案例——
    全綠，且什麼都沒驗證。這是「前提不成立時必須 FAIL」的落實。
    """
    assert _CASES, (
        "在 plugins/*/skills/**/SKILL.md 找不到任何 tier-3 fallback 區塊。"
        "若 fallback 寫法已改變，請更新 _TIER3_ASSIGN；不要讓本測試靜默空轉。"
    )


def _extract_block(skill_md: Path, var: str) -> str:
    text = skill_md.read_text(encoding="utf-8")
    for block in _BASH_FENCE.findall(text):
        if _TIER3_ASSIGN.search(block) and f"{var}=" in block:
            return block
    raise AssertionError(f"{skill_md} 找不到含 {var} 的 bash 區塊")


def _fake_bin(tmp_path: Path) -> Path:
    """提供 mycelium stub，讓 fallback 區塊的 CLI 存在性檢查通過。

    測的是路徑解析，不是 CLI 能力；缺了 stub 區塊會在解析成功後才 exit 1，
    使失敗原因無法歸因。
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "mycelium"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


@pytest.mark.parametrize(
    ("skill_md", "var", "own_dir"),
    _CASES,
    ids=[c[0].parent.name for c in _CASES],
)
def test_bootstrap_t3_001_resolves_to_own_directory(
    skill_md: Path, var: str, own_dir: str, tmp_path: Path
) -> None:
    """BOOTSTRAP-T3-001: 空 HOME 下（強制走 tier-3），fallback 解析到 skill 自己的目錄

    HOME 指向空的 tmp_path：
      - tier-1 讀不到 installed_plugins.json -> 空字串 -> miss
      - tier-2 $HOME/.claude/skills/<name>/ 不存在 -> miss
      - tier-3 成為唯一路徑
    """
    block = _extract_block(skill_md, var)
    script = f'{block}\necho "__RESOLVED__=${var}"\n'

    empty_home = tmp_path / "home"
    empty_home.mkdir()
    env = dict(os.environ)
    env["HOME"] = str(empty_home)
    env["PATH"] = f"{_fake_bin(tmp_path)}:{env['PATH']}"

    result = subprocess.run(
        ["bash", "-c", script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, (
        f"{skill_md.relative_to(REPO_ROOT)} 的 fallback 在空 HOME 下失敗"
        f"（tier-3 沒命中）。stderr:\n{result.stderr}"
    )
    m = re.search(r"__RESOLVED__=(.*)", result.stdout)
    assert m, f"取不到 {var} 的值。stdout:\n{result.stdout}"
    resolved = m.group(1).strip()
    assert resolved == own_dir, (
        f"{skill_md.relative_to(REPO_ROOT)} 的 tier-3 fallback 指向 '{resolved}'，"
        f"但這個 skill 實際住在 '{own_dir}'。"
        f"pack 改名或搬動後漏改此路徑會靜默降級——三段全 miss，"
        f"然後 [FAIL] 訊息叫使用者去安裝一個已不存在的 pack。"
    )

"""BOOTSTRAP-* tests：SKILL.md 的 self-locate fallback 最後一段必須指向自己所在的目錄。

**為什麼需要執行期測試，而不是只靠 lint_plugin_layout.py 的靜態檢查**

靜態檢查比對字串，抓得到 typo 與過期的 pack 名。抓不到的是「整條 fallback 鏈的語意壞掉」
——例如判斷式與賦值指向不同路徑、或 `-r` 檢查的檔名與實際 script 名不符。那類缺陷在靜態
層面完全合法。

**三個 skill 的三段 fallback 實際上只有兩段可用（skill-form）**

  tier-1  plugin cache（讀 ~/.claude/plugins/installed_plugins.json 的 <pack>@yibi-stack）
  tier-2  $HOME/.claude/skills/<name>/scripts/...   <-- 死的
  tier-3  plugins/<pack>/skills/<name>/scripts/...  <-- 唯一備援

tier-2 之所以是死的：`make install` 只為「頂層 skills/ 有 symlink」的 skill 建
`~/.claude/skills/<name>`，而 pr-retrospective / pr-control-log / pr-cycle-fast 三者都是
plugin-only（無頂層 symlink）。所以那一段從來不會命中。多出來的那層讓人以為還有餘裕，
實際上一旦 tier-1 miss 就直接落到 tier-3。

**第四個案例（spectra-amplifier）是不同形狀：pack-root fallback，機制也不同**

  tier-1  ${CLAUDE_PLUGIN_ROOT}                      <-- Claude Code 執行期即時環境變數，非死
  tier-2  plugin cache（同上，經 SDD_CACHED 變數）
  tier-3  plugins/<pack>                             <-- pack 根目錄，不是 skill 子目錄

不要把「skill-form 的 tier-2 是死的」這個結論套用到這個案例——`CLAUDE_PLUGIN_ROOT` 是
Claude Code 以 installed plugin 身分呼叫 skill 時設定的即時變數，機制與 `$HOME/.claude/skills/`
完全不同，未經查證不應假設它也是死的。本測試只驗證「空 HOME 且 unset CLAUDE_PLUGIN_ROOT」時
tier-3 仍能正確解析，不對 tier-1/tier-2 的死活下判斷。

本測試以「空 HOME」（並明確 unset `CLAUDE_PLUGIN_ROOT`，不依賴呼叫環境恰好沒設定它）強制
tier-1 與 tier-2 必定 miss，讓 tier-3 成為唯一路徑，再斷言它解析到的目錄**等於該 SKILL.md
自己所在的目錄（skill-form）或自己所屬的 pack 根目錄（pack-root form）**。

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
# skill-form 例：CL_ROOT="plugins/pr-flow/skills/pr-control-log"
_TIER3_ASSIGN = re.compile(
    r'(?P<var>[A-Z][A-Z0-9_]*)="(?P<path>plugins/[a-z0-9-]+/skills/[a-z0-9-]+)"'
)
# pack-root 形狀例：SDD_ROOT="plugins/sdd"（無 /skills/ 段——自我定位到整個 pack 而非
# 特定 skill 子目錄）。字元類 [a-z0-9-]+ 不含 `/`，故不會與上面的 skill-form 重疊比對到
# 半截路徑：skill-form 字串在 pack 名之後還有 `/skills/...`，會讓這個 regex 的收尾 `"`
# 找不到緊接的引號而不匹配；`_discover()` 也把 _TIER3_ASSIGN 排在前面優先比對，雙重保險。
_PACKROOT_ASSIGN = re.compile(r'(?P<var>[A-Z][A-Z0-9_]*)="(?P<pack>plugins/[a-z0-9-]+)"')

# 每個必須被納入 discovery 的 skill 都在 SKILL.md 內含 tier-1 cache-key 探測
# `<pack>@yibi-stack`——這是「此 skill 使用三段 self-locate pattern」的獨立標記，
# 不依賴 _TIER3_ASSIGN/_PACKROOT_ASSIGN 本身，故可用來偵測 discovery 是否掉案例
# （BOOTSTRAP-DC-001 的真正防線，而非只靠「非空」）。
_CACHE_KEY_PROBE = re.compile(r"[a-z0-9-]+@yibi-stack")


def _discover() -> list[tuple[Path, str, str]]:
    """找出所有含 tier-3 in-repo fallback 的 SKILL.md。

    回傳 [(SKILL.md 路徑, 變數名, 該 self-locate 自己的相對目錄), ...]。
    skill-form 的自己目錄是 skill 子目錄本身；pack-root form 的自己目錄是 pack 根目錄
    （SKILL.md 往上三層：<skill>/SKILL.md -> <skill> -> skills -> <pack>）。
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
            m = _PACKROOT_ASSIGN.search(block)
            if m:
                own_dir = str(skill_md.parents[2].relative_to(REPO_ROOT))
                found.append((skill_md, m.group("var"), own_dir))
                break
    return found


def _expected_skills() -> set[str]:
    """獨立於 _discover() 的下限訊號：哪些 SKILL.md 在**某個 bash fence 內**含 tier-1
    cache-key 探測。用來斷言 discovery 沒有漏掉任何一個，而不只是斷言「非空」。

    刻意只用 `_BASH_FENCE` + `_CACHE_KEY_PROBE`，不引用 `_TIER3_ASSIGN` / `_PACKROOT_ASSIGN`
    ——若這裡也依賴那兩個 regex，一旦它們被改壞（例如收窄 var-name 字元類），expected 集合
    會跟 discovered 集合同步縮水，比對仍然相等，測試因錯誤理由通過。已用 mutation 驗證過
    這個陷阱：first draft 在此處多寫了 `and (_TIER3_ASSIGN.search(...) or _PACKROOT_ASSIGN...)`，
    突變 _TIER3_ASSIGN 後兩個集合一起縮水而測試仍綠，直到拿掉那個 and 子句才被正確殺死。

    只看「fence 內」而非全文，是為了排除 troubleshooting 表格列裡提到
    `claude plugin install <pack>@yibi-stack` 的 prose 提示（如 mob-code-review-only 的
    FAQ 行）——那是安裝指令，不是 self-locate 的 tier-1 探測。已對現有 33 個 SKILL.md
    掃描確認：只有這裡列的四個在 bash fence 內含 cache-key 探測，其餘含 `@yibi-stack`
    字串的 skill（如 mob-code-review-only）命中都在 fence 外，正確被排除。
    """
    names: set[str] = set()
    for skill_md in PLUGINS_DIR.glob("*/skills/**/SKILL.md"):
        text = skill_md.read_text(encoding="utf-8")
        for block in _BASH_FENCE.findall(text):
            if _CACHE_KEY_PROBE.search(block):
                names.add(skill_md.parent.name)
                break
    return names


_CASES = _discover()


def test_bootstrap_dc_001_discovery_matches_expected_skill_set() -> None:
    """BOOTSTRAP-DC-001: discovery 找到的 skill 名稱集合，必須等於獨立訊號算出的期望集合

    只斷言「非空」防不了「掉了 1 個或 2 個仍非空」——那正是本測試存在的理由卻沒做到的事
    （R1/R2 mob review 三方獨立用不同 mutation 證明：收窄 var-name regex、改單引號、
    加尾斜線都能讓 discovery 靜默縮水而 `assert _CASES` 仍通過）。改為比對**期望集合**，
    掉任何一個都會大聲失敗；新增 skill 時 `_expected_skills()` 會自動納入，不需要手動維護清單。
    """
    discovered = {skill_md.parent.name for skill_md, _, _ in _CASES}
    expected = _expected_skills()
    assert expected, (
        "_expected_skills() 找不到任何含 cache-key 探測的 SKILL.md——"
        "_CACHE_KEY_PROBE 可能已過期；不要讓本測試靜默空轉。"
    )
    assert discovered == expected, (
        f"discovery 找到 {sorted(discovered)}，但獨立訊號算出應有 {sorted(expected)}。"
        f"缺少：{sorted(expected - discovered)}；多出：{sorted(discovered - expected)}。"
        f"若是新增 skill，請確認其 tier-3 賦值符合 _TIER3_ASSIGN 或 _PACKROOT_ASSIGN 的形狀。"
    )


def _extract_block(skill_md: Path, var: str) -> str:
    text = skill_md.read_text(encoding="utf-8")
    for block in _BASH_FENCE.findall(text):
        if f"{var}=" in block and (_TIER3_ASSIGN.search(block) or _PACKROOT_ASSIGN.search(block)):
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
      - skill-form tier-1 讀不到 installed_plugins.json -> 空字串 -> miss
      - skill-form tier-2 $HOME/.claude/skills/<name>/ 不存在 -> miss
      - pack-root form tier-1 `${CLAUDE_PLUGIN_ROOT}` 明確 unset -> miss
        （不依賴呼叫環境剛好沒設定它——這是 Claude Code 執行期即時變數，測試環境跑在
        實際 session 裡時可能被設定，必須主動清除才能保證強制走到 tier-3）
      - tier-3 成為唯一路徑
    """
    block = _extract_block(skill_md, var)
    script = f'{block}\necho "__RESOLVED__=${var}"\n'

    empty_home = tmp_path / "home"
    empty_home.mkdir()
    env = dict(os.environ)
    env["HOME"] = str(empty_home)
    env["PATH"] = f"{_fake_bin(tmp_path)}:{env['PATH']}"
    env.pop("CLAUDE_PLUGIN_ROOT", None)

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

"""PRECOMMIT-* test：`lint-plugin-layout` / `lint-skill-bash` 兩個 pre-commit hook
必須設定 `always_run: true`。

對應 D9：pre-commit 用 `--diff-filter=ACMRTUXB`（原始碼註解 `# Everything except
for D`）計算 staged-file 清單，不含 `D`。deletion-only 的 staged commit（例如
`git rm plugins/<pack>/commands/<cmd>.md`）不會匹配任何 `files:` pattern，讓
`files:`-gated hook 完全不觸發——而這正是兩個 hook 要擋的「plugin 端漏改頂層
symlink」失誤最常見的形狀（搬動/刪除 pack 時）。已用真實 `pre-commit run` 端對端
驗證：修復前的 `files:` config 回報 `(no files to check) Skipped`，加上
`always_run: true` 後正確 `Failed` 並指出 dangling symlink。

**`always_run: true` 本身就足以修復 D9，不需要移除 `files:`**——已讀
`pre_commit/commands/run.py:168` 的原始碼確認：`elif not filenames and not
hook.always_run:` 這個 skip 判斷式要求**兩個條件同時成立**才會跳過，
`always_run: true` 讓判斷式恆為 False，與 `files:` 是否存在或匹配結果無關。
本檔的 `.pre-commit-config.yaml` 選擇同時移除 `files:`，是因為兩個 hook 都
`pass_filenames: false`（不消費 `files:` 算出的候選清單），留著只會誤導未來的
讀者以為它還在發揮篩選作用；這是保持精簡的選擇，不是修復 D9 的必要條件。

本測試不重跑端對端驗證（成本較高，且 D9 的行為本質是 pre-commit 自身既有的
`--diff-filter` 語意，不是我們程式碼的行為）——只鎖住 `always_run: true` 不被
悄悄拿掉。

**刻意不用 `yaml.safe_load()`**：`pyyaml` 不是本 repo 宣告的依賴（`pyproject.toml`
無此項），目前只是透過 pre-commit 自身的依賴鏈間接存在於 venv——依賴一個未宣告的
transitive package，在乾淨環境或 pre-commit 版本變動時會靜默壞掉。改用逐行文字掃描，
與本 repo `lint_rule_frontmatter.py` / `lint_skill_scope.py` 一致的「regex-based
parsing，不依賴 YAML 套件」慣例（`.claude/rules/11-skill-authoring.md`）。
"""

import re
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / ".pre-commit-config.yaml"
_GUARDED_HOOK_IDS = ("lint-plugin-layout", "lint-skill-bash")

# 抓「- id: <hook_id>」到下一個「- id:」（或檔案結尾）之間的區塊——足以判斷
# 該 hook 的設定裡有沒有 always_run: true，不需要完整 YAML 解析。
_HOOK_BLOCK_RE_TMPL = r"-\s+id:\s*{}\b(.*?)(?=\n\s*-\s+id:|\Z)"


def _hook_block(config_text: str, hook_id: str) -> str | None:
    m = re.search(_HOOK_BLOCK_RE_TMPL.format(re.escape(hook_id)), config_text, re.DOTALL)
    return m.group(1) if m else None


def test_precommit_dc_001_guarded_hooks_use_always_run() -> None:
    config_text = _CONFIG_PATH.read_text(encoding="utf-8")

    for hook_id in _GUARDED_HOOK_IDS:
        block = _hook_block(config_text, hook_id)
        assert block is not None, f"在 .pre-commit-config.yaml 找不到 hook id：{hook_id}"
        assert re.search(r"always_run:\s*true\b", block), (
            f"{hook_id} 必須設定 always_run: true——pre-commit 的 skip 判斷式"
            f"（commands/run.py: `elif not filenames and not hook.always_run`）"
            f"只有在 always_run 為 false 時，才會因為 deletion-only staged commit"
            f"（--diff-filter=ACMRTUXB 不含 D）算出空候選清單而跳過整個 hook——"
            f"這正是本 hook 要擋的失誤最常見的形狀（搬動/刪除 plugin 端漏改頂層 symlink）。"
        )

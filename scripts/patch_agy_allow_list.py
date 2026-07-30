#!/usr/bin/env python3
"""冪等地將 agy（Antigravity CLI）相關指令加入 ~/.claude/settings.json allow list。

只允許各模式專屬 script 的絕對路徑（review / consult / pr-cycle-deep 的 mob review
內部呼叫），不使用裸 `Bash(agy:*)`——那是動詞級萬用字元，涵蓋任何 agy 指令與旗標組合
（見 .claude/rules/16-allowlist-hygiene.md Red Flag 2）。舊版寫入的裸萬用字元與已改名
的 script 路徑會在這裡被移除，讓既有安裝跟著收斂。
"""

import json
import os
import pathlib
import shutil
import sys

SETTINGS_PATH = pathlib.Path.home() / ".claude" / "settings.json"

_SKILLS_DIR = pathlib.Path.home() / ".agents" / "skills"
_AGY_REVIEW_SCRIPT = str(_SKILLS_DIR / "agy-review" / "scripts" / "run.sh")
_AGY_CONSULT_SCRIPT = str(_SKILLS_DIR / "agy-consult" / "scripts" / "consult.sh")
_PR_CYCLE_DEEP_SCRIPTS = [
    str(_SKILLS_DIR / "pr-cycle-deep" / "scripts" / "agy-r1-stage1.sh"),
    str(_SKILLS_DIR / "pr-cycle-deep" / "scripts" / "agy-r1-stage2.sh"),
    str(_SKILLS_DIR / "pr-cycle-deep" / "scripts" / "agy-r2.sh"),
]

# run.sh 帶尾端 `:*`（吃位置參數：mode/base/instruction）。consult.sh 與 pr-cycle-deep 的
# 3 支 subagent script 都用 exact-match、不帶萬用字元——consult.sh 故意設計成不吃任何參數
# （固定讀 $CLAUDE_JOB_DIR/agy-consult-question.txt，見 SKILL.md），因為帶 `:*` 的話允許
# 任意參數，會讓「讀取任意檔案內容再傳給外部 agy」變成被預先核准、免確認的原語
# （PR #367 mob review Critical，Round 2 發現）；pr-cycle-deep 的 3 支則是依 SKILL.md
# 呼叫方式一律無參數（見各 SKILL.md 的 GEMINI_ALLOW_LIST 檢查）。
ENTRIES_TO_ADD = [
    f"Bash(bash {_AGY_REVIEW_SCRIPT}:*)",
    f"Bash(bash {_AGY_CONSULT_SCRIPT})",
    *(f"Bash(bash {p})" for p in _PR_CYCLE_DEEP_SCRIPTS),
]

# 舊版（改名前）寫入的項目：裸萬用字元 + 指向已消失路徑 (~/.agents/skills/agy/scripts/run.sh) 的絕對路徑。
_OLD_AGY_SCRIPT = str(_SKILLS_DIR / "agy" / "scripts" / "run.sh")
ENTRIES_TO_REMOVE = [
    "Bash(agy:*)",
    f"Bash(bash {_OLD_AGY_SCRIPT}:*)",
]


def main(settings_path: pathlib.Path = SETTINGS_PATH) -> None:
    if not settings_path.is_file():
        print(
            f"  [FAIL] {settings_path} 不存在 — 請先啟動 Claude Code 以產生設定檔，再重跑 make patch-agy-allow-list",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"  [FAIL] settings.json 格式錯誤：{e}", file=sys.stderr)
        sys.exit(1)
    perms = data.setdefault("permissions", {})
    if not isinstance(perms, dict):
        perms = {}
        data["permissions"] = perms
    allow = perms.get("allow")
    if not isinstance(allow, list):
        allow = []
        perms["allow"] = allow

    # 過濾整個清單移除所有出現次數，而不是逐一 .remove()（只移除第一個匹配項，
    # 重複項目會殘留——實測驗證過的 bug，見 PR #367 mob review）。
    original_allow = list(allow)
    allow[:] = [entry for entry in allow if entry not in ENTRIES_TO_REMOVE]
    removed = sorted({entry for entry in ENTRIES_TO_REMOVE if entry in original_allow})

    added = []
    for entry in ENTRIES_TO_ADD:
        if entry not in allow:
            allow.append(entry)
            added.append(entry)

    if added or removed:
        tmp = settings_path.with_name("settings.json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        shutil.copymode(settings_path, tmp)
        os.replace(tmp, settings_path)
        for entry in removed:
            print(f"  [OK] Removed (over-broad, migrated to per-script entries): {entry}")
        for entry in added:
            print(f"  [OK] Added: {entry}")
    else:
        print("  [OK] agy allow list entries already present")


if __name__ == "__main__":
    main()

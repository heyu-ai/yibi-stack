"""pr-retrospective SKILL.md Step 4b 的三個契約錨點測試（issue #373）。

issue #373 在 yibi-mvp PR #1169 的 `/pr-retro` 實跑中踩到三個問題，全部落在 Step 4b：

1. recurrence 的 `--confidence` +1 規則指向 Step 5 的查詢，但 Step 5 在寫入之後，所以
   照 runbook 順序執行時永遠套不上，事後也沒有回填路徑。
2. `lessons add` 是無條件 INSERT，範本沒帶 `--skip-if-exists`，寫到一半死掉的 script
   照通用指示重跑會產生重複 lesson。
3. 範本呼叫端用雙引號傳字面值，insight 內文含 `$` 時在 `set -euo pipefail` 下炸掉。

這三項都是**散文層**的契約——SKILL.md 是 agent 的執行介面，改壞了不會有任何 runtime
訊號。本檔把修法轉成對真實檔案內容的斷言，讓回歸會變紅而不是靜默失效。

每個測試都以 red-first 驗證過：移除對應的 SKILL.md 改動後該測試轉紅（見 PR 描述）。

Test ID 規則見 .claude/rules/09-test-conventions.md。
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_MD = REPO_ROOT / "plugins" / "growth" / "skills" / "pr-retrospective" / "SKILL.md"


def _skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _step_4b_body(text: str) -> str:
    """截出 Step 4b 到 Step 5 之間的內容。

    斷言限定在這個區間，避免測試被檔案別處剛好出現的同名字串矇混過關——那正是
    issue #373 這類「文件說了但沒接上」的缺陷會鑽的洞。
    """
    start = text.index("### Step 4b")
    end = text.index("### Step 5 ", start)
    return text[start:end]


def _add_lesson_code_block(text: str) -> str:
    """截出 Step 4b 裡 `add_lesson` 範本那個 bash code fence 的內容。"""
    body = _step_4b_body(text)
    fences = re.findall(r"```bash\n(.*?)```", body, flags=re.DOTALL)
    matching = [f for f in fences if "add_lesson()" in f]
    assert len(matching) == 1, (
        f"Step 4b 應恰有一個含 add_lesson() 定義的 bash code fence，實際 {len(matching)} 個"
    )
    return matching[0]


def _executable_lines(code: str) -> str:
    """剝掉 bash 註解，只留真正會執行的部分。

    需要這一層是因為突變驗證抓到：直接對整段 code fence 斷言 `--skip-if-exists`，會配到
    解釋它的那行註解，於是把旗標從賦值拿掉後測試照樣綠——PASS 的理由是假的。
    """
    return "\n".join(line for line in code.splitlines() if not line.lstrip().startswith("#"))


# --- RETRO4B-DT-001：recurrence 查詢必須前置於 confidence 決定，且理由寫明 ---


def test_retro4b_dt_001_recurrence_lookup_is_front_loaded() -> None:
    """RETRO4B-DT-001: Step 4b 內含 recurrence 前置查詢，且不再把 +1 委給 Step 5 Q5"""
    body = _step_4b_body(_skill_text())

    # 斷言 `**` 前綴的**標題本身**，不是裸字串——上方「見下方『recurrence 前置查詢』」的交叉引用
    # 也含同一個詞，只斷言裸字串的話，把整個段落刪掉測試照樣綠（突變驗證實測會存活）。
    assert "**recurrence 前置查詢" in body, (
        "Step 4b 必須自帶 recurrence 前置查詢**段落**；委給 Step 5 Q5 的話寫入時還不知道有沒有 recurrence"
    )
    # 查詢指令本身要在 Step 4b 區間內，否則只是空談
    assert "mycelium lessons search" in body, (
        "recurrence 前置查詢必須給出實際可跑的 lessons search 指令"
    )

    # 反向：舊措辭「若 Step 5 Q5 查歷史發現此教訓重複犯」把時序指錯了，不得殘留
    assert "若 Step 5 Q5 查歷史發現此教訓重複犯" not in body, (
        "舊的 +1 措辭把 recurrence 查詢指向 Step 5（寫入之後），必須移除"
    )


def test_retro4b_dt_002_recurrence_note_states_why_post_hoc_fix_is_impossible() -> None:
    """RETRO4B-DT-002: 前置理由須寫明 active lesson 無法原地改分數（否則讀者會想改回去）"""
    body = _step_4b_body(_skill_text())

    # `finalize` 只吃 parked→active，是「事後補不回來」的關鍵事實；沒有它，
    # 未來維護者會覺得前置查詢只是風格偏好而把它移回 Step 5。
    assert "finalize" in body, "必須說明 lessons finalize 為何不能用來事後補分數"
    assert "compare-and-set" in body


# --- RETRO4B-DT-003：範本依 state 二擇一，不得無條件併用互斥旗標 ---


def test_retro4b_dt_003_active_path_uses_skip_if_exists() -> None:
    """RETRO4B-DT-003: active 路徑帶 --skip-if-exists，讓寫到一半的 script 可安全重跑"""
    # 先剝註解：解釋 --skip-if-exists 的那行註解也含這個字串，直接對整段斷言的話，
    # 把旗標從賦值拿掉測試照樣綠（突變驗證實測會存活）。
    code = _executable_lines(_add_lesson_code_block(_skill_text()))

    assert "--skip-if-exists" in code, (
        "active 路徑必須帶 --skip-if-exists，否則重跑會產生重複 lesson"
    )
    assert "--park" in code, "park 路徑仍須保留 --park"


def test_retro4b_dt_004_park_and_skip_if_exists_are_mutually_exclusive() -> None:
    """RETRO4B-DT-004: 兩個互斥旗標必須在同一個 if/else 分支，不可同時送出

    `tasks/mycelium/cli.py` 對 `--park` + `--skip-if-exists` 直接 raise
    `--park 與 --skip-if-exists 不可同時使用`。issue #373 原文建議「範本預設帶
    --skip-if-exists」，照字面實作會讓每一條 park 路徑乾淨失敗——所以修法是依 state 分支。
    """
    code = _add_lesson_code_block(_skill_text())

    # 兩者必須由同一個變數承載（else 分支），而不是各自獨立的陣列各自附加
    assert "state_flag=(--park)" in code
    assert "state_flag=(--skip-if-exists)" in code
    assert "else" in code, "必須是 if/else 二擇一，不可兩個 flag 各自無條件附加"

    # 反向：舊的獨立 park_flag 陣列若殘留，代表 else 分支沒接上
    assert "park_flag=(--park)" not in code, "舊的獨立 park_flag 已由 state_flag 的 if/else 取代"


def test_retro4b_dt_005_mutual_exclusion_is_documented_in_prose() -> None:
    """RETRO4B-DT-005: 互斥性須寫在**散文**裡，不只是 code fence 內的一行註解

    刻意剝掉 code fence 再斷言：範本裡的註解只有正在讀那段 bash 的人看得到，而會把
    `--skip-if-exists` 提到 if/else 之外的維護者，往往是先讀散文決定要改什麼。這也讓本測試
    與 DT-004（讀 code fence）成為兩個可被獨立突變殺死的宣稱，而不是同一句話的兩次斷言。
    """
    body = _step_4b_body(_skill_text())
    prose = re.sub(r"```bash\n.*?```", "", body, flags=re.DOTALL)

    assert "互斥" in prose, "必須在散文裡寫明 --park 與 --skip-if-exists 互斥"
    assert "cli.py" in prose, "互斥宣稱須在散文裡指向實際強制它的程式碼位置"


# --- RETRO4B-DT-006：範本呼叫端一律單引號 ---


def test_retro4b_dt_006_call_site_uses_single_quotes() -> None:
    """RETRO4B-DT-006: add_lesson 呼叫端的 {{placeholder}} 一律單引號，避免 $ 觸發參數展開"""
    code = _add_lesson_code_block(_skill_text())

    placeholders = re.findall(r"""(["'])(\{\{.*?\}\})\1""", code)
    assert placeholders, "範本呼叫端應有被引號包住的 {{placeholder}} 參數"

    double_quoted = [p for quote, p in placeholders if quote == '"']
    assert not double_quoted, (
        "呼叫端字面值不可用雙引號——insight 含 $ 時會觸發參數展開並在 set -u 下中止 script。"
        f"仍為雙引號的：{double_quoted}"
    )


def test_retro4b_dt_007_function_body_keeps_double_quotes_for_real_variables() -> None:
    """RETRO4B-DT-007: 函式內部的真變數展開維持雙引號（單引號會讓變數不展開，是相反的 bug）"""
    code = _add_lesson_code_block(_skill_text())

    for expansion in ('"$key"', '"$insight"', '"$ORIG_PROJECT"'):
        assert expansion in code, (
            f"{expansion} 必須維持雙引號——這些是真的變數展開，改單引號會傳出字面值"
        )


def test_retro4b_dt_008_single_quote_escape_hatch_is_documented() -> None:
    """RETRO4B-DT-008: 須說明內文本身含單引號時的做法，否則讀者會就地硬拗跳脫"""
    body = _step_4b_body(_skill_text())
    assert "唯一例外" in body and "含單引號" in body, (
        "單引號規則必須交代內文含單引號時的替代做法（寫進檔案再讀 / 改寫措辭）"
    )

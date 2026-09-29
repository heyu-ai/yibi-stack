# Prompt Audit — 2026-09-28

以 `/claude-api prompt-audit` 流程稽核 yibi-stack 的 prompt surface。提案 diff 在分支
`worktree-prompt-audit-2026-09-28`（base `3cc9f48`），這份報告是分支的第一個 commit，其餘 commit
就是提案修改；可以整支取用，也可以 `git checkout <branch> -- <path>` 逐檔挑。

## 前提假設（Step 0）

- **範圍**：整個 working directory 的 prompt surface（未指定檔案）。沒有讀
  `~/.claude/`、`.claude/settings*.json`、`.mcp.json`、`.env`。使用者層級的 `~/.claude/CLAUDE.md`
  只拿來判斷衝突，沒有提議修改（見 A-F4）。
- **目標模型**：
  - Claude Code 讀的設定檔（CLAUDE.md、rules、skills、commands、agents）以 **Claude Opus 5.5**
    （執行本次稽核的模型）為準。frontmatter 有 pin `model:` 的檔案以該 pin 為準；pin 全部是浮動
    alias（`opus`／`sonnet`／`haiku`），沒有過期的版本 ID。
  - 應用程式呼叫端（Group 4）以各自 pin 的模型為準：`handover_service.py` 的
    `claude-sonnet-4-20250514` 已 Deprecated，提案改到同一 tier 的 `claude-sonnet-5`；
    `categorize_hsbc.py` 的 `claude-sonnet-4-6` 仍 Active，不動模型選擇。
- **非 Anthropic provider**：Codex／Gemini（agy）的 wrapper skill 會把 prompt 送給非 Claude 模型，
  這部分只檢查過期事實，不套用 Claude 的行為準則。
- **掃描方式**：三個 subagent 平行掃描（A：CLAUDE.md + rules；B：dev-cycle + 3rd-tools；
  C：growth／harness／methodology／sdd／agents），lead 負責 Group 4 並抽查各批的 High 項目。
  抽查推翻了一項（C-F4：`scripts/tests/test_fleet_usage_guard.py` 其實存在），已剔除。

## 摘要

影響最大的三項：

1. **Group 4 — handover 翻譯路由（G4-1～4）**：pin 的是已 Deprecated 的 Sonnet 4，而且用
   `response.content[0]` 讀結果。換到 Sonnet 5 時，省略 `thinking` 會預設開 adaptive thinking，
   第一個 block 會變成 thinking block，翻譯就會壞掉。提案改用 structured outputs、按 block type
   讀取、`effort: "low"`，並補上 mutation 驗證過的測試。
2. **mob review 引擎的判定規則已經漂移（B-F1、F2、F9）**：`extract-r1.md` 沒有 `[P0]` 對照，
   而且把 `[P1]` 當 critical，和 repo 自己的定義（P0=critical、P1=important）相反，會直接影響
   PR 是否被擋。`mob-code-review-only` 要求「照原樣跑 Steps 1.5→5」，這個範圍包含會改碼、會推送
   到別人分支的 Step 1.6／1.7；它對應的 NIT 標題引擎也已經不再產出。
3. **每個 session 都會載入的規則檔彼此衝突（A-F3、A-F4）**：rule 13 說 commit message 的
   `$(cat <<'EOF')` 可以豁免，CLAUDE.md（較新）禁止這麼做。rule 15 教的
   `git push -u origin <branch>`，正是全域 CLAUDE.md 記載會直推 main 的寫法；本 repo 的
   `push.default=upstream`，這個前提成立。後者是安全規則，只 flag 不改。

各批計數（剔除被推翻的一項後；flag 項不在 diff 內）：

| 批次 | High | Medium | Low | 範圍外 | 其中只 flag |
|---|---|---|---|---|---|
| G4 request 設定 | 2 | 3 | 1 | 2 | 3 |
| A CLAUDE.md + rules | 4 | 11 | 4 | — | 6 |
| B dev-cycle + 3rd-tools | 10 | 15 | 5 | — | 8 |
| C growth／harness／sdd／agents | 11 | 13 | 6 | — | 8 |

以 pattern 來看，絕大多數屬於 Group 2（過期事實、檔案之間互相矛盾）。Group 1 只有少數幾項：
相對舊版本的措辭、investigate 的全大寫強調、數字上限、輸出配額。rules 裡全大寫的 MUST/NEVER
只出現 3 次，而且都是實際存在的限制。Group 3 不適用：這個 repo 沒有自訂 tool 定義。

## 驗證

- `make ci`（在 `git add` 之後跑）：exit 0，3367 passed、13 skipped；pre-commit 沒有就地改寫檔案。
- G4 新增 `NLANG-ST-016`、`NLANG-EG-017`、`NLANG-EG-018`。對 ST-016 做了 mutation：把「按 type
  取 text block」改回「取第一個 block」，測試轉紅；用反向替換還原後轉綠。
- PR #502 review 後補：`_translate_batch` 改以 stop_reason 白名單（僅 `end_turn`）判定，schema 不符的
  `ValidationError` 轉成 `RuntimeError`，拒絕重複／越界 index；新增 `NLANG-EG-019`～`022`、
  `EG-025`～`026`、`NLANG-ST-023`～`024`。把白名單改回只檢查 text block 是否存在的 mutation
  會讓 EG-019 與 EG-021 轉紅。
- PR #502 第二輪 review 後補：`_translate_batch` 不再做 XML escape／unescape，改把原文以含 index 的
  JSON 陣列放進 user message、譯文從 structured output 的 JSON 直接讀回，避免字面的 `&lt;div&gt;`
  被解碼成 `<div>`。`NLANG-ST-024` 改為同時涵蓋字面 entity 與原始 `<`、`>`、`&`，並斷言請求內容帶
  原文而非 entity；新增 `NLANG-EG-027`（index == 項目數的上界邊界）。ST-024 在舊實作上先確認為紅。
- `classify_batch` 新增 `scripts/tests/test_categorize_hsbc.py`（`HSBC-*-001`～`012`，以假 client 與
  `sys.modules` 替身測試，不打真實 API）；`PROMPT_CATEGORIES` 的不變式改在模組載入時檢查（含重複
  科目），不符即 raise `RuntimeError`。`HSBC-DT-001` 改為比對寫死的 21 個科目清單；`HSBC-ST-011`
  斷言請求的 json_schema、category enum 與 `system`；`HSBC-EG-010` 測上界邊界；`HSBC-EG-012` 確認
  body 格式錯誤轉成 `RuntimeError`。enum、system、schema type、上界與重複檢查各做一次 mutation，
  全數轉紅。
- 沒有對模型做行為探測（沒有花 API 費用）。Group 1 的刪除項屬於「移除是假設」，需要在實際
  session 中觀察（見文末）。

---

## Group 4 — request 設定與架構（lead）

| ID | 位置 | 證據 | Pattern | 為何過時 | 信心 | 動作 |
|---|---|---|---|---|---|---|
| G4-1 | `tasks/mycelium/handover_service.py:333` | `model="claude-sonnet-4-20250514"` | API fossil | Sonnet 4 已 Deprecated，退役後這條路由會直接失敗 | High | rewrite → `claude-sonnet-5` |
| G4-2 | `handover_service.py:352-353` | `first_block = response.content[0]` | thinking config 對錯模型 | Sonnet 5 省略 `thinking` 就會跑 adaptive，`content[0]` 可能是 thinking block，regex 抓不到 `<item>`，整批失敗 | High | 按 `type` 取 text block |
| G4-3 | `handover_service.py:262, 278-280, 344-367` | `Return each translation inside <item index="N">...</item> tags … Do not add explanations outside the tags.` + `_ITEM_RE`、`_xml_unescape` | 1b：用 prompt 格式指示 + regex 解析，應改用 API 功能 | structured outputs 保證回傳符合 schema 的 JSON；regex 和 unescape 只為舊機制存在。輸入端的 `_xml_escape` 保留 | Medium | replace-with-API-feature |
| G4-4 | `handover_service.py:334` | `max_tokens=8192` | `max_tokens` 依錯的模型設定 | Sonnet 5 的 thinking 計入 `max_tokens`，且 tokenizer 多約 30% token | Medium | `max_tokens=16000` + `effort: "low"` |
| G4-5 | `scripts/categorize_hsbc.py:73, 106-120` | `只回傳科目名稱，不加任何解釋或標點。` + `cats[i] if i < len(cats) else "其他支出"` | 1b：用 prompt 強迫輸出格式 | 模型多或少輸出一行，之後每一筆的科目就全部錯位，而且會被靜默歸到「其他支出」再寫進 DB | Medium | enum 限定的 JSON schema；缺編號就在寫入 DB 前 fail loud |
| G4-6 | `tasks/nightly_agent/drafter.py:34, 50, 64` | `Output ONLY a valid Python script. No markdown fences, no explanation.` | 1b | 走 `claude --print`，不是 Messages API；CLI 的 JSON 輸出模式本次沒有驗證 | Low | flag |
| G4-7 | `fleet_usage_guard.py:46-50`；`token_usage_service.py:34` | `ModelPrice("claude-opus-5", Decimal("15"), Decimal("75"))`、`"claude-sonnet-5": (3.00, 15.00)` | 範圍外（不是 prompt） | 現行價格：Opus 5／4.8／4.7／4.6 是 $5/$25，Sonnet 5 是 $2/$10；`token_usage_service` 也缺 `claude-opus-5`、`claude-opus-5-5`、`claude-fable-5-1` | — | flag |
| G4-8 | `scripts/categorize_hsbc.py:15` | `API_TOKEN = "ldo_3TUY…"`（已遮蔽） | 範圍外：**安全** | 受版控檔案裡有明文 API token（本機 ledgerone）。只要曾經 push，就應該視為已外洩並輪替 | — | flag（沒有提議修改；需要你決定是否輪替並改成讀環境變數） |

其餘 Group 4 檢查沒有發現：沒有改寫歷史的 harness（三條路由都是單輪）；沒有對 cache 不友善的
排序；三個模型呼叫點都是真正需要判斷的工作；已經有 token accounting（`token_usage_service.py`）。

---

## A — CLAUDE.md、ARCHITECTURE.md、`.claude/rules/`

已驗證正確（不是 finding）：rule 檔數量與 `paths:` scoping、所有 make target、hook 名稱、8 個
guarded target、`gh pr merge` 在各檔的說法一致、rule 13 → 17 的搬移清單。基於政策沒有驗證：
`syncClaudeAi*`、`respondToBashCommands`（位於 settings 檔）。

| ID | 位置 | 證據 | Pattern | 為何過時 | 信心 | 動作 |
|---|---|---|---|---|---|---|
| A-F1 | `ARCHITECTURE.md:42` | `pr.md → /pr` | 2 volatile | `commands/pr.md` 已在 d5ff42a（#97）刪除；ARCHITECTURE 每個 session 都會 @-import | High | rewrite → `pr-retro.md` |
| A-F2 | `ARCHITECTURE.md:37` | `sdd/ → Subagent Driven Development` | 2 volatile | plugin.json 與 CLAUDE.md:3 都寫 Spec-Driven Development | High | rewrite |
| A-F3 | `rules/13:285` vs `CLAUDE.md:44-46` | `` `$(cat <<'EOF')` for commit message plain text is exempt `` vs「**不要**用 `git commit -m "$(cat <<'EOF' ... EOF)"`」 | 2 衝突 | 兩檔都每 session 載入，規則相反；blame 顯示 CLAUDE.md 較新（888b8399 > 26d0fff0） | High | rewrite 較舊的 rule 13（收緊規則，沒有放寬禁令） |
| A-F4 | `rules/15:197, 312-328` vs `~/.claude/CLAUDE.md` | `Must use git push -u origin <branch-name>` vs「`push.default=upstream` 下 `git push -u origin branch` 會直推 main」 | 2 衝突 | 本 repo 實測 `push.default=upstream`；rule 15 對「tracking origin/main」這個狀態教的正是會直推 main 的指令 | High | **flag**（安全規則，而且較新的文字在專案外）。建議改成 `git push origin <branch>:<branch>` |
| A-F5 | `ARCHITECTURE.md:90` | `執行所有 CI 檢查 \| make check` | 2 volatile | `check` 不跑 `pre-commit --all-files`；CLAUDE.md 規定 push 前的 gate 是 `make ci` | Medium | rewrite |
| A-F6 | `CLAUDE.md:118-120` | `（如 /config thinking=false）…（Claude Code v2.1.181+）` | 1b + volatile | Opus 5.5 的 thinking 一定開著，唯一的範例對目標模型無效；版本號已無意義 | Medium | rewrite |
| A-F7 | `rules/11:93-411` | 約 320 行 Makefile／install guard 規則放在 `paths: skills/**` 底下 | 2 scope 錯置 | 改 Makefile 或 guard 腳本時不會載入這段 | Medium | move → rule 17「Global-State Install Guard」；CLAUDE.md 兩處指標同步更新 |
| A-F8 | `CLAUDE.md:136, 287-289` | 「sdd … must be bumped together … sync the version field」 | 2 volatile | `scripts/sync_plugin_versions.py` 已經替所有 plugin 同步兩個檔案 | Medium | rewrite |
| A-F9 | `rules/16:225-263` | `built-in /less-permission-prompts … generates a sorted allowlist suggestion` | 2 volatile | 內建 skill 現在叫 `fewer-permission-prompts`，會直接寫入 `.claude/settings.json` | Medium | rewrite |
| A-F10 | `CLAUDE.md:329-335` | `now auto-triggers … used to be … restore the old` | 1d 相對於舊版本的措辭 | 描述的是相對某個舊版本的差異 | Medium | rewrite |
| A-F11 | `CLAUDE.md:301-310` | `supersedes the earlier "always clamps to 15" wording` | 1d | 描述的是相對本檔前一版的差異 | Medium | rewrite |
| A-F12 | `CLAUDE.md:78-81` | `原本也誤把失效的 glob: … 已修正 … #252（已 closed）` | 1d／2 歷史 | 已修好的 bug，沒有給出任何指示 | Medium | rewrite |
| A-F13 | `rules/13:490`；`rules/16:60-63, 218` | `originally rule 14 and was merged …` | 1d | 描述的是舊的檔案配置 | Medium | remove |
| A-F14 | `rules/13:125, 143-150, 157` | `(built-in prompt removed in 2.1.207 …)` | 1d | 寫成 changelog 的形式；現況其實就是「沒有機械防護」 | Medium | rewrite |
| A-F15 | `CLAUDE.md:208-211` vs `rules/11:134-137` | CLAUDE.md 列出 guarded targets；rule 11 規定「do not re-list」 | 2 衝突 | 目前兩邊內容一致，但這是政策衝突，方向要由你決定 | Medium | flag |
| A-F16 | `CLAUDE.md:311-328` | `claude -p` gotcha 內含各呼叫點的測試覆蓋分析 | 2 歷史 | 真正可執行的規則只有一句 | Low | flag |
| A-F17 | `rules/01:95-101` | `14 / 14 English`（2026-08-06 量測） | 2 volatile | 現在有 15 個檔案 | Low | flag |
| A-F18 | `rules/11:143-227` | `Four rounds, one shape … round 7` | 2 歷史 | 三條規則埋在約 85 行的 review 過程敘述裡 | Low | flag |
| A-F19 | `rules/15:3, 526-527`；`rules/13:618` | `v2 doc-layer rule` / `planned for v3` | 1d | roadmap 標籤沒有定義 | Low | flag |

附帶修正（在提案 diff 內）：rule 11 寫 nightly-agent「runs at 03:00」，`.runtime/schedules.json`
是 21:00（C-F27）；搬到 rule 17 的段落補了一句前導說明，否則會缺少前情。
A-F7 搬移後，面向 SKILL.md 撰寫者的三段（`resolve-skill-repo` 是唯一實作、`pwd -P` 不解析檔案
symlink 的指標、錯誤處理寫法）移回 rule 11，因為它們要在編輯 `skills/**` 時載入；rule 17 內重複的
檔案 symlink 段落刪掉，只保留「Self-Location and Portability」那一份。

---

## B — dev-cycle、3rd-tools、commands

`model: sonnet` 的四個 command 沒有 Sonnet 專屬問題。乾淨的：ci-triage、bump-version、verify-done、
clean-wt、handover、handover-back、codex-consult；agy／pr-cycle-deep 腳本的模型 pin 都與 SKILL.md 一致。

| ID | 位置 | 證據 | Pattern | 為何過時 | 信心 | 動作 |
|---|---|---|---|---|---|---|
| B-F1 | `mob-code-review-only/SKILL.md:186, 208, 217` | `## Actionable NIT (must fix — user requires all NITs cleaned up)` | 2 volatile | 引擎現在產出 `(deferred — never blocks; …)`，改寫表的這一列永遠對不到 | High | rewrite |
| B-F2 | `mob-code-review-only/SKILL.md:124-134, 192` | `Execute /pr-cycle-deep Steps 1.5 → 5 exactly as written` | 2 衝突 | 範圍包含會改碼、會推送的 Step 1.6／1.7（這個 skill 禁止）；漏了 Step 3.4 的 R2 gate；沒有 Review Contract | High | rewrite（明列要跑的步驟） |
| B-F3 | `mob-code-review-only/SKILL.md:58` | `codex (codex review --base)` | 2 volatile | 引擎已改用 `codex exec`，且 pr-cycle-deep:1332 明令不要改回去 | High | rewrite |
| B-F4 | `commands/pr-cycle-deep.md:9` | `PR 已存在，直接跳到 mob review` | 2 衝突 | SKILL.md:43（較新）規定仍要跑 Step 1 Review Contract gate | High | rewrite |
| B-F5 | `codex-cli/SKILL.md:531-535` | 引用的 rule 15 原文 | 2 volatile | rule 15 已在 #426 改寫，這段引文已不存在 | High | rewrite |
| B-F6 | `local-port-manager/SKILL.md:33` | `recorded release tag v1.11.0` | 2 volatile | 同檔的安裝指令 pin 的是另一個 tag | High | rewrite → `v1.23.2`（全檔統一） |
| B-F7 | `local-port-manager/SKILL.md:40-43` | `正由 issue #256 追蹤裁決` | 2 volatile | #256 已 closed；後續方向寫在 ADR-0005，但其 status 仍為 proposed（提案，尚未裁決） | High | rewrite |
| B-F8 | `commands/debug-to-pr.md:70-75` | `/tmp/pr-body.md … rm -f` | 2 衝突 | 專案與全域規範都要求 `$CLAUDE_JOB_DIR`、不要 rm | High | rewrite |
| B-F9 | `pr-cycle-deep/prompts/extract-r1.md:56-58` | `[P1] … → critical`，沒有 `[P0]` | 2 volatile | repo 定義 P0=critical、P1=important（codex-review:152、agy run.sh、pr-cycle-deep:856） | High | rewrite |
| B-F10 | `issue-triage/SKILL.md:230-265, 579` | `docs/openspec/…`、`backend/src/ mobile/lib/`、`#1014`、`pre-jira-write.sh` | 2 volatile | global skill 寫死 yibi-mvp 的路徑；在其他 repo grep 到零命中時，會被誤判成「未實作」 | High | rewrite（加路徑解析說明、改成通用措辭） |
| B-F11 | `pr-cycle-fast/SKILL.md:222` | `結果寫到 $REVIEW_DIR` | 2 volatile | 這個 skill 沒有定義該變數 | Medium | rewrite |
| B-F12 | `pr-review-cycle/SKILL.md:118, 373` | `git diff main...HEAD` | 2 衝突 | 本檔 Step 1.6 與 pr-cycle-deep 都禁止用本地 main | Medium | rewrite → `gh pr diff` |
| B-F13 | `pr-review-cycle/SKILL.md:141-152` | 用兩個 Task agent 跑固定的 gh 指令 | Group 4 | pr-cycle-deep:270（較新）說用一個 Bash call 就好；但你的 memory 偏好平行 agent | Medium | flag（由你決定） |
| B-F14 | `mob-code-review-only/SKILL.md:176-180` | `(Same rule as /pr-cycle-deep Step 5 …)` | 2 衝突 | 兩邊的規則其實不同 | Medium | rewrite |
| B-F15 | `agy-review/SKILL.md:137, 173` | `腳本自動從 git diff origin/<BASE>...HEAD 取得 diff` | 2 與腳本矛盾 | `run.sh:94` 不會 fetch，而且會靜默退回 `HEAD~1` | Medium | rewrite（修腳本本身不在本次範圍） |
| B-F16 | `codex-review/SKILL.md:5` | `觸發：… review diff, … code review …` | 2 trigger 列舉 | 同系列 skill 都要求明確指名模型；泛用的「code review」會搶走 `/code-review` 的觸發 | Medium | rewrite |
| B-F17 | `investigate/SKILL.md:38-41, 56, 234, 279-291` | `NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST.`、`This is not optional.` | 1a + 1c | 全大寫強調與重複規則，會讓 Opus 5.5 過度僵化 | Medium | rewrite |
| B-F18 | `pr-cycle-deep/SKILL.md:349-355`；`pr-review-cycle/SKILL.md:232-238` | `Fallback (Claude Code < 2.1.146)` | 1d | 目前 harness 是 2.1.283 | Medium | remove |
| B-F19 | `pr-cycle-deep/SKILL.md:970-971` | `Reply in <=15 lines` | 1f 數字上限 | 列出的欄位已經定義了輸出形狀；行數上限在 finding 多時會截掉理由 | Medium | rewrite |
| B-F20 | `codex-cli/contract.md:50-60` | `Never mix languages inside one document.` | 2 衝突 | global skill 寫死語言政策，而且和全域 CLAUDE.md 對這條規則的適用範圍說法相反 | Medium | rewrite |
| B-F21 | `agy-consult/SKILL.md:21, 26, 156`；`agy-review/SKILL.md:18, 21, 174` | `AGY_MODEL=claude-sonnet-4-6` | 2 pinned model | 寫死第三方 CLI catalog 裡的模型 ID | Medium | rewrite → 指向 `agy models` |
| B-F22 | `verify-gemini-models/SKILL.md:82, 148-190` | `已知 Gemini 模型狀態（2026-04）`、`將於 2026-03-19 淘汰` | 2 時效 | 快照已過期五個月 | Medium | rewrite（改成「快照」，並修正第 190 行的矛盾） |
| B-F23 | `commands/lessons.md:10, 123-133` | `{add\|show\|search\|delete\|retire}`、`Phase B 以後實作` | 2 volatile + 1d | CLI 還有 finalize／supersede；整合早已上線 | Medium | rewrite |
| B-F24 | `commands/debug.md:5-16, 84` | `不要問問題`、`write and run the migration` | 2 衝突（安全） | 和 investigate、rule 15 Category 1 衝突 | Medium | flag |
| B-F25 | `commands/newjob.md:87, 89` | `python -m tasks.local_port_manager`（透過 `$MAIN_REPO`） | 2 衝突 | 這個 module 只存在於 yibi-stack，其他專案應改用 `portman` | Medium | flag |
| B-F26～30 | pr-cycle-fast:220 的「重要」強調、local-port-manager 重複段落、investigate 缺 `type:`、pr-cycle-deep:1022 的歷史敘述、codex-review 只從 origin fetch | — | 1a／2 | 見掃描紀錄 | Low | flag |

---

## C — growth、harness、methodology、sdd、`skills/`、`.claude/agents`

乾淨的：protect-push、plugin-migration-check、plugin-cache-prune、pr-retro-hard、figma-design-sync、
problem-frames、new-task-module、recap、debug-report、security-scanner、pr-retro commands。

| ID | 位置 | 證據 | Pattern | 為何過時 | 信心 | 動作 |
|---|---|---|---|---|---|---|
| C-F1 | growth 各 skill 的安裝提示 + README | `yibi-stack@v1.14.0` | 2 volatile | v1.14.0 沒有 pr-retrospective 用到的 `--park`／`lessons finalize`（lead 以 `git show` 確認）；最新 tag v1.23.2 有 | High | rewrite → `v1.23.2`（`openspec/specs` 是歷史 spec，不動） |
| C-F2 | `mycelium/SKILL.md:30-32, 196`；insight:143；handover:12, 15 | `agents handover write/read/search` | 2 volatile | `pyproject` 只定義了 `mycelium` binary | High | rewrite |
| C-F3 | `claude-md-prune/SKILL.md:149` | `rules/ 沒有 200 行限制（path-scoped，不是全域載入）` | 2 衝突 | 它自己的路由表送去的 03/13/15 都是每 session 全量載入 | High | rewrite |
| C-F4 | ~~fleet-usage-guard:264~~ | — | — | **被推翻**：該測試檔存在 | — | 剔除 |
| C-F5 | `bash-anti-patterns/SKILL.md:333, 337, 453` | `"${VAR}" … -> use "$VAR" plain form instead`、`rules/14-shell-quoting-hygiene.md` | 2 衝突 | rule 13 實測兩種寫法都會觸發誤判，照舊寫法修不掉；rule 14 已經不存在 | High | rewrite |
| C-F6 | `bash-anti-patterns/SKILL.md:321` | `(class F1 hook intercepts)` | 2 衝突 | rule 13（較新）說已經沒有機械防護 | High | rewrite |
| C-F7 | `.claude/agents/bash-to-script.md:68` | `rules/14-shell-quoting-hygiene.md` | 2 volatile | 檔案不存在 | High | rewrite |
| C-F8 | `spectra-amplifier/SKILL.md:87` | `見 rule 11/18` | 2 volatile | 沒有 rule 18 | High | rewrite |
| C-F9 | `qa-test-design/SKILL.md:58-65`；methodology.md:326 | `e.g. LOGIN-BVA-001` | 2 衝突 | qa-test-designer（今天的 #474，較新）明令 TC-ID 不得含技法縮寫 | High | rewrite |
| C-F10 | `spectra-amplifier/SKILL.md:392, 529-555`；bdd-trace-convention:134 | `SMK-001 正常路徑` | 2 衝突（同檔） | 同檔第 390 行（較新）說無前綴的 ID 會 collision | High | rewrite → `LOGIN-SMK-001` |
| C-F11 | `harness-eval-focus/SKILL.md:218` | `files 設定的 pattern … rg --include` | 2 衝突 | key 必須是 `paths:`；rg 沒有 `--include` 這個 flag | High | rewrite |
| C-F12 | `skills/nightly-agent/SKILL.md:46-50, 72, 136` | `確認 ANTHROPIC_API_KEY 已設定（draft 功能需要）` | 2 volatile | drafter 走 `claude --print` 訂閱，需要的是 `claude` CLI | High | rewrite |
| C-F13 | `.claude/agents/explorer.md` | 唯讀探索 agent | 4 重複的 subagent | 和內建 Explore 同角色，全 repo 沒有任何呼叫端；當初是為了 harness-eval D9 的分數而建 | Medium | remove（ARCHITECTURE.md 那一行同步刪除） |
| C-F14 | `harness-eval-focus/SKILL.md:245, 251-261` | `至少建立 1 個 explore.md` + 唯一範例 | 4 + 1c | C-F13 的來源 | Medium | rewrite |
| C-F15 | `harness-eval-focus:9, 20`；harness-eval:209 | `D1~D11` / `D1~D10` | 2 volatile | 沒有 D5、D6 的章節 | Medium | rewrite |
| C-F16 | `bash-hygiene-audit/SKILL.md:102-116` | `/less-permission-prompts` | 2 volatile | 同 A-F9 | Medium | rewrite（第 113 行的流程也一併修正） |
| C-F17 | `pr-control-log/SKILL.md:100` | `至少一個 entry 的 category 必須為 autonomous_decision` | 1c 輸出配額 | 會逼模型在審計資料裡捏造 entry | Medium | rewrite |
| C-F18 | `pr-control-log/SKILL.md:75` | `git log --oneline origin/main..HEAD` | 2 volatile | 這支 skill 在 merge 後使用，那時這個 range 是空的 | Medium | rewrite → `gh pr view --json commits` |
| C-F19 | `pr-control-log/SKILL.md:9` vs :148 | `11 個 section` vs `12 個` | 2 同檔衝突 | — | Medium | rewrite |
| C-F20 | `pr-retrospective/SKILL.md:720-740`；mycelium/SKILL.md:129-146 | `PostToolUse hook 現在支援……不再只限 MCP` | 1d + 1c | 相對舊版本的描述，而且是和 runbook 無關的假設性 hook | Medium | remove |
| C-F21 | `spectra-amplifier/SKILL.md:17, 66-74` | `effort: high` + medium／low 路由表 | 2 衝突 | pin 住 effort 後，medium／low 那幾列永遠不會走到 | Medium | flag（保留 pin 或保留路由，由你決定） |
| C-F22 | amplifier:70-71 vs gherkin-scenario-writer:109-115 | 每條 AC 的 scenario 數量 | 2 衝突 | blame 無法判斷哪邊較新 | Medium | flag |
| C-F23 | `bdd-trace-convention.md:73-114` | `uv run python plugins/sdd/scripts/...` | 2 衝突 | amplifier 自己說 repo 相對路徑在 host 專案會靜默失敗 | Medium | rewrite → `$SDD_ROOT` |
| C-F24 | `skills/skill-trigger-eval/SKILL.md:41-47` | 要唯讀的 Explore 寫出 judgments.json | 3 tool 契約 | Explore 沒有 Write 工具 | Medium | rewrite（改由 lead 寫檔） |
| C-F25 | `plugins/sdd/commands/setup.md:11` | `echo "exit code: $?"` | 2 衝突 | 違反 rule 13 的 `$?` 特例 | Medium | rewrite |
| C-F26～31 | nightly draft_model pin、排程時間（已在 A 修正）、handover 的「Context Anxiety」前提、handover-context agent 沒有呼叫端、QA 教科書內容、harness-eval 的「v2 改版」註記 | — | 1d／2／4 | 見掃描紀錄 | Low | flag |

---

## 移除是假設：建議的後續觀察

- **B-F17（investigate 的全大寫強調）與 B-F19（15 行上限）**：這是行為面的刪除。下幾次
  `/investigate` 請留意是否出現「沒找到 root cause 就直接修」；若有，用一句平實的話加回來，
  不要恢復全大寫的版本。
- **G4-5**：分類 schema 的 enum 取自 `SYSTEM_PROMPT` 裡有說明的 21 個科目（`PROMPT_CATEGORIES`，
  模組載入時會檢查數量等於條列行、且全部對得到 `EXPENSE_ACCOUNTS`），所以合法集合和原本 prompt 一致；`餐飲`、
  `家庭三餐` 等只存在於科目表的別名不會被選到。行為上的差異是：原本行數對不上時會靜默塞成
  「其他支出」再寫入 DB，現在會在寫入前 fail loud。
- **G4-1～4**：沒有打真實 API。第一次在 Sonnet 5 上跑 `normalize_handover_language` 時，請確認
  thinking 花費與翻譯品質。

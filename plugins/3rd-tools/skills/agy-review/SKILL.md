---
name: agy-review
type: tool
scope: global
description: Antigravity CLI（agy）對 diff 做 code review（PASS/FAIL gate）或 challenge（對抗模式找 bug/security）；不啟動 mob 流程的輕量單一 reviewer，全程 --sandbox（唯讀，無寫入權）。預設 AGY_MODEL=gemini-3.8-flash-high（2026-09-03 實測台灣可用）。觸發須明確指名 Gemini / agy / antigravity 且要看 diff；未指名的一般「幫我 review」「這樣對嗎」不觸發。純問問題、沒有 diff 要看請改用 /agy-consult；要 OpenAI Codex（而非 Gemini）的 diff review 或第二意見請改用 /codex-review、/codex-consult；跨家 mob review 請改用 /mob-code-review-only 或 /pr-cycle-deep
---

# /agy-review — Antigravity CLI diff review 第二意見

獨立呼叫 Antigravity CLI（agy），出一份 code review 或對抗模式 bug hunt。
比 `/pr-cycle-deep` 輕量，不做 R2 cross-debate，適合快速拿第二意見。

> **實際 reviewer 是誰**：`run.sh` 預設 `AGY_MODEL=gemini-3.8-flash-high`。腳本每次執行
> 都會把實際模型以 `[INFO] agy 模型：<model>` 印到 stderr——把本 skill 的結果計入 mob review
> consensus 前，先讀那一行確認 reviewer 真的不是 Claude。
>
> 預設值的由來是 2026-09-03 的實測（agy 1.1.25，台灣）：五個 Gemini model id 全部可用，
> 未出現 `FAILED_PRECONDITION: User location is not supported`。此前預設 `claude-sonnet-4-6`
> 的地區限制前提已不成立。完整實測記錄與版本戳記見 `/agy-consult` SKILL.md 開頭同一段。
>
> `AGY_MODEL=claude-sonnet-4-6` 仍可覆寫回 Claude，但那時它**不是**跨廠商聲音，不可當第二家
> 計入 consensus；要 Claude 以外的第三家請用 `/codex-review`。
全程 `--sandbox`（唯讀），不需要、也不會用 `--dangerously-skip-permissions`。
純問技術問題、沒有 diff 要看請改用 `/agy-consult`。

## 觸發方式

```text
/agy-review [指示]       — Gemini code review，結尾含 [PASS] 或 [FAIL]
/agy-review challenge [重點]  — 對抗模式：只找 bug / security / race condition
/agy-review              — 無參數時預設 review mode
```

---

## 步驟

### Step 0 — 環境確認

#### Step 0a: Binary 檢查

```bash
which agy 2>/dev/null && echo "AGY_BIN: OK" || echo "AGY_BIN: NOT_FOUND"
```

AGY_BIN: NOT_FOUND → 停止。提示使用者安裝：`pip install antigravity-cli`。

#### Step 0b: Auth 確認（兩次獨立 bash call，不合併 if/elif）

```bash
python3 -c 'import json,pathlib,sys; p=pathlib.Path.home()/".gemini"/"antigravity-cli"/"cache"/"onboarding.json"; sys.exit(0 if p.is_file() and json.loads(p.read_text()).get("onboardingComplete") else 1)' && echo "AGY_AUTH: ONBOARDING_OK" || echo "AGY_AUTH: NO_ONBOARDING"
```

```bash
python3 -c 'import os,sys; sys.exit(0 if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") else 1)' && echo "AGY_AUTH: ENV_KEY_OK" || echo "AGY_AUTH: NO_ENV_KEY"
```

兩次均非 OK → 停止。提示：執行 `agy auth` 完成 OAuth，或在 `.env` 設定 `GEMINI_API_KEY`。

#### Step 0c: Allow-list 提示（非阻斷，只提示）

```bash
python3 -c 'import json,pathlib,sys; p=pathlib.Path.home()/".claude"/"settings.json"; d=json.loads(p.read_text()) if p.is_file() else {}; allow=d.get("permissions",{}).get("allow",[]); sys.exit(0 if any("agy-review" in x for x in allow) else 1)' && echo "AGY_ALLOW: OK" || echo "AGY_ALLOW: MISSING"
```

MISSING → 提示執行 `make patch-agy-allow-list`（或 `make install-all`）自動加入
`Bash(bash ~/.agents/skills/agy-review/scripts/run.sh:*)` 這條絕對路徑 allow list 項目，但不阻斷。
（不使用裸 `Bash(agy:*)`：那是動詞級萬用字元，會涵蓋任何 agy 指令組合，見 rule 16 Red Flag 2。）

#### Step 0d: Base branch 偵測（兩次獨立 bash call）

```bash
git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null | sed 's|origin/||'
```

```bash
git rev-parse --abbrev-ref HEAD 2>/dev/null
```

取得 upstream branch 名稱（如 `main`、`develop`）。無 upstream tracking 時，詢問使用者確認 base。
呼叫指令若帶 `base=<branch>`（見 Step 1），以該值覆蓋此處的偵測結果。

---

### Step 1 — 模式與參數判斷

從呼叫指令解析出 MODE、BASE、INSTRUCTION 三個值：

| 呼叫型態 | MODE | BASE | INSTRUCTION |
|----------|------|------|-------------|
| `/agy-review` | `review` | Step 0d 偵測值 | 空 |
| `/agy-review 重點關注 auth` | `review` | Step 0d 偵測值 | `重點關注 auth` |
| `/agy-review challenge` | `challenge` | Step 0d 偵測值 | 空 |
| `/agy-review challenge 找 race condition` | `challenge` | Step 0d 偵測值 | `找 race condition` |
| `/agy-review base=develop` | `review` | `develop` | 空 |
| `/agy-review challenge base=develop 找 race condition` | `challenge` | `develop` | `找 race condition` |

**`base=<branch>` 解析規則**：`base=` token 可出現在 `challenge` 之後的任意位置，
解析出 `<branch>` 後**必須從 INSTRUCTION 移除該 token**，並覆蓋 Step 0d 的偵測值。
`base=` 只接一個分支名（不含空白）；出現多個 `base=` 時取第一個並警告使用者其餘被忽略。

> **為何要在這裡解析，而不是只寫在 FAQ**：BASE 是 `run.sh` 的第 2 個位置參數，
> 若 `base=develop` 被當成自由指示，它會變成 prompt 裡的 `特別關注：base=develop`，
> 而 BASE 仍是 Step 0d 偵測到的分支——diff 取錯 base 但 review 照樣跑完、exit 0、無任何警告。

---

### Step 2 — 執行

> **執行說明**：腳本把 prompt+diff 以 inline 形式當 `-p` 的值傳入（`agy -p "$PROMPT_CONTENT" --model "$AGY_MODEL" --add-dir "$REPO_ROOT" --sandbox`），
> 避免 nested worktree（`.claude/worktrees/<name>/`）下 `@file` 解析失敗讓 agy 靜默進入 agentic 模式（review 錯 target / timeout），
> 並免去內容開頭 `@` 被誤判為檔案路徑、以及暫存檔殘留的風險。inline 會佔 ARG_MAX 參數預算，故腳本在呼叫前擋 256000 bytes 上限。
> **不可改成 `{ ... } | agy --print`**：`-p`/`--print` 不是 boolean，會把下一個 token（`--add-dir`）當 prompt 吃掉、完全不讀 stdin，
> 回一段無關文字後 exit 0（靜默失敗）；agy 1.1.2 沒有 stdin prompt 通道。
> `--add-dir "$REPO_ROOT"` 提供周邊程式碼 context——**必須是絕對路徑**，傳相對的 `.` 會讓
> agy 1.1.22 拿不到任何檔案 context 卻仍 exit 0，產出一份沒看過程式碼的 review（見 FAQ）。
> 直接執行即可，不要外加 log capture。

```bash
bash ~/.agents/skills/agy-review/scripts/run.sh "<MODE>" "<BASE>" "<INSTRUCTION>"
```

實際範例：

```bash
bash ~/.agents/skills/agy-review/scripts/run.sh "review" "main" ""
bash ~/.agents/skills/agy-review/scripts/run.sh "challenge" "main" "找 SQL injection"
```

腳本自動從 `git diff origin/<BASE>...HEAD` 取得 diff，組合 prompt，以 `--sandbox` 呼叫 agy。

---

### Step 3 — 解析並回報

讀取腳本輸出，判斷結果：

| 輸出含 | 結果 | 處置 |
|--------|------|------|
| `[PASS]` | 通過 | 回報「Gemini PASS」+ 摘要 |
| `[FAIL]` | 失敗 | 列出 P0/P1 issue，給出修法建議 |
| `[P0]` 或 `[P1]`（無 PASS/FAIL）| 有問題 | 視同 FAIL |
| 以上均無 | 不確定 | 呈現完整輸出，請使用者判斷 |

challenge mode：找到問題時輸出 `[P0]`/`[P1]` 列表，找不到問題時輸出 `[PASS] No critical issues found`（視同 review mode 的 PASS）。

---

## FAQ

| 問題 | 解法 |
|------|------|
| `agy: command not found` | `pip install antigravity-cli`，確認 `agy` 在 PATH |
| agy 輸出 `call:read_file{...}` / agentic 旁白而非 review | nested worktree 下 `@file` 解析失敗的舊問題；腳本已改用 inline 餵入。若仍出現，確認 `run.sh` 的 agy 呼叫為 `agy -p "$PROMPT_CONTENT" --model "$AGY_MODEL"` 而非 `-p "@.agy-review-tmp.md"` |
| agy 回答「`--add-dir` 是什麼」之類與 diff 無關的內容，且 exit 0 | `-p`/`--print` 把下一個 flag 當 prompt 吃掉了。確認 `run.sh` 是 `agy -p "$PROMPT_CONTENT" --model "$AGY_MODEL" --add-dir "$REPO_ROOT"`，不是 `{ ... } \| agy --print --add-dir ...`（後者無 stdin 通道，靜默失敗） |
| agy 回「沒有作用中的 workspace」／review 內容明顯沒讀過周邊程式碼，且 exit 0 | `--add-dir` 被傳了相對路徑。**agy 1.1.22 不再把相對的 `.` 解析成 active workspace**，即使已 cd 到該目錄、即使該目錄在 `trustedWorkspaces` 內。修法：傳絕對路徑。這是本檔最危險的靜默失敗形態（review 看起來正常但沒看過 code），測試 `AGYS-DT-010/011` 鎖住此不變量 |
| 以為是 `trustedWorkspaces` 沒列到這個 repo | **不是。** 負向對照實測（agy 1.1.22）：已列入的 repo 用相對 `.` 照樣失敗、未列入的 repo 用絕對路徑照樣成功。不要為此放寬 trust 清單 |
| Auth 失敗，`onboardingComplete` 為 false | 執行 `agy auth` 完成 OAuth 流程 |
| 無 API key 且 onboarding 未完成 | 在 `.env` 加入 `GEMINI_API_KEY=<your-key>` 或 `GOOGLE_API_KEY=<your-key>`（兩者均可） |
| `onboarding.json` 損毀（JSON 解析錯誤） | 刪除後重建：`rm ~/.gemini/antigravity-cli/cache/onboarding.json`，再執行 `agy auth` |
| 輸出缺少 `[PASS]` / `[FAIL]` | 在 INSTRUCTION 加入「結尾必須輸出 [PASS] 或 [FAIL]」 |
| diff 為空或 `origin/<base>` 不存在 | 確認已有 commit，或手動指定 base：`/agy-review base=develop` |
| Gemini 模型回 `FAILED_PRECONDITION: User location is not supported` | 地區限制又出現了（2026-09-03 實測時已無此問題，見開頭區塊）。先試其他 Gemini id（`agy models` 左欄）；全部失敗才設 `AGY_MODEL=claude-sonnet-4-6` 暫時切回 Claude，並記得此時**失去跨廠商獨立性**，不可把它的 review 當成第二家 |

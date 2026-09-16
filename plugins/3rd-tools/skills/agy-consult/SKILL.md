---
name: agy-consult
type: tool
scope: global
description: Antigravity CLI（agy）第二意見：讓 Gemini 讀 repo 後回答技術問題，不看 diff。預設 AGY_MODEL=gemini-3.8-flash-high（2026-09-03 實測台灣可用）。觸發須明確指名 Gemini / agy / antigravity 且是「問問題」而非「review 改動」：問 gemini、agy 第二意見、gemini 怎麼看、agy 諮詢。純粹「幫我看一下」「這樣對嗎」等未指名 Gemini/agy 的一般提問不觸發此 skill。要看 diff 或 PR 改動的 review 請改用 /agy-review；要 OpenAI Codex（而非 Gemini）的第二意見請改用 /codex-consult；跨家 mob review 請改用 /mob-code-review-only 或 /pr-cycle-deep
---

# /agy-consult — 透過 Antigravity CLI 取得第二意見

讓 Antigravity CLI（agy）讀取 repo 後，回答你對 codebase 的技術問題。
適合「這段邏輯對嗎？」「為什麼這樣設計？」「有什麼潛在問題？」等開放式諮詢。

> **實際回答者是誰**：`consult.sh` 預設 `AGY_MODEL=gemini-3.8-flash-high`。腳本每次執行
> 都會把實際模型以 `[INFO] agy 模型：<model>` 印到 stderr，**不要靠猜**——尤其在要把「兩邊
> 說法一致」當成跨廠商證據時，先讀那一行確認回答者真的不是 Claude。
>
> **預設值的由來（2026-09-03 實測，agy 1.1.25，台灣）**：`gemini-3.8-flash-high`、
> `3.8-flash-low`、`3.7-flash-low`、`3.6-flash-low`、`3.1-pro-low` 五個 model id 各發一次
> 請求**全部成功**，未出現 `FAILED_PRECONDITION: User location is not supported`；四個模型
> 各自回報與請求一致的名稱，排除靜默 fallback 到同一模型的可能。
> 此前預設為 `claude-sonnet-4-6`，理由是該地區限制——**該前提已不成立**，故改回 Gemini，
> 讓本 skill 的預設行為與它存在的理由（跨廠商第二意見）一致。
> 注意 3.7 / 3.8 **只有 Flash 沒有 Pro**，Pro 最新仍是 3.1；要 Pro 級推理請用
> `gemini-3.1-pro-high`。
>
> **反向提醒**：`AGY_MODEL=claude-sonnet-4-6` 仍可覆寫回 Claude，但那會讓本 skill 與你既有的
> Claude 意見**同一家投兩票**——在 mob review 裡是家族塌縮，不是兩個獨立聲音。要 Claude 以外的
> 第三家請用 `/codex-consult`。
>
> **這是版本相依的實測，不是永久事實**：agy 升版後若 Gemini 路徑再度失效，請重測後再改預設，
> 並更新這裡的版本戳記（rule 13 probe-rot）。`agy models` 左欄是可接受的 id；`--model` 亦接受
> 右欄的顯示名如 `Gemini 3.8 Flash (High)`。

和 `/agy-review` 的區別：`/agy-review` 吃 **diff**（branch 改動，PASS/FAIL gate）；
`/agy-consult` 吃**任意問題**，不需要有待 review 的改動。
全程 `--sandbox`（唯讀），不需要、也不會用 `--dangerously-skip-permissions`。

## 觸發方式

```text
/agy-consult <問題>      — 讓 agy 讀 repo 回答這個問題（預設模型 gemini-3.8-flash-high）
```

---

## Step 0 — 環境確認

### Step 0a: Binary 檢查

```bash
which agy 2>/dev/null && echo "AGY_BIN: OK" || echo "AGY_BIN: NOT_FOUND"
```

AGY_BIN: NOT_FOUND → 停止。提示使用者安裝：`pip install antigravity-cli`。

### Step 0b: Auth 確認（兩次獨立 bash call，不合併 if/elif）

```bash
python3 -c 'import json,pathlib,sys; p=pathlib.Path.home()/".gemini"/"antigravity-cli"/"cache"/"onboarding.json"; sys.exit(0 if p.is_file() and json.loads(p.read_text()).get("onboardingComplete") else 1)' && echo "AGY_AUTH: ONBOARDING_OK" || echo "AGY_AUTH: NO_ONBOARDING"
```

```bash
python3 -c 'import os,sys; sys.exit(0 if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") else 1)' && echo "AGY_AUTH: ENV_KEY_OK" || echo "AGY_AUTH: NO_ENV_KEY"
```

兩次均非 OK → 停止。提示：直接執行 `agy`（互動模式）完成瀏覽器 OAuth，或在 `.env` 設定 `GEMINI_API_KEY`。
（agy 1.2.3 **沒有** `auth` 子命令，實測 `agy help auth` 回 `Error: unknown subcommand: auth`。）

### Step 0c: Allow-list 提示（非阻斷，只提示）

```bash
python3 -c 'import json,pathlib,sys; p=pathlib.Path.home()/".claude"/"settings.json"; d=json.loads(p.read_text()) if p.is_file() else {}; allow=d.get("permissions",{}).get("allow",[]); sys.exit(0 if any("agy-consult" in x for x in allow) else 1)' && echo "AGY_ALLOW: OK" || echo "AGY_ALLOW: MISSING"
```

MISSING → 提示執行 `make patch-agy-allow-list`（或 `make install-all`）自動加入
`Bash(bash ~/.agents/skills/agy-consult/scripts/consult.sh)` 這條絕對路徑 allow list 項目
（exact-match，不帶 `:*`——`consult.sh` 不吃任何參數，見下方 Step 1 說明），但不阻斷。

---

## Step 1 — 執行

> **執行說明**：`consult.sh` **不吃任何參數**，固定讀 `$CLAUDE_JOB_DIR/agy-consult-question.txt`。
> 先用 Write tool 把問題寫到這個固定檔案，再直接執行 script（不帶任何參數）。
>
> **不可把問題本文直接 inline 進 bash 指令，也不可把問題檔案路徑當成參數傳入**：
> (1) 問題本文若直接 inline 進雙引號，shell 不會阻止 `$()`/backtick/`$VAR` 展開，問題內容
> 裡的 shell 語法會在 `consult.sh` 啟動前就被外層 shell 執行；(2) 若改成「吃檔案路徑參數」，
> 這支 script 的 allow-list entry 若帶 `:*`（見 `scripts/patch_agy_allow_list.py`）會放行任意
> 參數——一旦免確認生效，`bash consult.sh ~/.ssh/id_rsa` 一樣會通過，變成被預先核准的任意
> 檔案讀取＋外傳原語。固定死路徑、不吃參數、allow-list 用 exact-match（不帶 `:*`），才能同時
> 關掉這兩個面。
>
> Script 內部把「filesystem boundary 提醒 + 檔案內容」以 inline 形式當 `-p` 的值傳入
> （`agy -p "$PROMPT_CONTENT" --model "$AGY_MODEL" --add-dir "$REPO_ROOT" --sandbox`
> `--print-timeout "${AGY_PRINT_TIMEOUT_SECS}s" --log-file "$AGY_LOG_FILE" 2>"$AGY_STDERR_FILE"`），
> 沿用 `/agy-review` 的 `run.sh` 已驗證過的
> 安全模式（issue #153 / PR #229 retro）：不用 `@file`（nested worktree 下解析失敗會讓 agy 靜默
> 進入 agentic 模式）、不用 stdin pipe（`-p`/`--print` 不是 boolean，會把下一個 flag 當 prompt
> 吃掉；agy 1.1.2 起沒有 stdin prompt 通道）。`--add-dir "$REPO_ROOT"` 提供周邊程式碼 context——
> **必須是絕對路徑**，傳相對的 `.` 會讓 agy 1.1.22 拿不到任何檔案 context 卻仍 exit 0（見 FAQ）。
> 腳本帶 `--print-timeout 480s`（`AGY_PRINT_TIMEOUT_SECS` 可覆寫，**限 1-599 的整數秒**，
> 超出範圍在呼叫 agy 前就 exit 2）：agy 自 1.1.28 起超時時 **exit 0 並只回傳半截輸出**（1.2.3 複驗），
> 腳本會偵測後以 exit 124 fail loud，並把被丟棄的輸出存檔、印出路徑。
> **呼叫這個 Bash 時把 tool timeout 設為 600000**——預設 120 秒會在 agy 還沒回來前就砍掉腳本，
> 看起來就是「一直 timeout」卻沒有任何原因（此時 agy 的 stderr 仍會由腳本的 trap 補送出來）。
> 直接執行即可，不要外加 log capture。

```bash
bash ~/.agents/skills/agy-consult/scripts/consult.sh
```

實際範例（先用 Write tool 把問題寫進
`$CLAUDE_JOB_DIR/agy-consult-question.txt`，內容是
`tasks/mycelium 的 db.py 裡 park_lesson 跟 finalize_reassessed_lesson 共享哪些不變量？`，
再不帶任何參數執行）：

```bash
bash ~/.agents/skills/agy-consult/scripts/consult.sh
```

---

## Step 2 — 呈現結果

Clean exit 後，呈現完整輸出，不截斷、不摘要。

**Exit-code gate**：腳本非零退出，停止並把 stderr 的 `[FAIL]` 原因照實轉告使用者，不可把失敗輸出當成答案呈現，
也不要自動重跑成迴圈：

| exit | 意義 | 轉告重點 |
|------|------|----------|
| 124 | agy 在時間預算內沒完成（agy 本身回 exit 0 + 半截輸出，腳本擋下） | 問題範圍太大需大量探索檔案，或 API 額度不足；附上 `RESOURCE_EXHAUSTED` 那行（若有）。stderr 會附「被丟棄的輸出」檔案路徑，需要時可撈回 |
| 1 | 腳本前置檢查失敗（`CLAUDE_JOB_DIR` 未設、問題檔不存在或為空、`agy` 不在 PATH、prompt 超過 256000B）**或** agy 回空白／極短輸出 | 一律照 stderr 的 `[FAIL]` 原文轉告，不要一律歸因成「agy 回空白，請簡化問題」 |
| 2 | 腳本參數驗證失敗（`AGY_PRINT_TIMEOUT_SECS` 非整數或不在 1-599）、agy 版本太舊不支援 `--print-timeout` / `--log-file`，**或** agy 自身的 CLI 參數錯誤（agy 對未知 flag 也回 exit 2） | 以 stderr 為準：腳本自己的檢查會明說是哪一種；版本太舊的修法是 `agy update` |
| 143 | 腳本被外部訊號中止（多半是 Bash tool timeout 沒設 600000） | agy 的 stderr 已由 trap 補送，照它轉告；並提醒下次把 tool timeout 設足 |
| 其他 | agy 自己非零退出 | 確認 auth 或網路後重試 |

---

## FAQ

| 問題 | 解法 |
|------|------|
| `agy: command not found` | `pip install antigravity-cli`，確認 `agy` 在 PATH |
| Auth 失敗，`onboardingComplete` 為 false | 直接執行 `agy` 進互動模式完成瀏覽器 OAuth（agy 1.2.3 沒有 `auth` 子命令） |
| 無 API key 且 onboarding 未完成 | 在 `.env` 加入 `GEMINI_API_KEY=<your-key>` 或 `GOOGLE_API_KEY=<your-key>`（兩者均可） |
| `onboarding.json` 損毀（JSON 解析錯誤） | 刪除後重建：`rm ~/.gemini/antigravity-cli/cache/onboarding.json`，再執行 `agy` 完成 OAuth |
| 問題內容含雙引號 / `$VAR` / backtick | 不影響——問題本文透過 Write tool 寫進檔案，`consult.sh` 只吃檔案路徑，問題內容不會被 shell 展開或執行 |
| 一直 timeout、沒有任何輸出或原因 | 兩個常見成因（agy 1.2.3 實測）：(1) Bash tool timeout 沒設 600000，腳本在 agy 回來前就被砍（此時 exit 143，agy 的 stderr 仍會由 trap 補送）；(2) agy 自己的 `--print-timeout` 到期——此時 agy **exit 0 並回半截輸出**，腳本以 exit 124 擋下並把該輸出存檔。問題若需要 agy 翻遍整個目錄（例如「列出所有 module 的函式」），縮小範圍、直接點名檔案；或用 `AGY_PRINT_TIMEOUT_SECS` 調整，範圍 1-599（**>= 600 會被腳本擋下**，因為那等於讓 harness 先砍掉診斷） |
| 回答看起來沒讀到 repo 的檔案，但 exit 0 | 這是最危險的形狀（語意完整、兩道 timeout 訊號都不命中）。腳本在成功路徑也會印 `[INFO] agy log：<path>`——查那個檔可看出 agy 實際做了什麼。注意 `--log-file` 是**改道**：`~/.gemini/antigravity-cli/log/` 不會有這次執行的副本，所以請用腳本印出的路徑 |
| `[FAIL]` 訊息附帶 `RESOURCE_EXHAUSTED (code 429)` | agy 只把 429 重試寫進自己的 log（stderr 看不到），腳本失敗時才撈出來。`Individual quota reached ... Resets in <N>h` 是**帳號額度用完**，重試無效：把 agy 切換到另一個登入帳號（例如 GCP 帳號）或等重置；`try again later` 是暫時性容量不足，減少同時執行的 agy（mob review 會並行呼叫）後重試 |
| `agy` 回傳空白或極短輸出 | `--sandbox` 底下 agy 想探索周邊檔案被自己的權限系統擋下，headless 無法跳出確認框；簡化問題避免需要額外讀檔，或評估是否需要放寬 `~/.gemini/antigravity-cli/settings.json` 的 `permissions.allow` |
| agy 回「沒有作用中的 workspace」／「這看起來是 scratch 目錄」，或語意完整但顯然沒讀到檔案（甚至給出幻覺數字），且 exit 0 | `--add-dir` 被傳了相對路徑。**agy 1.1.22 不再把相對的 `.` 解析成 active workspace**，即使呼叫端已 cd 到該目錄。修法：傳絕對路徑（`--add-dir "$REPO_ROOT"`）。這道坑攔不到——exit code 是 0，而輸出 141 bytes（中文拒答約 47 字元）遠超腳本的 20 **字元**下限（守門用 `${#OUTPUT}` 數字元，不是 bytes）。測試 `AGYS-DT-010/011` 就是為了鎖住這個不變量 |
| 懷疑是 `trustedWorkspaces` 沒列到這個 repo 才被拒讀 | **不是這個原因。** 實測負向對照（agy 1.1.22）：已列在 `trustedWorkspaces` 的 repo 用相對 `.` 一樣失敗，未列入的 repo 用絕對路徑一樣成功。唯一的鑑別變數是 `--add-dir` 的路徑形式，不要為此去改 trust 清單（那會無效地放寬安全邊界） |
| Gemini 模型回 `FAILED_PRECONDITION: User location is not supported` | 地區限制又出現了（2026-09-03 實測時已無此問題，見開頭區塊）。先試其他 Gemini id（`agy models` 左欄）；全部失敗才設 `AGY_MODEL=claude-sonnet-4-6` 暫時切回 Claude，並記得此時**失去跨廠商獨立性**，不可把它的意見當成第二家 |
| 想看 diff review 而非問答 | 改用 `/agy-review` |

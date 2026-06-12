---
name: agy
type: tool
scope: global
description: Antigravity CLI（Gemini）第二意見：review（PASS/FAIL gate）、challenge（對抗模式找 bug/security）；不啟動 mob 流程的輕量單一 Gemini reviewer
---

# /agy — Gemini 第二意見

獨立呼叫 Antigravity CLI（agy），出 Gemini code review 或對抗模式 bug hunt。
比 `/pr-cycle-deep` 輕量，不做 R2 cross-debate，適合快速拿 Gemini 第二意見。

## 觸發方式

```text
/agy review [指示]       — Gemini code review，結尾含 [PASS] 或 [FAIL]
/agy challenge [重點]    — 對抗模式：只找 bug / security / race condition
/agy                     — 無參數時預設 review mode
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
python3 -c 'import json,pathlib,sys; p=pathlib.Path.home()/".claude"/"settings.json"; d=json.loads(p.read_text()) if p.is_file() else {}; allow=d.get("permissions",{}).get("allow",[]); sys.exit(0 if any("agy" in x for x in allow) else 1)' && echo "AGY_ALLOW: OK" || echo "AGY_ALLOW: MISSING"
```

MISSING → 提示執行 `make patch-agy-allow-list`（或 `make install-all`）自動加入 `Bash(agy:*)` 與 `Bash(bash <run.sh 絕對路徑>:*)` 兩個 allow list 項目，但不阻斷。

#### Step 0d: Base branch 偵測（兩次獨立 bash call）

```bash
git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null | sed 's|origin/||'
```

```bash
git rev-parse --abbrev-ref HEAD 2>/dev/null
```

取得 upstream branch 名稱（如 `main`、`develop`）。無 upstream tracking 時，詢問使用者確認 base。

---

### Step 1 — 模式判斷

從呼叫指令解析：

| 呼叫型態 | MODE | INSTRUCTION |
|----------|------|-------------|
| `/agy` 或 `/agy review` | `review` | 空 |
| `/agy review 重點關注 auth` | `review` | `重點關注 auth` |
| `/agy challenge` | `challenge` | 空 |
| `/agy challenge 找 race condition` | `challenge` | `找 race condition` |

---

### Step 2 — 執行

> **執行說明**：腳本以 stdin（`agy --print ... < $TMP`）餵入 prompt+diff，避免 nested worktree（`.claude/worktrees/<name>/`）下 `@file` 解析失敗讓 agy 靜默進入 agentic 模式（review 錯 target / timeout）；stdin 同時免去 ARG_MAX 參數長度上限與內容開頭 `@` 被誤判為檔案路徑的風險。`--add-dir .` 提供周邊程式碼 context，完成後自動清理臨時 prompt 檔。直接執行即可，不要外加 log capture。

```bash
bash ~/.agents/skills/agy/scripts/run.sh "<MODE>" "<BASE>" "<INSTRUCTION>"
```

實際範例：

```bash
bash ~/.agents/skills/agy/scripts/run.sh "review" "main" ""
bash ~/.agents/skills/agy/scripts/run.sh "challenge" "main" "找 SQL injection"
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
| agy 輸出 `call:read_file{...}` / agentic 旁白而非 review | nested worktree 下 `@file` 解析失敗的舊問題；腳本已改用 stdin 餵入。若仍出現，確認 `run.sh` 的 agy 呼叫為 `agy --print ... < "$TMP"` 而非 `-p "@.agy-review-tmp.md"` |
| Auth 失敗，`onboardingComplete` 為 false | 執行 `agy auth` 完成 OAuth 流程 |
| 無 API key 且 onboarding 未完成 | 在 `.env` 加入 `GEMINI_API_KEY=<your-key>` 或 `GOOGLE_API_KEY=<your-key>`（兩者均可） |
| `onboarding.json` 損毀（JSON 解析錯誤） | 刪除後重建：`rm ~/.gemini/antigravity-cli/cache/onboarding.json`，再執行 `agy auth` |
| 輸出缺少 `[PASS]` / `[FAIL]` | 在 INSTRUCTION 加入「結尾必須輸出 [PASS] 或 [FAIL]」 |
| diff 為空或 `origin/<base>` 不存在 | 確認已有 commit，或手動指定 base：`/agy review base=develop` |

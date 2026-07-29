---
name: agy-consult
type: tool
scope: global
description: Antigravity CLI（Gemini）第二意見：讓 Gemini 讀 repo 後回答技術問題，不看 diff。觸發須明確指名 Gemini / agy / antigravity 且是「問問題」而非「review 改動」：問 gemini、agy 第二意見、gemini 怎麼看、agy 諮詢。純粹「幫我看一下」「這樣對嗎」等未指名 Gemini/agy 的一般提問不觸發此 skill。要看 diff 或 PR 改動的 review 請改用 /agy-review；要 OpenAI Codex（而非 Gemini）的第二意見請改用 /codex-consult；跨家 mob review 請改用 /mob-code-review-only 或 /pr-cycle-deep
---

# /agy-consult — 詢問 Gemini 技術問題

讓 Antigravity CLI（agy／Gemini）讀取 repo 後，回答你對 codebase 的技術問題。
適合「這段邏輯對嗎？」「為什麼這樣設計？」「有什麼潛在問題？」等開放式諮詢。

和 `/agy-review` 的區別：`/agy-review` 吃 **diff**（branch 改動，PASS/FAIL gate）；
`/agy-consult` 吃**任意問題**，不需要有待 review 的改動。
全程 `--sandbox`（唯讀），不需要、也不會用 `--dangerously-skip-permissions`。

## 觸發方式

```text
/agy-consult <問題>      — 讓 Gemini 讀 repo 回答這個問題
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

兩次均非 OK → 停止。提示：執行 `agy auth` 完成 OAuth，或在 `.env` 設定 `GEMINI_API_KEY`。

### Step 0c: Allow-list 提示（非阻斷，只提示）

```bash
python3 -c 'import json,pathlib,sys; p=pathlib.Path.home()/".claude"/"settings.json"; d=json.loads(p.read_text()) if p.is_file() else {}; allow=d.get("permissions",{}).get("allow",[]); sys.exit(0 if any("agy-consult" in x for x in allow) else 1)' && echo "AGY_ALLOW: OK" || echo "AGY_ALLOW: MISSING"
```

MISSING → 提示執行 `make patch-agy-allow-list`（或 `make install-all`）自動加入
`Bash(bash ~/.agents/skills/agy-consult/scripts/consult.sh:*)` 這條絕對路徑 allow list 項目，但不阻斷。

---

## Step 1 — 執行

> **執行說明**：腳本把「filesystem boundary 提醒 + 使用者問題」以 inline 形式當 `-p` 的值傳入
> （`agy -p "$PROMPT_CONTENT" --add-dir . --sandbox`），沿用 `/agy-review` 的 `run.sh` 已驗證過的
> 安全模式（issue #153 / PR #229 retro）：不用 `@file`（nested worktree 下解析失敗會讓 agy 靜默
> 進入 agentic 模式）、不用 stdin pipe（`-p`/`--print` 不是 boolean，會把下一個 flag 當 prompt
> 吃掉；agy 1.1.2 起沒有 stdin prompt 通道）。`--add-dir .` 提供周邊程式碼 context。
> 直接執行即可，不要外加 log capture。

```bash
bash ~/.agents/skills/agy-consult/scripts/consult.sh "<問題>"
```

實際範例：

```bash
bash ~/.agents/skills/agy-consult/scripts/consult.sh "tasks/mycelium 的 db.py 裡 park_lesson 跟 finalize_reassessed_lesson 共享哪些不變量？"
```

---

## Step 2 — 呈現結果

Clean exit 後，呈現完整輸出，不截斷、不摘要。

**Exit-code gate**：agy 非零退出，停止並告知使用者：「agy 執行失敗，請確認 auth 或網路後重試。」
不可把失敗輸出當成答案呈現。

---

## FAQ

| 問題 | 解法 |
|------|------|
| `agy: command not found` | `pip install antigravity-cli`，確認 `agy` 在 PATH |
| Auth 失敗，`onboardingComplete` 為 false | 執行 `agy auth` 完成 OAuth 流程 |
| 無 API key 且 onboarding 未完成 | 在 `.env` 加入 `GEMINI_API_KEY=<your-key>` 或 `GOOGLE_API_KEY=<your-key>`（兩者均可） |
| `onboarding.json` 損毀（JSON 解析錯誤） | 刪除後重建：`rm ~/.gemini/antigravity-cli/cache/onboarding.json`，再執行 `agy auth` |
| 問題內容含雙引號 / `$VAR` / backtick | `consult.sh` 用單一位置參數傳入，Claude 呼叫時需確保問題字串本身用雙引號包住；複雜問題建議先簡化成一行敘述 |
| 想看 diff review 而非問答 | 改用 `/agy-review` |

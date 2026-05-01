---
name: pr-review-cycle
type: know
scope: global
description: >
  完整 PR 生命週期：從建立 PR 到 parallel review → fix → re-review → simplify → CI → merge。
  觸發情境：「跑 PR cycle」「review 這個 PR」「pr-review-cycle」「完整 PR 流程」
---

# PR Review Cycle

從建立 PR 到合併的完整流程，適用任何技術棧（Python / JS / Go / 其他）的 git 專案。

## 使用方式

```text
/pr-review-cycle
/pr-review-cycle #<PR number>   ← 已有 PR 時直接跳 Step 2
```

---

## Workflow

### Step 1 — 建立 PR

若尚未建立 PR，依序執行：

```bash
# 確認在 feature branch，不在 main
git branch --show-current

# commit 所有未提交的變更
git add <files>
git commit -m "..."

# push 並建立 PR
git push -u origin HEAD
gh pr create --title "..." --body "..."
```

若專案有安裝 `/commit-commands:commit-push-pr`，可直接執行（自動 commit + push + PR）。

記下 PR number，後續步驟使用。

---

### Step 2 — Parallel Review（平行啟動 4 個 agent）

在**同一則訊息**中平行啟動所有 review agents（`pr-review-toolkit` 各 subagent）：

| Agent | 聚焦面向 |
|-------|---------|
| `code-reviewer` | 專案規範合規、潛在 bug、邏輯錯誤 |
| `silent-failure-hunter` | 靜默失敗、exception 吞噬、不當 fallback |
| `pr-test-analyzer` | 測試覆蓋缺口、critical path 未測試 |
| `comment-analyzer` | 文件準確性、comment rot、誤導說明 |

彙整結果，分級：

- **Critical**（阻擋 merge）
- **Important**（應修）
- **Minor**（選修）

---

### Step 3 — Fix

依序處理 **Critical** → **Important**：

1. 修改程式碼

2. 每修完一批就跑本地 CI。先讀取專案根目錄找出實際的 CI 指令：

   ```bash
   # 找 CI 入口（依序確認）
   cat Makefile 2>/dev/null | grep -E "^ci:|^test:|^check:" | head -5
   cat package.json 2>/dev/null | python3 -c "import json,sys; s=json.load(sys.stdin).get('scripts',{}); [print(k,':',v) for k,v in s.items() if k in ('test','ci','check')]"
   cat pyproject.toml 2>/dev/null | grep -A2 "\[tool.pytest\|testpaths"
   ```

   常見 CI 指令對照：

   | 技術棧 | 典型本地 CI 指令 |
   |--------|----------------|
   | Python (make) | `make ci` |
   | Python (bare) | `uv run pytest` / `pytest` |
   | Node.js | `npm test` / `npm run ci` |
   | Go | `go test ./...` |
   | Rust | `cargo test` |

   若失敗，**先修好再繼續**，不跳過。

3. commit（訊息描述修了什麼，不要 "fix review comments"）：

   ```bash
   git commit -m "fix(...): ..."
   git push
   ```

---

### Step 4 — Re-review

對**本次修改的檔案**重跑 Step 2 的 agents：

```bash
git diff main...HEAD --name-only   # 確認範圍
```

確認所有 Critical / Important 問題已解決。若有新問題，回到 Step 3。

---

### Step 5 — Simplify

執行 `/simplify`，對 PR 全部變更跑三個向度的 review（reuse / quality / efficiency）。

將任何簡化改動作為**獨立 commit**，方便 reviewer 看 diff：

```bash
git commit -m "refactor(...): simplify per /simplify review"
git push
```

---

### Step 6 — CI Check

等待 GitHub Actions 全部通過：

```bash
gh pr checks {{pr_number}} --watch
```

若 CI 失敗：

1. 先在本地重現（使用 Step 3 找到的本地 CI 指令）
2. 修好，commit，push
3. 重新等待 CI

本地 CI 是權威：CI 與本地結果不一致時，以本地工具輸出為準，檢查 CI 環境差異（Python 版本、環境變數、快取等）。

---

### Step 7 — Merge

CI 全綠後 squash merge：

```bash
gh pr merge {{pr_number}} --squash --delete-branch
```

回報 merge commit URL 給使用者。

---

## 常見問題處理

| 問題 | 處理方式 |
|------|----------|
| Step 2 agent 沒有 git diff 可讀 | 先執行 Step 1 建立 branch/PR |
| 找不到本地 CI 指令 | 讀 `Makefile` / `package.json` / `pyproject.toml`，或問使用者 |
| Linter 失敗 | 查對應工具的 `--fix` 選項（ruff: `ruff check --fix`；eslint: `--fix`；gofmt: 自動格式化） |
| Type checker 失敗 | 確認 untyped 第三方庫的設定（mypy: `follow_imports = skip`；tsc: 加 `@types/<pkg>` 或設 `skipLibCheck: true`）|
| Security scanner 失敗 | 加對應工具的忽略註解（bandit: `# nosec BXXX`；等），並在 PR 說明原因 |
| Re-review 發現新問題 | 回 Step 3，不要直接 merge |
| CI 與本地結果不一致 | 以本地 CI 為準，比對 CI/本地的工具版本與環境變數差異 |
| 想跳過某個 review agent | 可以，但必須說明原因 |

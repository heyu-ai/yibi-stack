---
name: mycelium-handover
type: tool
scope: global
description: >
  跨對話、跨裝置、跨 Agent 的工作交班系統。使用 SQLite + JSONL 保存工作狀態，
  避免 context rot 和 compact 資訊遺失。
  寫入情境：用戶說「/handover」、「交班」、「記錄進度」、「切換任務」、
  「我要換到另一台電腦繼續」、「切到 Gemini/Codex 繼續」、「context 快滿了」。
  讀取情境：用戶說「handover back」、「讀取上次進度」、「我回來了」、「上次做到哪」、
  「show handover」、「resume from handover」、「帶我回到上次的工作」。
  是 `agents` skill 的子 skill。
---

# agents handover：跨對話工作交班系統

## 設計哲學

LLM 的 context 是揮發性的，但工作狀態不應該是。三個關鍵洞察：

1. **Context Rot**：context 越大，模型對早期資訊的注意力越差
2. **Context Anxiety**：context 接近上限時會焦慮、草草結束
3. **Compact 不可控**：LLM 自己壓縮 context 時，你無法控制它丟掉什麼

與其讓 context 膨脹到 rot，不如主動寫入結構化交班記錄，用乾淨 context 重新開始。

## 兩層 Schema

### Layer 1：Universal（人 & 任何 Agent 都能讀）

| 欄位 | 說明 |
|---|---|
| id | UUID |
| timestamp | ISO 8601 |
| operator | 操作者 |
| session_type | `sdd` / `debug` / `discussion` / `admin` |
| topic | 這次工作的主題 |
| conversation_summary | 對話重點摘要 |
| completed | 完成了什麼 |
| decisions | 做了哪些決策 |
| blocked | 卡住的事項 |
| next_priorities | 下一步優先事項 |
| lessons_learned | 這次學到什麼 |
| attempted_approaches | 試過什麼方案（debug 時特別重要） |
| tags | 自由標籤 |

### Layer 2：Environment-specific

| 欄位 | 說明 |
|---|---|
| device | 裝置名稱（自動填 config.json 的 device_id） |
| agent_type | `claude` / `gemini` / `codex` / ... |
| subscription_account | 帳號（自動三層 fallback） |
| branch | Git branch（自動讀） |
| working_dir | 工作目錄 |
| project | 專案名稱（自動 = git repo 名稱；worktree 下回傳主 repo 名稱） |
| last_files | 最後處理的檔案 |
| test_status | 測試狀態摘要 |
| token_usage_estimate | token 使用量 |

## 步驟

> **執行位置**：本 skill 可從任何 cwd 觸發。先跑 Step 1 的腳本捕捉原始
> project（worktree-safe），並 preflight PATH 中 installed `mycelium`。

### Step 1 — 環境確認

```bash
_gcd=$(git rev-parse --git-common-dir 2>/dev/null)
case "$_gcd" in
    /*)
      _dir=$(dirname "$_gcd")
      ORIG_PROJECT=$(basename "$_dir")
      unset _dir ;;
    ?*)
      _top=$(git rev-parse --show-toplevel)
      ORIG_PROJECT=$(basename "$_top")
      unset _top ;;
    *)
      ORIG_PROJECT=$(basename "$PWD") ;;
esac
unset _gcd
if ! command -v mycelium >/dev/null 2>&1; then
  echo '[FAIL] 缺少 mycelium，請執行：uv tool install "yibi-stack @ git+https://github.com/heyu-ai/yibi-stack@v1.11.0"' >&2
  exit 1
fi
ls ~/.agents/handover/handover.db
```

若 DB 不存在，先跑 `mycelium init`。

### Step 2 — 寫入交班

```bash
mycelium handover write \
  --session-type {{debug|sdd|discussion|admin}} \
  --topic "{{topic}}" \
  --summary "{{summary}}" \
  --completed '["修復 parser", "加 unit test"]' \
  --decisions '["改用 nom 做解析"]' \
  --blocked '["API rate limit 未處理"]' \
  --next '["處理 rate limit"]' \
  --lessons '["nom 比 regex 更穩定"]' \
  --approaches '["試過 regex 太脆弱", "split 邊界條件多"]' \
  --tags '["parser","rust"]' \
  --project "$ORIG_PROJECT"
```

未提供的 metadata 會自動偵測：`device` / `agent_type` / `account` / `branch` / `working_dir`；
`project` 一律使用 Step 1 捕捉的明確值。

### Step 3 — 讀取交班（Handover Back）

用戶說「handover back」、「我回來了」、「讀取上次進度」時，先偵測當前專案再讀取：

```bash
# 用 Step 1 捕捉的 ORIG_PROJECT（git-common-dir 兩步式，worktree 下回傳主 repo 名稱，
# 與 handover write 的 detect_project() 一致；basename "$PWD" 在 worktree / 子目錄會回傳錯誤名稱）
mycelium handover read --last 3 --project "$ORIG_PROJECT"

# 讀取目前專案最近 4 筆
mycelium handover read --last 4 --project "$ORIG_PROJECT"

# 原始 JSON
mycelium handover read --last 4 --project "$ORIG_PROJECT" --json
```

讀取後，根據 `next_priorities` 提示使用者下一步是什麼。

### Step 4 — 搜尋

```bash
mycelium handover search --query "parser" --project "$ORIG_PROJECT"
mycelium handover search --query "bug" --type debug --limit 5 --project "$ORIG_PROJECT"
mycelium handover search --project flight-mcp
mycelium handover search --account claude-pro --project "$ORIG_PROJECT"
```

## 交班時機建議

主動建議使用者交班的情境：

1. 對話 token 超過 60% context window
2. 完成一個明確的任務段落
3. 使用者要 /clear → 先 handover 再 clear
4. 偵測到自己開始摘要或寫 SUMMARY.md（context anxiety 信號）
5. 使用者要離開 / 切 Agent / 切機器

## 跨 Agent 使用

當使用者說「我要切到 Gemini/Codex 繼續」：

1. 執行 `handover write`（Layer 1 純文字 LLM 都看得懂）
2. 把輸出的 conversation_summary / completed / next_priorities / lessons_learned 格式化貼給新 Agent：

```markdown
## Handover Summary

**Topic**: [topic]
**Session Type**: [session_type]
**What was done**: [completed]
**Key decisions**: [decisions]
**Blocked**: [blocked]
**Next steps**: [next_priorities]
**Lessons learned**: [lessons_learned]
**Approaches tried**: [attempted_approaches]
```

## 常見問題

| 問題 | 解法 |
|------|------|
| 找不到 DB | 先跑 `mycelium init` |
| session_type 無效 | 只能是 sdd / debug / discussion / admin 四選一 |
| --completed 格式錯誤 | 必須是合法 JSON array，例：`'["a","b"]'` |
| 跨機器看到不同內容 | 確認 Syncthing 已同步；或用 JSONL 鏡像手動 import |

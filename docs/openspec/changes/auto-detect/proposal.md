# Proposal：auto-detect

> 版本：v1.0 | 日期：2026-04-16 | 狀態：Draft

## 背景

目前 `detect_account()` 與 `detect_agent_type()` 只有兩層 fallback（env var → config.json 靜態值），導致：

- 同一台機器切換 Gmail / 公司帳號時，必須手動改 env var 或 config.json
- `_registry/accounts.json` 永遠是空陣列，registry 形同虛設
- Gemini CLI、Codex CLI 的帳號資訊明明可以自動讀取，卻需要手動設定

本 proposal 設計 **Adapter Pattern + 四層 fallback** 的自動偵測機制，讓 account 與 agent_type 在大多數情境下零配置自動填充。

---

## Layer 1 — User Stories

### 四元素萃取

| 元素 | 內容 |
|------|------|
| **Actors** | Claude Code hook、Gemini CLI hook、Codex CLI hook、CLI 使用者 |
| **Actions** | 偵測當前帳號 email、偵測 agent 類型、查詢帳號清單、首次問詢並緩存 |
| **Data** | `~/.gemini/google_accounts.json`、`~/.codex/auth.json`、`~/.claude/.claude.json`、`_registry/accounts.json` |
| **Constraints** | Claude Code 無法從本機取得 email（只有 SHA256 hash）；各 agent credential 格式不同；不得讀取私鑰或 token 本體 |

---

### US-001：Gemini 帳號自動偵測

**Persona**：使用 Gemini CLI 的 howie，每次開 session 都登入 `howie@gmail.com` 或 `howie@heyuai.com.tw` 其中一個。
**Action**：不設任何 env var，執行 Gemini 的 handover write 或 insight 收集。
**Outcome**：`subscription_account` / `account` 欄位自動填入正確的 email，不需手動介入。

**Acceptance Criteria**：

- AC-001-1：GIVEN `~/.gemini/google_accounts.json` 存在且 `active` 欄位有值，WHEN `detect_account()` 被呼叫且 `AGENT_ACCOUNT` 未設定，THEN 回傳 `active` 的 email 值
- AC-001-2：GIVEN `~/.gemini/google_accounts.json` 不存在或 `active` 為空，WHEN `detect_account()` 被呼叫，THEN fallback 到下一層（config.json → "unknown"）
- AC-001-3：GIVEN 偵測到新 email 且 `_registry/accounts.json` 中不存在此 email，WHEN 偵測成功後，THEN 自動將此帳號寫入 `accounts.json`

---

### US-002：Codex CLI 帳號自動偵測

**Persona**：使用 Codex CLI 的 howie，credential 儲存於 `~/.codex/auth.json`。
**Action**：不設 env var，執行 Codex 環境下的帳號偵測。
**Outcome**：自動解碼 JWT `id_token` 取得 email。

**Acceptance Criteria**：

- AC-002-1：GIVEN `~/.codex/auth.json` 存在且 `tokens.id_token` 為有效 JWT，WHEN `detect_account()` 被呼叫，THEN 解碼 JWT payload 中間段（base64url），回傳 `email` 欄位
- AC-002-2：GIVEN `tokens.id_token` 解碼失敗（格式錯誤、欄位缺失），WHEN `detect_account()` 被呼叫，THEN 靜默 fallback，不拋出例外
- AC-002-3：GIVEN `OPENAI_API_KEY` 有設定但 `tokens` 不存在，WHEN `detect_account()` 被呼叫，THEN fallback 到 config.json（API key 模式無法取得 email）

---

### US-003：Claude 帳號偵測（hash 對照表）

**Persona**：使用 Claude Code 的 howie，在 Mac Pro 用 claude-pro（`howie@gmail.com`），Mac Mini 用 claude-team（`howie@heyuai.com.tw`）。
**Action**：首次執行時被問詢 email，之後自動對照。
**Outcome**：`~/.claude/.claude.json` 的 userID hash 與 email 的對應關係持久化在 `_registry/accounts.json`，不需每次重問。

**Acceptance Criteria**：

- AC-003-1：GIVEN `~/.claude/.claude.json` 存在且 `_registry/accounts.json` 有此 userID hash 的對應記錄，WHEN `detect_account()` 被呼叫，THEN 直接回傳對應的 email，不詢問使用者
- AC-003-2：GIVEN `~/.claude/.claude.json` 存在但 `accounts.json` 中沒有此 userID 的對應記錄，WHEN 第一次偵測時，THEN 透過 `agents account link-claude` 指令引導使用者輸入 email 並儲存對照
- AC-003-3：GIVEN `~/.claude/.claude.json` 不存在，WHEN `detect_account()` 被呼叫，THEN 跳過 Claude adapter，繼續 fallback

---

### US-004：agent_type 由呼叫端帶入

**Persona**：各 hook（Claude stop hook、Gemini hook）的開發者。
**Action**：在 hook 腳本或 CLI 呼叫時明確傳入 `agent_type`。
**Outcome**：`agent_type` 不靠環境推斷，由最了解執行上下文的呼叫端決定。

**Acceptance Criteria**：

- AC-004-1：GIVEN hook 呼叫 `detect_agent_type(caller="claude")`，WHEN 函式執行，THEN 回傳 `"claude"` 不論任何環境狀態
- AC-004-2：GIVEN `AGENT_TYPE` env var 有設定，WHEN `detect_agent_type()` 被呼叫，THEN env var 的值優先（override 呼叫端預設值）
- AC-004-3：GIVEN 呼叫端未傳入 `caller` 且 `AGENT_TYPE` 未設定，WHEN 函式執行，THEN fallback 到 `config.json default_agent`，再 fallback 到 `"claude"`

---

## Layer 2 — 功能規格

### FS-001：GeminiAccountAdapter.detect()

**追溯**：AC-001-1, AC-001-2（US-001）

1. **輸入約束**：無輸入參數；讀取 `~/.gemini/google_accounts.json`
2. **處理邏輯**：系統 SHALL 讀取 `AGENTS_HOME / ".." / ".gemini" / "google_accounts.json"`
   （即 `Path.home() / ".gemini" / "google_accounts.json"`）；若檔案存在 SHALL 解析 JSON；SHALL 取 `data["active"]`；若 `active` 為非空字串 SHALL 回傳此值
3. **輸出／副作用**：MUST 回傳 `str | None`；`None` 代表無法偵測，呼叫端繼續 fallback
4. **不做什麼**：MUST NOT 讀取 `oauth_creds.json` 或任何 token 檔案；本規格不負責 Gemini 登入狀態驗證
5. **錯誤處理**：若檔案不存在、JSON 解析失敗、`active` 欄位缺失，SHALL 靜默回傳 `None`，不拋例外

---

### FS-002：CodexAccountAdapter.detect()

**追溯**：AC-002-1, AC-002-2, AC-002-3（US-002）

1. **輸入約束**：無輸入參數；讀取 `~/.codex/auth.json`
2. **處理邏輯**：系統 SHALL 讀取 `Path.home() / ".codex" / "auth.json"`；SHALL 取 `data["tokens"]["id_token"]`；SHALL 用 base64url 解碼中間段（payload 部分，以 `.` 分割後取索引 1）；SHALL 解析 JSON payload；SHALL 取 `payload["email"]`
3. **輸出／副作用**：MUST 回傳 `str | None`；`None` 代表無法偵測
4. **不做什麼**：MUST NOT 驗證 JWT 簽章；MUST NOT 讀取 `access_token` 本體；不負責 token 過期判斷
5. **錯誤處理**：任一步驟失敗（檔案不存在、JSON 錯誤、`tokens` 缺失、JWT 格式錯誤、`email` 欄位缺失），SHALL 靜默回傳 `None`

---

### FS-003：ClaudeAccountAdapter.detect()

**追溯**：AC-003-1, AC-003-2, AC-003-3（US-003）

1. **輸入約束**：無輸入參數；讀取 `~/.claude/.claude.json`；查詢 `_registry/accounts.json`
2. **處理邏輯**：SHALL 讀取 `Path.home() / ".claude" / ".claude.json"` 取得 `userID`（SHA256 hash）；
   SHALL 在 `_registry/accounts.json` 中尋找 `agent_type == "claude"` 且 `hash == userID` 的記錄；
   若找到 SHALL 回傳對應的 `email`；若未找到 SHALL 回傳 `None`（不詢問，詢問由 `agents account link-claude` 指令負責）
3. **輸出／副作用**：MUST 回傳 `str | None`
4. **不做什麼**：MUST NOT 直接詢問使用者；MUST NOT 嘗試反解 SHA256
5. **錯誤處理**：`.claude.json` 不存在、JSON 錯誤、`accounts.json` 讀取失敗，SHALL 靜默回傳 `None`

---

### FS-004：detect_account() 四層 fallback

**追溯**：AC-001-1, AC-002-1, AC-003-1（US-001-003）

1. **輸入約束**：`agent_type: str = "claude"`（呼叫端傳入，決定優先使用哪個 adapter）；`warn: bool = True`
2. **處理邏輯**：
   - 層 1：若 `AGENT_ACCOUNT` env var 有非空值，SHALL 直接回傳
   - 層 2：依 `agent_type` 選擇對應 adapter，呼叫 `adapter.detect()`；若回傳非 `None` SHALL 觸發 FS-005 自動註冊後回傳
   - 層 3：載入 `config.json`，若 `default_account` 非 `None` 非空字串，SHALL 回傳
   - 層 4：若 `warn=True` SHALL 印 stderr warning；SHALL 回傳 `"unknown"`
3. **輸出／副作用**：MUST 回傳 `str`（永不回傳 `None`）
4. **不做什麼**：MUST NOT 在 fallback 過程中拋出例外；不負責 UI 互動
5. **錯誤處理**：任何 adapter 的內部錯誤已在 adapter 層處理；本層不需額外 try/except

---

### FS-005：AccountRegistry.auto_register()

**追溯**：AC-001-3（US-001）

1. **輸入約束**：`email: str`（非空）；`agent_type: str`；`extra: dict` 選用（如 Claude 的 `hash`）
2. **處理邏輯**：SHALL 讀取 `REGISTRY_DIR / "accounts.json"`；若 email + agent_type 組合已存在 SHALL 直接回傳（冪等）；若不存在 SHALL append 新記錄並寫回
3. **輸出／副作用**：MUST 寫入 `accounts.json`；回傳 `bool`（True 代表新增，False 代表已存在）
4. **不做什麼**：MUST NOT 覆蓋既有記錄；不負責 registry 格式遷移
5. **錯誤處理**：檔案寫入失敗 SHALL 印 stderr warning，MUST NOT 拋出例外（偵測失敗不應中斷主流程）

---

### FS-006：detect_agent_type() 更新

**追溯**：AC-004-1, AC-004-2, AC-004-3（US-004）

1. **輸入約束**：新增 `caller: str | None = None` 參數；`default: str = "claude"` 維持
2. **處理邏輯**：
   - 層 0（新增）：若 `caller` 非 `None` 非空 SHALL 作為初始預設值（可被 env var 覆蓋）
   - 層 1：若 `AGENT_TYPE` env var 有非空值，SHALL 優先回傳
   - 層 2：若 `caller` 有值，SHALL 回傳 `caller`
   - 層 3：載入 `config.json`，若 `default_agent` 有值，SHALL 回傳
   - 層 4：回傳 `default` 參數（預設 `"claude"`）
3. **輸出／副作用**：MUST 回傳 `str`
4. **不做什麼**：MUST NOT 讀取任何 credential 檔案
5. **錯誤處理**：config.json 讀取失敗 SHALL 靜默繼續 fallback

---

### FS-007：agents account link-claude 指令

**追溯**：AC-003-2（US-003）

1. **輸入約束**：互動式指令，不接受 CLI 參數（改為 prompt 詢問）
2. **處理邏輯**：SHALL 讀取 `~/.claude/.claude.json` 的 `userID`；SHALL 用 `click.prompt()` 詢問使用者 email；SHALL 驗證 email 格式（包含 `@`）；SHALL 呼叫 `AccountRegistry.auto_register()` 寫入 accounts.json，帶 `extra={"hash": userID}`
3. **輸出／副作用**：SHALL 印確認訊息；MUST 寫入 `accounts.json`
4. **不做什麼**：MUST NOT 驗證 email 是否真實存在；不負責 Claude 登入
5. **錯誤處理**：`.claude.json` 不存在 SHALL 印錯誤並 exit(1)；email 格式不合法 SHALL 重新詢問（最多 3 次）

---

## Layer 4 — 假設與約束

## 假設

| # | 假設內容 | 若不成立的影響 |
|---|----------|----------------|
| A1 | `~/.gemini/google_accounts.json` 的 `active` 欄位在切換帳號後會即時更新 | 可能偵測到舊帳號；影響 handover/insight 的 account 欄位準確性 |
| A2 | `~/.codex/auth.json` 的 JWT `id_token` 格式穩定，email 欄位持續存在 | Codex 更新可能導致 adapter 失效；需維護 |
| A3 | Claude Code 的 `~/.claude/.claude.json` userID 在重新登入後不會改變 | 需要重新執行 `link-claude` 重新建立對照 |
| A4 | 使用者在單一機器上不會同時用同一 agent 的兩個帳號（但可以不同 agent 用不同帳號） | 若同機器 Claude 同時登多帳號，hash 對照表機制失效 |

## 硬性限制

| # | 限制 | 來源 |
|---|------|------|
| C1 | Claude Code 本機無法取得帳號 email，只有 SHA256 hash | `~/.claude/.claude.json` 的設計 |
| C2 | 偵測邏輯不得 throw exception，必須 fallback | session_memory 現有慣例：偵測失敗不應中斷主流程 |
| C3 | 不讀取 token 本體（access_token、refresh_token）、不驗證 JWT 簽章 | 安全性原則：只讀取公開 claims，不碰 credential |
| C4 | detect_account() 的 API 簽章保持向後相容（新增 `agent_type` 參數需有預設值） | 避免破壞現有 insight_hook.py 和 handover_service.py 的呼叫 |

## Out of Scope

| 功能 | 排除原因 | 未來考量 |
|------|----------|----------|
| ChatGPT / OpenAI API key 模式帳號偵測 | API key 模式無帳號 email 概念 | 若 OpenAI 加入 OAuth 再評估 |
| claude.ai web 帳號偵測 | 需 Chrome MCP，屬於 daily-summary 範疇 | Phase 2 的 inbox 功能 |
| 多帳號同時登入的 session 切換 | A4 假設限制；複雜度過高 | 未來若有需求再設計 |
| token 有效期判斷 | 過期 token 的 JWT payload 仍可讀到 email | 若有 stale data 問題再處理 |
| Gemma local / Ollama 帳號偵測 | 本地模型無帳號概念 | 不適用 |

---

## Layer 5 — 可測試性

## Done 定義

此功能視為「完成」的條件：

- [ ] FS-001 ~ FS-007 均已實作
- [ ] `detect_account(agent_type="gemini")` 在有 `google_accounts.json` 時自動回傳 email
- [ ] `detect_account(agent_type="codex")` 在有 `auth.json` 時自動回傳 email
- [ ] `detect_account(agent_type="claude")` 在 hash 對照表存在時自動回傳 email
- [ ] `agents account link-claude` 指令可執行並寫入 accounts.json
- [ ] 新帳號首次偵測後自動出現在 `_registry/accounts.json`
- [ ] 所有 adapter 在 credential 檔案不存在時不拋例外
- [ ] 既有 `insight_hook.py` 和 `handover_service.py` 的呼叫無需修改（向後相容）
- [ ] 單元測試覆蓋 FS-001 ~ FS-007 的所有 AC

## 冒煙測試情境

### ST-001：Gemini 帳號自動填充

- GIVEN `~/.gemini/google_accounts.json` 存在，`active` = `"howie@gmail.com"`，且 `AGENT_ACCOUNT` 未設定
- WHEN 執行 `detect_account(agent_type="gemini")`
- THEN 回傳 `"howie@gmail.com"`，且 `accounts.json` 新增一筆 gemini 帳號記錄

### ST-002：Codex JWT 解碼

- GIVEN `~/.codex/auth.json` 存在，`tokens.id_token` 為含 email 的有效 JWT
- WHEN 執行 `detect_account(agent_type="codex")`
- THEN 回傳 JWT payload 中的 `email`

### ST-003：Claude hash 對照表命中

- GIVEN `~/.claude/.claude.json` 存在，`accounts.json` 有此 userID hash 的對應記錄
- WHEN 執行 `detect_account(agent_type="claude")`
- THEN 回傳對應 email，不詢問使用者

### ST-004：全部 adapter 失敗的 fallback

- GIVEN 所有 credential 檔案不存在，`AGENT_ACCOUNT` 未設定，`config.json` 的 `default_account` 為 `null`
- WHEN 執行 `detect_account(warn=False)`
- THEN 回傳 `"unknown"`，無例外、無 stderr 輸出

### ST-005：env var override

- GIVEN `AGENT_ACCOUNT` = `"override@example.com"`，且 `~/.gemini/google_accounts.json` 有 active 值
- WHEN 執行 `detect_account(agent_type="gemini")`
- THEN 回傳 `"override@example.com"`（env var 優先於 adapter）

## QA 技術建議

- FS-001 ~ FS-003 adapter：使用 `tmp_path` + mock 檔案內容，覆蓋「正常路徑」與「各種失敗路徑」的等價類別
- FS-004 fallback 邏輯：決策表測試（4 層 fallback × 各層有值/無值 的組合）
- FS-005 registry 寫入：測試冪等性（同一 email 寫兩次不重複）

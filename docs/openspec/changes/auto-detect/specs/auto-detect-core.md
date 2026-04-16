# Delta Specs：auto-detect-core

> 對應規格：`docs/openspec/changes/auto-detect/proposal.md`
> 變更類型：ADDED（初版）

## FS-001：GeminiAccountAdapter

**GIVEN** `~/.gemini/google_accounts.json` 存在，`active` = `"howie@gmail.com"`
**WHEN** `GeminiAccountAdapter().detect()` 被呼叫
**THEN** 回傳 `"howie@gmail.com"`

**邊界值測試情境**：

- `active` = `""` → 回傳 `None`
- `active` 欄位不存在 → 回傳 `None`
- 檔案不存在 → 回傳 `None`
- JSON 格式錯誤 → 回傳 `None`（不拋例外）

---

## FS-002：CodexAccountAdapter

**GIVEN** `~/.codex/auth.json` 存在，`tokens.id_token` 為含 `email: "howie@gmail.com"` 的 JWT
**WHEN** `CodexAccountAdapter().detect()` 被呼叫
**THEN** 回傳 `"howie@gmail.com"`

**邊界值測試情境**：

- JWT 格式錯誤（不含 `.`）→ 回傳 `None`
- payload 解碼後 JSON 無 `email` 欄位 → 回傳 `None`
- `tokens` 欄位缺失 → 回傳 `None`
- `OPENAI_API_KEY` 有值但 `tokens` 為 null → 回傳 `None`
- 檔案不存在 → 回傳 `None`

---

## FS-003：ClaudeAccountAdapter

**GIVEN** `~/.claude/.claude.json` 存在，`userID` = `"abc123"`，`accounts.json` 有 `{"email": "howie@gmail.com", "agent_type": "claude", "hash": "abc123"}`
**WHEN** `ClaudeAccountAdapter().detect()` 被呼叫
**THEN** 回傳 `"howie@gmail.com"`

**邊界值測試情境**：

- `accounts.json` 無此 hash 對應 → 回傳 `None`（不詢問使用者）
- `~/.claude/.claude.json` 不存在 → 回傳 `None`
- `accounts.json` 空陣列 → 回傳 `None`

---

## FS-004：detect_account() fallback 決策表

| env var | adapter 結果 | config.json | 預期回傳 |
|---------|-------------|-------------|----------|
| 有值 | 任何 | 任何 | env var 的值 |
| 未設 | email | 任何 | email（同時 auto_register） |
| 未設 | None | 有值 | config.json 的 default_account |
| 未設 | None | None | `"unknown"` |

---

## FS-005：AccountRegistry.auto_register() 冪等性

**GIVEN** `accounts.json` 已有 `{"email": "howie@gmail.com", "agent_type": "gemini", ...}`
**WHEN** `auto_register("howie@gmail.com", "gemini")` 再次被呼叫
**THEN** 回傳 `False`，`accounts.json` 記錄數不增加

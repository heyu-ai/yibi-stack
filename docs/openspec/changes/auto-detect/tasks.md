# tasks.md — auto-detect

> [PRIORITY-REVIEW] 優先序由系統自動推導，請確認後移除此行。

## Phase 1：Setup

- [ ] T001 [P] 建立 `AccountAdapter` 抽象介面 — target: `tasks/session_memory/adapters/base.py`
- [ ] T002 [P] 建立 `AccountRegistry` 讀寫介面 + `AccountRecord` dataclass — target: `tasks/session_memory/registry.py`

## Phase 2：Foundational（adapters）

- [ ] T003 [P] 實作 `GeminiAccountAdapter` — target: `tasks/session_memory/adapters/gemini.py`
- [ ] T004 [P] 實作 `CodexAccountAdapter`（JWT base64url 解碼）— target: `tasks/session_memory/adapters/codex.py`
- [ ] T005 [P] 實作 `ClaudeAccountAdapter`（hash 查表）— target: `tasks/session_memory/adapters/claude.py`
- [ ] T006 [P] adapter registry（依 agent_type 取 adapter）— target: `tasks/session_memory/adapters/__init__.py`

## Phase 3：User Stories（P1 → P2 → P3）

### US-001 + US-002 + US-003：帳號自動偵測（P1 — 核心路徑）

**Story Goal**：`detect_account(agent_type=...)` 依 Agent 類型自動取得 email
**Test Criteria**：FS-001 ~ FS-005 全數通過

- [ ] T010 [P] 更新 `detect_account()` 加入 adapter 層 + 四層 fallback — target: `tasks/session_memory/account.py`
- [ ] T011 [P] 更新 `detect_account()` 觸發 `AccountRegistry.auto_register()` — target: `tasks/session_memory/account.py`
- [ ] T012 [P] 撰寫 adapters 單元測試（GeminiAdapter、CodexAdapter、ClaudeAdapter）— target: `tasks/session_memory/tests/test_adapters.py`
- [ ] T013 [P] 撰寫 `detect_account()` 四層 fallback 決策表測試 — target: `tasks/session_memory/tests/test_account.py`

### US-004：agent_type 由呼叫端帶入（P2）

**Story Goal**：`detect_agent_type(caller=...)` 讓 hook 明確傳入類型
**Test Criteria**：FS-006 通過

- [ ] T020 更新 `detect_agent_type()` 加入 `caller` 參數（依賴 T010 完成）— target: `tasks/session_memory/account.py`
- [ ] T021 [P] 更新 `insight_hook.py` 傳入 `agent_type="claude"`（向後相容）— target: `tasks/session_memory/insight_hook.py`

### US-003：link-claude 指令（P2）

**Story Goal**：互動式指令讓使用者首次建立 Claude hash → email 對照

- [ ] T030 新增 `agents account link-claude` CLI 指令 — target: `tasks/session_memory/cli.py`
- [ ] T031 [P] 撰寫 link-claude 單元測試 — target: `tasks/session_memory/tests/test_cli.py`

## Phase 4：Polish & Cross-Cutting Concerns

- [ ] T040 [P] 更新 `handover_service.py` 的 `detect_account()` 呼叫，傳入 `agent_type`
- [ ] T041 [P] 更新 `skills/session-memory/SKILL.md` 的 FAQ，移除「不做 credentials 偵測」的說明，改為說明新偵測機制
- [ ] T042 [P] 更新 `skills/README.md` 若有相關說明需同步

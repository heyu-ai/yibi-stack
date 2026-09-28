# tasks.md — {{change-name}}

> [PRIORITY-REVIEW] 優先序由系統自動推導，請確認後移除此行。

## Phase 1：Setup

- [ ] T001 [P] {{task-description}} — target: `{{file-path}}`
- [ ] T002 [P] {{task-description}} — target: `{{file-path}}`

## Phase 2：Foundational

- [ ] T003 [P] {{task-description}} — target: `{{file-path}}`
- [ ] T004 [P] {{task-description}} — target: `{{file-path}}`

## Phase 3：User Stories

### {{US-title}}（P1 - 核心路徑）

**Story Goal**：{{goal}}
**Test Criteria**：{{scenario slugs}} 通過；`check_testplan_trace.py --report --change {{change-name}}` 中本 US 的 auto TC 皆為 `bound`

- [ ] T010 [USn] Red-first：撰寫綁定 `tc: {{auto TC-IDs of this US}}` 的失敗測試，確認在實作前為紅燈 — target: `{{test-file-path}}`
- [ ] T011 [USn] {{task-description}}（依賴 T010）— target: `{{file-path}}`

> 每個 US 的第一個任務固定是 red-first 測試：測試的 docstring 同時寫 `spec: <cap>#<slug>` 與
> `tc: <TC-ID>`，實作前必須是紅燈（與 pr-cycle-deep Step 1.7 red-first gate 一致：PR 的測試要抓得到 PR 的改動）。

## Phase 4：Integration

- [ ] T020 {{integration-task}} — target: `{{file-path}}`

## Task Markers

- `[P]` = 可與其他任務平行執行（parallelizable）
- `[USn]` = 對應 User Story 編號
- 無標記 = 有前序依賴，須照順序執行
- `[O]` = Optional（nice-to-have）

## 追溯說明

每個 task 應追溯回 proposal.md 的 US / AC 編號與 Gherkin scenario slug，確保規格與實作雙向可追蹤。

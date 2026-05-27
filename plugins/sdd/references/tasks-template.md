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
**Test Criteria**：{{scenario slugs}} 通過

- [ ] T010 [P] {{task-description}} — target: `{{file-path}}`
- [ ] T011 [P] 撰寫測試 — target: `{{test-file-path}}`

## Phase 4：Integration

- [ ] T020 {{integration-task}} — target: `{{file-path}}`

## Task Markers

- `[P]` = 可與其他任務平行執行（parallelizable）
- `[USn]` = 對應 User Story 編號
- 無標記 = 有前序依賴，須照順序執行
- `[O]` = Optional（nice-to-have）

## 追溯說明

每個 task 應追溯回 proposal.md 的 US / AC 編號與 Gherkin scenario slug，確保規格與實作雙向可追蹤。

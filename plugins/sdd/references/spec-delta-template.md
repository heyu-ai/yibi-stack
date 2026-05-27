# Delta Specs：{{feature-name}}

> 對應規格：`docs/openspec/changes/{{change-name}}/proposal.md`
> 變更類型：ADDED（初版）

每個 delta spec 對應一個 Scenario，用 `#### Scenario: <slug>` 格式描述可測試的行為。

---

## US-001：{{user-story-title}}

### AC-001-1

#### Scenario: {{slug-001}} -- {{spec-title}}

**GIVEN** {{前置條件（系統狀態、輸入資料）}}
**WHEN** `{{function_or_operation}}` 被呼叫
**THEN** {{期望結果}}

**[ADDED]** {{新增的行為描述}}

**邊界值測試情境**：

- `{{edge-case-input}}` → {{expected-result}}
- `{{edge-case-input}}` → {{expected-result}}（不拋例外）
- 輸入不存在 → 靜默回傳 `None` / 空結果

### AC-001-2

#### Scenario: {{slug-002}} -- {{spec-title}}

**GIVEN** {{前置條件}}
**WHEN** {{操作}}
**THEN** {{期望結果}}

**[MODIFIED]** {{修改描述：原行為 → 新行為}}

---

## Delta Marker 說明

| Marker | 意義 |
|--------|------|
| `[ADDED]` | 此版本新增，原本不存在 |
| `[MODIFIED]` | 原有行為調整，可能有 breaking change |
| `[REMOVED]` | 此版本移除，使用者需遷移 |

無 marker 的 GIVEN/WHEN/THEN = 描述不變的穩定行為（regression test 基準）。

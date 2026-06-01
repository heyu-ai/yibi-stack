# Test Plan：add-token-economy-harness

> Change: `add-token-economy-harness` | Capability: `token-economy-scanner`
> Convention: `.claude/rules/09-test-conventions.md`（host convention）
> Generated: 2026-06-01

---

## TC Table

| TC-ID | Scenario Slug | Test Purpose | Technique | Precondition | Steps | Expected Result |
|-------|--------------|-------------|-----------|-------------|-------|----------------|
| TE-DT-001 | `high-always-on-warn` | always-on proxy > 20000 chars triggers WARN + score penalty | DT | tmp_path：CLAUDE.md=10001 chars + rules/01.md=10000 chars | `scan_token_economy(target_dir)` | findings 含 `WARN always-on context` + char count；`score < max_score` |
| TE-DT-002 | `low-always-on-ok` | always-on proxy ≤ 5000 chars → OK finding | DT | tmp_path：CLAUDE.md=4999 chars，無 rules/ | `scan_token_economy(target_dir)` | findings 含 `OK always-on context`；`score >= max_score - 1` |
| TE-DT-003 | `score-decreases-with-token-growth` | 分數隨 always-on 增加單調遞減；> 20000 → 分數 ≤ max_score−3 | DT | dir A=5000 chars，dir B=30000 chars | 各別 `scan_token_economy()` | `score(A) > score(B)`；`score(B) <= max_score - 3` |
| TE-DT-004 | `low-progressive-disclosure-warn` | on_demand/total < 0.3 觸發 WARN + 數值比例 | DT | CLAUDE.md=8000 chars，無 skills/ | `scan_token_economy(target_dir)` | findings 含 `WARN progressive-disclosure 比例過低` + 數值 |
| TE-DT-005 | `adequate-progressive-disclosure-ok` | on_demand/total ≥ 0.5 → OK | DT | CLAUDE.md=2000 chars；skills/foo/SKILL.md body=4000 chars | `scan_token_economy(target_dir)` | findings 含 `OK progressive-disclosure` |
| TE-DT-006 | `claude-md-rules-overlap-warn` | ≥3 個共同高頻詞 → WARN + 詞清單（≤5 個）| DT | CLAUDE.md 與 rules/01.md 共享 ≥5 個高頻非停用詞 | `scan_token_economy(target_dir)` | findings 含 `WARN CLAUDE.md↔rules 重疊` + ≤5 個重疊詞 |
| TE-DT-007 | `no-overlap-ok` | < 3 個共同高頻詞 → OK | DT | CLAUDE.md 與 rules 詞彙明顯不同（僅 1 個共用詞）| `scan_token_economy(target_dir)` | findings 含 `OK no CLAUDE.md↔rules redundancy detected` |
| TE-DT-008 | `long-skill-no-effort-warn` | body > 2000 chars 且無 effort: → WARN + skill 名稱 | DT | skills/slow/SKILL.md：valid frontmatter 無 effort:，body="x"×2001 | `scan_token_economy(target_dir)` | findings 含 `WARN effort 未設定` 與 skill 目錄名 `slow` |
| TE-DT-009 | `short-skill-no-effort-ok` | body ≤ 2000 chars 且無 effort: → 不觸發 WARN | DT | skills/fast/SKILL.md：valid frontmatter 無 effort:，body="x"×2000 | `scan_token_economy(target_dir)` | findings 不含 `WARN effort 未設定` |
| TE-EG-001 | `findings-include-disclaimer` | 任何非空 findings 包含近似值聲明 | EG | 使用 TE-DT-001 的高 always-on dir | `scan_token_economy(target_dir)` | ≥1 條 finding 含 `字元估計（非精準 token 計量）` |
| TE-EG-002 | `skill-body-counted-as-on-demand` | SKILL.md body chars 計入 on_demand，不計入 always_on | EG | CLAUDE.md=1000 chars；skills/foo/SKILL.md body=3000 chars | `scan_token_economy(target_dir)`；檢查 extra 或 ratio 變化 | `on_demand_chars >= 3000`；always_on_chars 不包含 SKILL.md body |
| TE-EG-003 | `overlap-word-list-bounded` | 重疊詞清單不超過 5 個，即使實際重疊詞更多 | EG | CLAUDE.md 與 rules 共享 10+ 高頻詞 | `scan_token_economy(target_dir)` | WARN finding 中列出的詞 ≤ 5 個 |
| TE-ST-001 | `effort-check-isolated-to-d11` | D11 effort WARN 不影響 D4 score | ST | skills/ 含 long SKILL.md 無 effort:（D4 structure valid）| `run_scan(target_dir)` 完整 D1–D11 | D11 findings 含 WARN；D4 `score` 不變；D4 findings 無 effort WARN |
| TE-ST-002 | `run-scan-includes-d11` | `run_scan` 包含 D11 維度在 ScanOutput.dimensions | ST | 任意 valid target_dir | `run_scan(target_dir)` | dimensions 含 `dimension == "D11"`；`total_mechanical_max` 反映 D11 加入 |
| TE-VL-001 | `score-never-negative` | MechanicalFinding score 不可為負 | VL | 直接 model 實例化 | `MechanicalFinding(score=-1, ...)` | 拋出 `ValidationError` |
| TE-VL-002 | `score-capped-at-max` | 理想 dir 的 score ≤ max_score | VL | CLAUDE.md=1000 chars；skills/good/SKILL.md effort:low，body≤2000 | `scan_token_economy(target_dir)` | `result.score <= result.max_score` |
| SMK-001 | `smoke-minimal-dir` | 空目錄不 crash | SMK | 空 tmp_path | `scan_token_economy(tmp_path)` | 回傳 MechanicalFinding，無 exception |

---

## Coverage Analysis

| Scenario Slug | Status | 對應 TC-ID | Notes |
|--------------|--------|-----------|-------|
| `high-always-on-warn` | ✓ covered | TE-DT-001 | AC-001-1 |
| `low-always-on-ok` | ✓ covered | TE-DT-002 | AC-001-2 |
| `score-decreases-with-token-growth` | ✓ covered | TE-DT-003 | AC-001-3 |
| `findings-include-disclaimer` | ✓ covered | TE-EG-001 | AC-001-4；reuses DT-001 fixture |
| `low-progressive-disclosure-warn` | ✓ covered | TE-DT-004 | AC-002-1 |
| `adequate-progressive-disclosure-ok` | ✓ covered | TE-DT-005 | AC-002-2 |
| `skill-body-counted-as-on-demand` | ✓ covered | TE-EG-002 | AC-002-3；requires extra fields exposed |
| `claude-md-rules-overlap-warn` | ✓ covered | TE-DT-006 + TE-EG-003 | AC-003-1（DT-006=WARN present，EG-003=word cap）|
| `no-overlap-ok` | ✓ covered | TE-DT-007 | AC-003-2 |
| `long-skill-no-effort-warn` | ✓ covered | TE-DT-008 | AC-004-1 |
| `short-skill-no-effort-ok` | ✓ covered | TE-DT-009 | AC-004-2 |
| `effort-check-isolated-to-d11` | ✓ covered | TE-ST-001 | AC-004-3 |
| `smk-high-always-on` | ✓ covered | TE-DT-001 + TE-ST-002 | CLI path via run_scan |
| `smk-low-always-on` | ✓ covered | TE-DT-002 | — |
| `smk-scan-speed` | △ partial | — | 100ms 效能驗證需 `time.perf_counter`；建議 TE-EG 補充一個 timing test |
| `smk-no-effort-skill` | ✓ covered | TE-DT-008 | — |
| `smk-disclaimer` | ✓ covered | TE-EG-001 | — |

> △ partial — `smk-scan-speed`：建議補 TE-EG-004 使用 `time.perf_counter` 驗證 < 0.1s。

---

## Implementation Notes

- `scan_token_economy` 為新 D11 scanner，位於 `tasks/harness_eval/scanners/token_economy.py`
- `MechanicalFinding.extra` 應暴露 `always_on_chars`、`on_demand_chars`（list[str] 格式）
  供 TE-EG-002 的 testability
- 詞頻重疊偵測需維護停用詞列表；TE-DT-007 採明顯不同詞彙避免 stopword 邊界問題
- 所有測試使用 `make_target(tmp_path, ...)` helper，對齊現有 `test_scanners.py` 慣例

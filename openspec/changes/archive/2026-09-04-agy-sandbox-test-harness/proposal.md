## Problem

pr-cycle-deep 的三支 agy 腳本（stage1、stage2、R2）在 headless 模式下反覆遭遇 sandbox 權限阻擋檔案讀取的問題。根本原因是 agy 的 `--sandbox` 模式會 auto-deny `command` 工具，而 headless `-p` 模式無法互動確認——agy exits 0 但 stdout 為空，靜默失敗。

目前的 workaround 是 stage1/R2 使用權限繞過旗標、stage2 使用 `--sandbox`，但**零個測試釘住這個 permission flag contract**，導致問題反覆發生：

1. **Permission flag 選擇無測試保護**：有人改 flag 不會被抓到
2. **空輸出 guard 不對稱**：`agy-consult`/`agy-review`（3rd-tools）有最小字元數檢查，pr-cycle-deep 的 stage2/R2 只用 `-s`（非空），sandbox auto-deny 的空檔案可能通過
3. **agy 版本未 pin**：腳本註解 "verified on 1.1.12" 但無 runtime 版本驗證，升級後行為改變不會被偵測
4. **auto-deny stderr 訊息未被偵測**：agy 在 sandbox 下被 auto-deny 時 exits 0 + 空 stdout + stderr 寫 "a tool required the command permission"，腳本看到 rc=0 以為成功

## Root Cause

agy 的 `--sandbox` 模式設計：`read_file`/`ListDirectory` 在 `--add-dir` 範圍內放行，但 `command`（shell 執行）被 auto-deny。headless `-p` 模式無互動終端可核准，agy 直接 auto-deny 並 exit 0。這是 agy 上游行為，repo 內無法修復根本原因。

測試層面的根因：現有 `test_agy_scripts.py` 有 AGYS-DT-001~013 測試釘住 inline prompt、`--add-dir` 絕對路徑、model pinning、validator flags 等不變量，但遺漏了 **permission flag contract** 和 **sandbox auto-deny 空輸出偵測** 這兩個維度。

## Proposed Solution

三層測試策略，從靜態到動態逐層加固：

### Layer 1: Permission Flag Contract（靜態斷言）

在 `test_agy_scripts.py` 新增 `TestPermissionFlagContract` class，斷言每支腳本使用正確的 permission flag：
- stage1/R2 必須使用權限繞過旗標（需要 `command` 工具探索周邊程式碼）
- stage2 必須使用 `--sandbox`（純文字萃取，不需 `command`）
- 互斥斷言：同一腳本不得同時出現兩個 flag

### Layer 2: Stub 模擬 auto-deny（runtime 驗證）

擴充現有 `_FAKE_AGY` stub 機制：新增一個 sandbox-deny 模式的 stub，模擬 agy 在 `--sandbox` 下收到 `command` 請求時的行為（exit 0 + 空 stdout + stderr auto-deny 訊息），驗證腳本的 guard 能偵測到並 `[FAIL]`。

### Layer 3: 版本 probe script + Makefile target

新增 `scripts/probe-agy-sandbox.sh`，手動驗證 agy 的 sandbox 行為是否跟腳本預期一致。做成 `make probe-agy` target，在 agy 升級時手動執行。CI 無法自動化（需 agy auth），但提供結構化的 SOP。

## Non-Goals

- 不修改 agy 上游行為（sandbox auto-deny command 是 agy 設計決策）
- 不將權限繞過旗標改回 `--sandbox`（目前 workaround 已驗證有效）
- 不在 CI 中自動呼叫真實 agy（需 auth + API 費用）
- 不修改 `agy-consult`/`agy-review`（3rd-tools 插件）的空輸出 guard（該問題屬於獨立 scope）

## Success Criteria

1. 若有人不小心把 stage1/R2 的權限繞過旗標改成 `--sandbox`，pytest 會立即失敗
2. 若有人不小心把 stage2 的 `--sandbox` 改成權限繞過旗標，pytest 會立即失敗
3. 若 agy 升級後 sandbox auto-deny 行為改變，`make probe-agy` 能偵測到差異
4. 所有新增測試通過 `uv run pytest`

## Step 4 — 假設與約束

### 假設（衍生自 problem-frame.md W）

| # | 假設內容 | 若不成立的影響 |
|---|----------|----------------|
| A1 (W1) | agy 腳本的 permission flag 出現在 agy 呼叫行的 literal 文字中（不透過變數間接組裝）| 靜態文字斷言會 false-negative，需改用 runtime stub 驗證 |
| A2 (W2) | agy 的 sandbox auto-deny 行為是 exit 0 + 空 stdout + stderr 訊息（而非 exit non-zero）| stub 的模擬行為需同步更新 |
| A3 (W3) | `agy_validate.py` 或 `-s` 檢查會對空輸出 exit non-zero | 若不成立，需在腳本補強空輸出 guard（tasks 2.3 已預留此條件分支）|
| A4 (W4) | agy 的 `--sandbox` + `--add-dir` 仍允許 `read_file`/`ListDirectory`（只擋 `command`）| 若不成立，stage2 也需改用權限繞過旗標，整個合約需重新設計 |

### 硬性限制

| # | 限制 | 來源 |
|---|------|------|
| C1 | CI 不能呼叫真實 agy（需 auth + API 費用）| 基礎設施限制 |
| C2 | probe script 必須在無 auth 時 graceful `[SKIP]`，不能 hard fail | 可用性要求 |

### Out of Scope

| 功能 | 排除原因 | 未來考量 |
|------|----------|----------|
| 修改 agy 上游 sandbox 行為 | 非本 repo 控制範圍 | 若 agy 未來支援細粒度 sandbox permission，可移除 permission-bypass workaround |
| 3rd-tools `agy-consult`/`agy-review` 的空輸出 guard 對稱化 | 獨立 scope，與本 change 的 pr-cycle-deep 聚焦不同 | 可做為 follow-up change |
| CI 自動化 probe（真實 agy 呼叫）| 需 auth + 費用 | 若未來 CI 有 agy auth，可把 probe 加入 CI pipeline |

## Step 5 — 完工標準

### Done 定義

此功能視為「完成」的條件：
- [ ] TestPermissionFlagContract（DT-014/015/016）全部通過
- [ ] TestSandboxAutoDenyDetection（ST-005/006）全部通過
- [ ] probe-agy-sandbox.sh 語法正確（`bash -n` 通過）
- [ ] Makefile `probe-agy` target 可執行
- [ ] Mutation 驗證：flag 替換後對應測試變紅
- [ ] `make ci` 全通過

### Traceability Matrix

| AC | Scenario slug | TC-ID | pytest docstring |
|----|--------------|-------|-----------------|
| AC-001-1 | `review-flag-regressed-to-sandbox` | AGYS-DT-014 | `spec: agy-sandbox-permission-contract#review-flag-regressed-to-sandbox` |
| AC-001-2 | `extract-flag-regressed-to-bypass` | AGYS-DT-015 | `spec: agy-sandbox-permission-contract#extract-flag-regressed-to-bypass` |
| AC-001-3 | `mutual-exclusion-violated` | AGYS-DT-016 | `spec: agy-sandbox-permission-contract#mutual-exclusion-violated` |
| AC-002-1 | `stub-auto-deny-detected` | AGYS-ST-005 | `spec: agy-sandbox-permission-contract#stub-auto-deny-detected` |
| AC-002-2 | `genuine-sandbox-empty-output` | AGYS-ST-006 | `spec: agy-sandbox-permission-contract#genuine-sandbox-empty-output` |
| AC-003-1 | `probe-sandbox-file-read` | AGYS-VL-001 | manual probe |
| AC-003-2 | `probe-sandbox-command-deny` | AGYS-VL-002 | manual probe |
| AC-003-3 | `probe-bypass-full-access` | AGYS-VL-003 | manual probe |
| AC-003-4 | `probe-no-auth-graceful` | AGYS-EG-001 | manual probe |

## Impact

- Affected code:
  - Modified: `plugins/dev-cycle/skills/pr-cycle-deep/scripts/tests/test_agy_scripts.py`
  - New: `scripts/probe-agy-sandbox.sh`
  - Modified: `Makefile`（新增 `probe-agy` target）

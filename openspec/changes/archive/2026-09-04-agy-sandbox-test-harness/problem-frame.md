# Problem Frame: agy-sandbox-test-harness

## Frame 型別
主導：**Transformation**（把 agy 腳本的 permission flag 合約轉成可執行的測試斷言）
組合：**Information Display**（probe script 顯示 agy sandbox 行為的真實狀態）

## R — 需求（世界狀態）

pr-cycle-deep 的 agy 腳本使用的 permission flag 合約（stage1/R2 用權限繞過旗標、stage2 用 `--sandbox`）在任何 code 修改或 agy 版本升級後，仍然維持正確且可被偵測。具體而言：

1. permission flag 的錯誤替換（如 stage1 被改成 `--sandbox`）會在 CI 被抓到
2. agy sandbox auto-deny 造成的空輸出會被腳本自身的 guard 偵測到
3. agy 升級後 sandbox 行為假設是否仍成立，可被手動驗證

## S — 規格（機器在介面的可觀察行為）

- S1：`test_agy_scripts.py` 的 `TestPermissionFlagContract` class MUST 對三支腳本各斷言正確的 permission flag，且互斥
- S2：當 agy stub 模擬 sandbox auto-deny（exit 0 + 空 stdout），stage2 腳本 MUST exit non-zero 並輸出 `[FAIL]`
- S3：`scripts/probe-agy-sandbox.sh` MUST 對三項 sandbox 行為各輸出 `[PASS]` 或 `[FAIL]`，且在無 agy auth 時 graceful `[SKIP]`

## W — 領域假設

| # | 假設內容 | 若不成立的影響 |
|---|----------|----------------|
| W1 | agy 腳本的 permission flag 出現在 agy 呼叫行的 literal 文字中（不是透過變數間接組裝）| 靜態文字斷言會 false-negative，需改用 runtime stub 驗證 |
| W2 | agy 的 sandbox auto-deny 行為是 exit 0 + 空 stdout + stderr 訊息（而非 exit non-zero）| stub 的模擬行為需同步更新 |
| W3 | `agy_validate.py` 或 `-s` 檢查會對空輸出 exit non-zero | 若不成立，需在腳本補強空輸出 guard（tasks 2.3 已預留此條件分支）|
| W4 | agy 的 `--sandbox` + `--add-dir` 仍允許 `read_file`/`ListDirectory`（只擋 `command`）| 若不成立，stage2 也需改用權限繞過旗標，整個合約需重新設計 |

## 正確性論證（S ∧ W ⟹ R）

**R1（flag 替換被 CI 抓到）**：由 S1，TestPermissionFlagContract 對每支腳本斷言 literal flag 文字。由 W1，flag 以 literal 出現在腳本中。故 flag 被替換 → 斷言失敗 → CI 紅燈。R1 成立。

**R2（空輸出被偵測）**：由 S2，stub 模擬 auto-deny 行為（W2 定義的 exit 0 + 空 stdout）。由 W3，腳本的現有 guard 對空輸出 exit non-zero。故 auto-deny 發生 → 腳本偵測到 → exit non-zero。R2 成立。若 W3 不成立，tasks 2.3 補強 guard 使 W3 成立。

**R3（版本升級可驗證）**：由 S3，probe script 測試三項行為。由 W4，baseline 行為已知。故升級後跑 probe → 行為改變 → `[FAIL]` 顯示差異。R3 成立。

## Frame Concern 檢查表

### 通用
- [x] R 只描述世界狀態（permission flag 合約維持正確），不含機器內部實作
- [x] S 只描述機器在介面的可觀察行為（test fail/pass、script exit code、probe output）
- [x] W 列出所有領域假設（W1-W4），每條標明若不成立的後果
- [x] S ∧ W ⟹ R 逐條 R 推導成立

### Transformation 額外
- [x] 輸入領域所有合法值都有對應輸出（三支腳本各自有斷言；probe 的三項行為各有判定）
- [x] 不產生需求未要求的輸出（測試只斷言 flag 合約，不擴大範圍）

### Information Display 額外（probe script）
- [x] 顯示與真實世界的延遲假設：probe 是手動即時執行，無延遲問題
- [x] 不可觀測部分：無 agy auth 時 graceful `[SKIP]`（已標為已知限制）

## DBC 對應（文件化）

| DBC 概念 | 來自 frame | 落地機制 |
|----------|-----------|---------|
| require | W1: flag 以 literal 出現 | TestPermissionFlagContract 靜態斷言 |
| require | W2: auto-deny = exit 0 + 空 stdout | _FAKE_AGY_SANDBOX_DENY stub 模擬 |
| ensure | R1: flag 替換被偵測 | DT-014/015 mutation 驗證 |
| ensure | R2: 空輸出被偵測 | ST-005 behavioral test |
| invariant | W4: sandbox 允許 read_file 擋 command | probe-agy-sandbox.sh 三項 probe |

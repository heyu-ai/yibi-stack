---
type: bug
issues: [390, 530]
---

## Problem

#390 的 agy R1/R2 在真正工作樹執行，唯讀 prompt 與事後狀態比較不能阻止寫入。
#530 的 Step 2 直接呼叫內建 code-review，沒有明確 PR 目標或 findings 路徑過濾，
本機 main 落後時曾把無關 finding 送進修復。

## Root Cause

工作目錄與權限邊界未隔離；Step 2 未消費既有 fresh-fetch diff 的基準。
內建 code-review 的實際 base 演算法不是本 repo 可證明或修改的前提。

## Proposed Solution

- agy R1/R2 改讀獨立 HEAD snapshot，以 OS 檔案系統保護原工作樹、Git metadata 與 snapshot。
  保留 command 探索、認證、timeout 隔離、輸出驗證与事後比對；無可用 OS 防護則拒絕啟動。
- 將既有 setup-review-dir 提前至 Step 2，固定 fresh base/head/changed paths，警告落後的本機 main。
- 對結構化 Step 2 findings 進行確定性路徑過濾；只讓接受結果進入修復，拒絕項目與數量保留於 final 報告。

## Success Criteria

- AC-1: R1/R2 的 cwd 與 absolute add-dir 指向獨立 committed-HEAD snapshot；完整 tracked blob 不受 export-ignore 遺漏；不帶原始 .git/shared index/hardlink 或 untracked secrets。
- AC-2: relative、absolute、symlink、hardlink 與 Git-metadata 寫入探針均不能改動原資料；missing/unusable backend、髒 tracked tree／衝突均 loud fail，不能 unrestricted fallback。
- AC-3: 成功、失敗、timeout、SIGINT/SIGTERM 都保留原有 log／validator／timeout quarantine 行為，回收 owned process group 與暫存狀態；PRE/POST 原樹比較保留；不刪其他 session 的 shared scratch。
- AC-4: local main 落後且 PR branch 無 upstream 的真實 Git 對照中，scope 只來自 fresh fetched base 到 HEAD；fresh-main 對照結果相同。缺少 local main 不誤判失敗，損壞 ref 不冒充不存在。
- AC-5: 結構化 findings 只依 captured canonical changed paths admission，涵蓋 rename/deletion／特殊檔名；accepted item 除 file 正規化外保留原資料與 evidence，rejected item 原文／原因／數量保留在 audit。
- AC-6: malformed input、缺失或無效 manifest、HEAD 變動及 setup 失敗均不能留下可重用的舊 accepted 結果；合法空清單可通過；重跑只更新 final.md 的 owned audit 區塊，不覆蓋其他證據。
- AC-7: Step 2 明確指定 PR、先 fresh scope 再 filter；aggregation 與 Step 6 只消費 filtered findings；pre-filter fix/comment 不能繞過；scope 改變後不能沿用舊 admission。
- AC-8: wrappers、helpers、runbook、CHANGELOG 與 change artifacts 一致；受影響的 source-string／固定行數測試可退役，但可觀察安全／錯誤／生命週期行為必須由回歸測試與 smoke 支撐。
## Capabilities

### New Capabilities

- `review-execution-isolation`: agy reviewer 的一次性 snapshot、OS 防寫與生命週期。
- `review-finding-scope`: fresh PR scope 與 Step 2 finding admission/audit。

### Modified Capabilities

- `pr-review-convergence`: 同步已退役的固定文件行數上限；既有收斂、證據與必要內容檢查原則不變。

## Impact

- Modified: `plugins/dev-cycle/skills/pr-cycle-deep/scripts/agy-r1-stage1.sh`
- Modified: `plugins/dev-cycle/skills/pr-cycle-deep/scripts/agy-r2.sh`
- Modified: `plugins/dev-cycle/skills/pr-cycle-deep/scripts/setup-review-dir.sh`
- Modified: `plugins/dev-cycle/skills/pr-cycle-deep/SKILL.md`
- Modified: `plugins/dev-cycle/skills/pr-cycle-deep/scripts/tests/test_agy_scripts.py`
- Modified: `CHANGELOG.md`
- New: 隔離 helper、scope filter 及對應行為測試，均位於既有 review scripts 與 tests 目錄。

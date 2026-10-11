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

- AC-1：R1/R2 reviewer 讀得到 HEAD 檔案，但相對、絕對路徑與 symlink 寫入無法改變原工作樹或 Git metadata。
- AC-2：錯誤、timeout、signal 會停止 child 並清掉隔離目錄，原有 log／timeout／validator 契約仍可觀察。
- AC-3：缺少或失效的 OS backend 不呼叫 unrestricted agy；髒 tracked tree 不靜默以舊 HEAD 取代。
- AC-4：本機 main 落後且 PR branch 無 upstream 時，scope 仍等於 fresh base 到 HEAD 的 PR 變更。
- AC-5：diff 外 finding 被移出修復清單，完整保留拒絕原因与數量；diff 內結果保持原資料。
- AC-6：malformed findings 或 HEAD 已移動會失敗，舊 filtered 結果不得被重用；正常空清單有效。
- AC-7：Step 2、aggregation、Step 6 與 opt-in cleanup 均使用同一 scope 契約，不能繞過 filter 自動修复。

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

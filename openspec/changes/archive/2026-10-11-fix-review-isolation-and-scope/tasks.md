## 1. 隔離 reviewer 執行（#390）

- [x] 1.1 落實 Reviewers execute inside a protected disposable snapshot（Isolation interface）：committed-HEAD snapshot 與 backend fail-closed；驗證 relative/absolute/symlink/shared Git write probes 被擋且 source 可讀（AC-1、AC-2）。
- [x] 1.2 落實 Isolation preserves review output and cleanup contracts：遷移 R1/R2 wrappers，保留輸出／timeout／validator 與原樹比對，錯誤／signal 先停 process group 再清理；驗證 wrapper 行為測試與 CLI smoke（AC-3）。

## 2. Fresh PR scope 與 finding admission（#530）

- [x] 2.1 落實 Step 2 consumes a fresh immutable PR scope（Scope interface）：setup 發布 fresh base/head/changed paths manifest 與 local main 落後警告；以真實 tmp remote 的 stale-main/no-upstream 及 fresh-main 對照驗證（AC-4）。
- [x] 2.2 落實 Only admitted findings reach the repair list：findings filter 與 idempotent audit 保留 accepted data、完整 rejected item 與原因，錯誤／HEAD 變動失效舊產物；驗證 mixed/empty/malformed/rename/deletion 路徑（AC-5、AC-6）。

## 3. 整合與驗證

- [x] 3.1 更新 Step 2/3/5/6 與 opt-in cleanup，明確 PR 目標，禁止未過濾 finding 進修復，保留 final audit；逐段核對 CLI 介面與 runbook 的一致性（AC-7）。
- [x] 3.2 執行相關測試、lint／format 檢查與實際 CLI containment／filter smoke，更新 changelog，記錄 OS／上游驗證限制；無漏項後通過 Spectra validate/analyze。
- [x] 3.3 依 AC-8 的 fact sweep 同步 R1/R2 私有 HOME、OS 防寫與 Step 2 setup；將 Skill document line budget 替換為 Skill document contract validation，保留必要內容檢查、退役固定行數正確性裁決，驗證 Spectra validate/analyze 與 changed-file checks。
- [x] 3.4 依 howie 的交付裁決移除靜默 cleanup failure：安全恢復自有目錄權限，不跟隨外部 symlink，清除失敗時 exit 1 並記錄殘留路徑；以 R1/R2 不可變假憑證、無 backend 的目錄權限測試與真實 CLI 探針驗證（AC-3、AC-8）。

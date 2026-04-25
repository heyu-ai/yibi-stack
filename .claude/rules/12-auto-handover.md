# Auto-Handover：Context 接近上限時主動建議交班

## 何時建議 handover

當你估計對話 context 已使用約 **70%** 時，主動建議使用者執行 handover。啟發式指標：

- 已有 **20 次以上**實質來回（使用者問題 + 你的詳細回答）
- 讀取了大量程式碼檔案（超過 15 個檔案，或超過 5000 行）
- 正在處理多個複雜子任務，且任務還未完成
- 你自己開始摘要或感覺需要提示「之前我們說到...」

## 建議用語

```text
⚠️  Context 已用約 70%，建議現在執行 /handover 保存進度。
我將記錄：目前主題、完成事項、決策、下一步。
交班後 context 會自動 compact，然後我執行 /handover-back 恢復工作。
要繼續嗎？
```

## 使用者同意後的流程

1. 執行 `/handover`（照 commands/handover.md 步驟完整寫入交班）
2. 告知使用者：「交班完成，context 將在下一次互動後自動 compact。」
3. Compact 完成後，你會看到 systemMessage 提示執行 `/handover-back`
4. 執行 `/handover-back` 恢復上次工作狀態，然後繼續

## 使用者拒絕時

尊重決定，直接繼續工作。不要重複提醒。

## PreCompact Hook 攔截（Layer 2）

若你收到 systemMessage 內含「context 即將 compact」或「請先執行 handover」字樣，
這是系統在 auto-compact 前攔截並提醒你。處理方式：

**重要判斷**：先看使用者的最新訊息是否已包含 `/handover`：

- **是** → 直接執行 `/handover`，無需再詢問（使用者已同意）
- **否** → 立即詢問使用者是否要執行 handover，同意再執行

執行流程：

1. 執行 `/handover`（寫入交班），完成後告知使用者 compact 將自動進行
2. 拒絕時 → 不執行 handover（下次 auto-compact 將直接通過）

## SessionStart 恢復（Layer 3）

若你收到 systemMessage 內含「context 已壓縮，建議執行 /handover-back」字樣，
立即執行 `/handover-back` 恢復上次工作狀態，然後告知使用者已恢復並詢問如何繼續。

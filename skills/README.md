# Skills 索引

此目錄為 agent 執行介面層。每個 skill 對應一個日常工作任務，包含完整的 step-by-step runbook。

## 可用 Skills

| Skill | 描述 | SKILL.md | 相依工具 |
|-------|------|----------|---------|
| `gmail-scan` | 通用 Gmail 掃描（非金融類），支援多 profile 郵件搜尋與附件下載。金融帳單請用 gmail-billing | [skills/gmail-scan/SKILL.md](gmail-scan/SKILL.md) | `gws` CLI, `uv` |
| `gmail-billing` | 從 Gmail 掃描金融帳單 PDF，自動下載、解密、分類、轉 CSV。支援 on-demand 補掃與每季定期批次匯入 | [skills/gmail-billing/SKILL.md](gmail-billing/SKILL.md) | `gws` CLI, `uv`, Java Runtime |
| `einvoice-blank-upload` | 上傳空白未使用發票號碼到財政部電子發票整合服務平台（每兩個月） | [skills/einvoice-blank-upload/SKILL.md](einvoice-blank-upload/SKILL.md) | `uv`, Playwright, 人工 CAPTCHA |

## 執行方式

1. 選擇對應的 skill
2. 開啟 `SKILL.md`
3. 照步驟依序執行

## 新增 Skill

參考 [`_template/SKILL.md`](_template/SKILL.md) 取得標準格式。

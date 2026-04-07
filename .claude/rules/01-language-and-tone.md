# 雙語慣例（Language & Tone）

## Code Identifiers — 英文

所有程式碼識別符（variable、function、class、module、parameter 名稱）一律使用英文：

```python
# 正確
def load_config(profile_name: str) -> BillingConfig: ...

# 錯誤
def 載入設定(設定檔名稱: str) -> ...: ...
```

## 文字內容 — 繁體中文（zh-TW）

以下內容一律使用繁體中文台灣用語：

- Module/class/function docstrings
- `click.echo()` 輸出訊息
- 錯誤訊息（RuntimeError、ValueError 等）
- 程式碼內的說明性 comment
- SKILL.md 的所有 prose

```python
"""CLI 入口：Gmail 帳單掃描。"""

raise RuntimeError("環境變數 GMAIL_TOKEN 未設定，請先執行 setup 指令")

click.echo(f"✓ 已匯入 {count} 筆帳單記錄")
```

## 標點符號

中文文字使用全形標點：，、。：；！？「」『』

不要在中文句子中混用半形標點（,  .  :  ;  !  ?）。

## SKILL.md 例外

SKILL.md 中的 code blocks、shell 指令、tool names 使用英文，其餘 prose 用中文。

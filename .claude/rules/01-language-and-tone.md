# Layered Language Strategy

## Code Identifiers — English

All code identifiers (variable, function, class, module, parameter names) must use English:

```python
# Correct
def load_config(profile_name: str) -> BillingConfig: ...

# Wrong
def 載入設定(設定檔名稱: str) -> ...: ...
```

## User-Facing Output — Traditional Chinese (zh-TW)

All user-visible output uses Traditional Chinese (Taiwan):

- Module/class/function docstrings
- `click.echo()` output messages
- Error messages (RuntimeError, ValueError, etc.)
- Explanatory code comments

```python
"""CLI 入口：Gmail 帳單掃描。"""

raise RuntimeError("環境變數 GMAIL_TOKEN 未設定，請先執行 setup 指令")

click.echo(f"✓ 已匯入 {count} 筆帳單記錄")
```

## Punctuation

Chinese text uses full-width punctuation: ，、。：；！？「」『』

Do not mix half-width punctuation (, . : ; ! ?) into Chinese sentences.

## SKILL.md

Code blocks, shell commands, and tool names use English; all other prose uses Traditional Chinese.

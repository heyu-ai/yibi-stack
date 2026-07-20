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

## Conversational Replies — Mirror the User's Input Language

The sections above govern **artifacts** (docstrings, `click.echo()`, comments). This one governs
the **assistant's own chat replies**, which is a separate and far more frequently violated layer.

Rule: before composing **any** reply, check the language of the user's most recent message.
If it contains CJK characters (U+4E00–U+9FFF), write the entire reply in 繁體中文台灣用語 —
identifiers, CLI flags, and code fences keep their original English form.

An explicit language instruction — from the user, or from a project/global setting like this
repo's CLAUDE.md — always overrides this character-range heuristic. The range is a fast backstop
for the common case, not a language classifier: U+4E00–U+9FFF also covers Japanese kanji and
Simplified Chinese, so treat it as "reply in the user's language" with 繁中 as this repo's default,
not as "any CJK byte forces Traditional Chinese".

"Any reply" is literal. The observed failures were never the main answer; they were the
small utterances that feel exempt:

- the opening action sentence of a turn (`Let me check...`, `I'll run the...`)
- mid-task progress and status updates during a long workflow
- skill bootstrap narration and diagnostic steps
- tool-call narration between two tool invocations

Three mechanisms cause the drift. Knowing them is what makes the rule actionable:

| Mechanism | What happens |
| --- | --- |
| **Tool-call re-entry** | The language decision is made once at session start and silently dropped when the turn resumes after a tool call or context switch. |
| **`thinking` in English** | When reasoning opens in English, the reply inherits that language — the first prose line comes out English before anything "decides" to switch. |
| **English tool output** | Surrounding English stdout/stderr biases the reply language, even though tool output is data, not a language signal. |

So the check must be **re-run per reply**, not per session, and it keys off the *user's message*
only — never off the language of tool output or of your own reasoning.

Evidence: the nightly self-improvement agent independently rediscovered this friction on roughly
**26 branches across a six-day window** (2026-07-14 → 2026-07-19; the exact count comes from the
dedup pipeline's record, not from surviving refs, which are fewer after merges/deletions), making
it by far the most frequently observed friction in the repo's history. See PR #279 for the dedup
pipeline that stopped the re-reporting; this rule addresses the underlying behavior.

## Punctuation

Chinese text uses full-width punctuation: ，、。：；！？「」『』

Do not mix half-width punctuation (, . : ; ! ?) into Chinese sentences.

## SKILL.md

Code blocks, shell commands, and tool names use English; all other prose uses Traditional Chinese.

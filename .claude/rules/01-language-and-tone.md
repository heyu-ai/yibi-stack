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

Rule: before composing **any** reply, mirror the language of the user's most recent message —
reply in the language the user wrote in, keeping identifiers, CLI flags, and code fences in their
original English form. For this repo the operative case is Chinese: whenever the user writes in
Chinese, write the entire reply in 繁體中文台灣用語.

A CJK character-range check (U+4E00–U+9FFF) is a fast backstop for spotting that common case, not
a language classifier — the range also covers Japanese kanji and Simplified Chinese, so do not read
"the message contains a CJK byte" as "force Traditional Chinese". An explicit language instruction —
from the user, or from a project/global setting like this repo's CLAUDE.md — always wins over the
heuristic.

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

This is the most frequently observed friction in the repo's history (nightly-agent reports,
about 26 branches in six days; dedup pipeline in PR #279).

## Punctuation

Chinese text uses full-width punctuation: ，、。：；！？「」『』

Do not mix half-width punctuation (, . : ; ! ?) into Chinese sentences.

## SKILL.md

Code blocks, shell commands, and tool names use English; all other prose uses Traditional Chinese.

## Rule Files (`.claude/rules/**`) — English

The explanatory prose in **this repo's own rule files** is English. Identifiers, CLI flags, JSON
keys and commands inside code fences stay English everywhere (see the first section); this one
covers only the surrounding prose.

**This is a per-repo declaration, not a global default.** `~/.claude/CLAUDE.md` deliberately gives
no default for rule-file prose. The resolution order is: (1) the repo's own language-policy
file, if it declares one; (2) otherwise, the majority of that repo's existing rule files.

Measured 2026-08-06 — this declaration matches current state, so **no existing file needs
rewriting**:

| repo | `.claude/rules/` | declared |
|------|------------------|----------|
| yibi-stack (this repo) | 15 / 15 English | English (here) |
| ainization-skill | 18 / 18 Traditional Chinese | Traditional Chinese |
| yibi-mvp | 20 zh / 6 en / 3 mixed | Traditional Chinese (`04-language-policy.md`) |

**Sibling repos differ by design — do not "harmonize" across repos.** Each is internally
consistent.

The criterion is **whether the text is compared verbatim by a machine**, not file location
("it lives in `.claude/rules/`, so it is for agents, so English" is the wrong inference). Rule files are read by humans as much as by agents — incident
pointers, rejected alternatives and their reasons all need to be quickly readable — so their prose
belongs to the human-readable class, and each repo picks the language its readers use.

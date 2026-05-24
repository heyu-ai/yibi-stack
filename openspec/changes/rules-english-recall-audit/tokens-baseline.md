# Token Baseline -- always-loaded rules (pre-PR-C)

**Measured**: 2026-05-24
**Tokenizer**: tiktoken cl100k_base (local, no API cost; ~5-15% variance vs Claude tokenizer)
**Branch**: origin/main post-PR-B (#50)
**Rules measured**: 6 always-loaded (no `globs:` frontmatter)

## Per-file breakdown

| Rule file | Chars | Tokens (pre-PR-C) | t/char |
|-----------|-------|-------------------|--------|
| `01-language-and-tone.md` | 684 | 408 | 0.596 |
| `02-error-and-import.md` | 1,887 | 883 | 0.468 |
| `03-security.md` | 1,495 | 735 | 0.492 |
| `13-bash-anti-patterns.md` | 21,657 | 11,810 | 0.545 |
| `15-irreversible-operations.md` | 5,777 | 3,398 | 0.588 |
| `16-allowlist-hygiene.md` | 8,218 | 4,118 | 0.501 |
| **TOTAL** | **39,718** | **21,352** | **0.538** |

## Post-PR-C target

| Metric | Value |
|--------|-------|
| Pre-PR-C total tokens | 21,352 |
| Post-PR-C total tokens | TBD -- re-run after PR-C merges |
| Target reduction | >= 30% |
| Pass threshold | <= 14,946 tokens |

## Notes

- Tokenizer: tiktoken `cl100k_base` (GPT-4 tokenizer, local computation, zero API cost).
- Variance vs Claude tokenizer: ~5-15% for mixed Chinese/English content.
- t/char > 0.5 indicates significant CJK density; t/char ~0.25 is typical English prose.
- Re-run after PR-C merges to fill Post-PR-C column.

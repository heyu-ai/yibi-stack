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

## Post-PR-C actuals

**Measured**: 2026-05-25 (after PR #77 merged)

| Rule file | Chars | Tokens (post-PR-C) | t/char |
|-----------|-------|-------------------|--------|
| `01-language-and-tone.md` | 927 | 287 | 0.310 |
| `02-error-and-import.md` | 2,445 | 635 | 0.260 |
| `03-security.md` | 2,025 | 476 | 0.235 |
| `13-bash-anti-patterns.md` | 27,156 | 7,496 | 0.276 |
| `15-irreversible-operations.md` | 9,631 | 2,270 | 0.236 |
| `16-allowlist-hygiene.md` | 9,361 | 2,528 | 0.270 |
| **TOTAL** | **51,545** | **13,692** | **0.266** |

| Metric | Value |
|--------|-------|
| Pre-PR-C total tokens | 21,352 |
| Post-PR-C total tokens | 13,692 |
| Actual reduction | **35.9%** ✅ |
| Target reduction | >= 30% |
| Pass threshold | <= 14,946 tokens |

Note: chars increased (~30%) because English prose expands some sections, but token density dropped from 0.538 to 0.266 t/char — consistent with CJK → English tokenizer savings.

## Notes

- Tokenizer: tiktoken `cl100k_base` (GPT-4 tokenizer, local computation, zero API cost).
- Variance vs Claude tokenizer: ~5-15% for mixed Chinese/English content.
- t/char > 0.5 indicates significant CJK density; t/char ~0.25 is typical English prose.
- Re-run after PR-C merges to fill Post-PR-C column.

# Rule Trap Prompts

Mutation tests for rules 13 and 15. Each prompt is designed to trigger the exact mistake
a compressed rule section prevents. Run with `claude -p` against the trimmed rules; if the
AI avoids the anti-pattern, the verbose version was unnecessary.

## Usage

```bash
# Run one trap prompt
claude -p "$(cat tests/rule-traps/trap-pipe-exit-code.txt)"

# Compare with baseline (checkout main, run same prompt)
```

## Scoring

- **PASS**: AI avoids the anti-pattern AND uses the correct fix pattern
- **FAIL**: AI produces the anti-pattern (the compressed rule didn't change behavior)

If FAIL, add back the minimum additional detail and re-test.

# harness-eval Developer Reference

Developer-facing notes for the `tasks/harness_eval/` module.
Agent-facing runbook: `skills/harness-eval/SKILL.md`.

## Scanner Authoring Conventions

### `semantic_targets` must use absolute paths

When a scanner populates `MechanicalFinding.semantic_targets`, store **absolute** paths,
not paths relative to `target_dir`:

```python
# Correct: absolute path — semantic agent can Read this directly
semantic_targets = [str(tf) for tf in test_files[:_SEMANTIC_TARGET_LIMIT]]

# Wrong: relative path — agent Read fails because it needs an absolute path
semantic_targets = [str(tf.relative_to(target_dir)) for tf in test_files]
```

`extra["factory_helper_files"]` is an exception — the semantic agent checks only its
non-emptiness to award factory-helper sub-item points; it does not resolve the path strings.
Relative paths are therefore appropriate.

### `extra[...]` keys are informational metadata only

Keys added to `MechanicalFinding.extra` do not affect the mechanical score for that dimension.
They exist as hints for the semantic scoring agent or for human-readable output.
The `extra` field type is `dict[str, list[str]]`; any new key must conform to this type.

### OSError handling in file readers

Scanner helper functions that read individual files (e.g., `_has_factory_helpers`) may
silently skip unreadable files when the result is an additive list — an unreadable file
simply does not contribute to the list. Document this contract in the function docstring.

Top-level scoring paths (Makefile, `settings.json`) must surface read failures as
`WARN: ...` entries in `findings` so the caller knows why a scoring signal was absent.

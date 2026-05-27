---
name: warn-plugin-version-lockstep
enabled: true
event: bash
pattern: "plugins/[^/]+/package\\.json"
action: warn
---

# Plugin version lockstep check

You are modifying or staging `plugins/*/package.json`.
Make sure the corresponding `plugins/*/.claude-plugin/plugin.json` has the **same `"version"` value**.

These two files must stay in lockstep — Claude Code marketplace reads `plugin.json`,
while npm-style tooling reads `package.json`.
Divergence is invisible until a user installs the plugin and sees the wrong version.

Quick check:

```bash
grep '"version"' plugins/<name>/package.json plugins/<name>/.claude-plugin/plugin.json
```

**Source**: PR #112 mob review — both Claude and Codex independently flagged a 1.3.0 (plugin.json)
vs 1.4.0 (package.json) split that was missed before merge.

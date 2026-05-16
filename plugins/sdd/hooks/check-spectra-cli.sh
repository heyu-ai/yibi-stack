#!/usr/bin/env bash
# SessionStart hook: check if spectra CLI is installed.
# Silent when found; injects an additionalContext nudge when absent (degraded mode).

set -euo pipefail

if command -v spectra >/dev/null 2>&1; then
    exit 0
fi

MSG="[spectra plugin] spectra CLI not found in PATH. Amplifier methodology and openspec templates are fully usable without it. To enable archive/validate/analyze sub-flows, install Spectra.app for macOS: brew install --cask spectra-app (upstream: https://github.com/kaochenlong/spectra-app). macOS only -- Linux/Windows users can still use all skill methodology in degraded mode."

MSG_ESC=$(printf '%s' "$MSG" | sed 's/\\/\\\\/g; s/"/\\"/g')

if [ -n "${CURSOR_PLUGIN_ROOT:-}" ]; then
    printf '{\n  "additional_context": "%s"\n}\n' "$MSG_ESC"
elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -z "${COPILOT_CLI:-}" ]; then
    printf '{\n  "hookSpecificOutput": {\n    "hookEventName": "SessionStart",\n    "additionalContext": "%s"\n  }\n}\n' "$MSG_ESC"
else
    printf '{\n  "additionalContext": "%s"\n}\n' "$MSG_ESC"
fi

exit 0

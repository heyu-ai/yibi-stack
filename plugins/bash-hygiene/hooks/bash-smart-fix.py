#!/usr/bin/env python3
"""PreToolUse hook: Rule 2 detection with auto-fix.

Rule 2: "$(cmd)" subshell inside a double-quoted context triggers
  Unhandled node type: string in Claude Code's bash parser.

Two match levels:
  Standalone:  cmd "$(inner)"    -> auto-fix: VAR=$(inner) ; cmd "$VAR"
  Embedded:    echo "x $(inner)" -> manual guidance (can't safely extract)

Exit codes: 0 = allow, 2 = block
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from _audit_log import log_event as _log_event
except Exception:  # pragma: no cover

    def _log_event(*_a: object, **_kw: object) -> None:  # type: ignore[misc]
        pass


# Standalone: entire quoted token is "$(inner)" with no surrounding text.
_RULE2_STANDALONE = re.compile(r'"(\$\(([^()]+)\))"')
# Embedded: $(inner) appears inside a larger double-quoted string.
_RULE2_EMBEDDED = re.compile(r'"[^"]*(\$\(([^()]+)\))[^"]*"')

# Compound-command separators (including newline) before the matched token
# indicate the subshell executes after a state change; show manual guidance.
_COMPOUND_RE = re.compile(r"(?:&&|\|\||;|\||\n)\s*[^|&;]*$")

# Function-definition prefix: hoisting out of a function body changes scope.
_FUNCTION_RE = re.compile(r"\(\)\s*\{|\bfunction\b\s+\w")

# Candidate variable names for auto-hoist, ordered by specificity.
_VAR_CANDIDATES = [
    (("show-toplevel", "rev-parse", "git-common-dir"), "WT"),
    (("dirname",), "DIR"),
    (("basename",), "BASE"),
]
_VAR_FALLBACK = "TMP"


def _load_command() -> str:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return ""
    if data.get("tool_name") != "Bash":
        return ""
    command = data.get("tool_input", {}).get("command", "")
    return command if isinstance(command, str) else ""


def _name_unused(name: str, cmd: str) -> bool:
    """True if neither $name nor ${name} appears in cmd."""
    return f"${name}" not in cmd and f"${{{name}}}" not in cmd


def _var_name(inner_cmd: str, cmd: str) -> str:
    """Pick a variable name that does not already appear in cmd."""
    for keywords, name in _VAR_CANDIDATES:
        if any(kw in inner_cmd for kw in keywords) and _name_unused(name, cmd):
            return name
    if _name_unused(_VAR_FALLBACK, cmd):
        return _VAR_FALLBACK
    for i in range(1, 10):
        candidate = f"{_VAR_FALLBACK}{i}"
        if _name_unused(candidate, cmd):
            return candidate
    return _VAR_FALLBACK


def _quote_state_at(text: str, pos: int) -> tuple[bool, bool]:
    """Return (in_double, in_single) quote state at position pos.

    In bash, single quotes are fully literal — backslash has no special meaning
    inside them. Backslash escape only applies inside double-quoted strings.
    """
    in_double = False
    in_single = False
    i = 0
    while i < pos:
        c = text[i]
        # Backslash escapes the next char only inside double quotes.
        if c == "\\" and in_double:
            i += 2
            continue
        if c == '"' and not in_single:
            in_double = not in_double
        elif c == "'" and not in_double:
            in_single = not in_single
        i += 1
    return in_double, in_single


def _is_compound_prefix(prefix: str) -> bool:
    return bool(_COMPOUND_RE.search(prefix) or _FUNCTION_RE.search(prefix))


def _detect_rule2(cmd: str) -> tuple[str, str | None, int, int] | None:
    """Return (token, fix_or_None, start, end) for first valid Rule 2 match.

    fix is None when the subshell is embedded in a larger quoted string (auto-fix
    impossible) or when compound separators precede it (unsafe hoist). start/end
    are the matched span positions for position-based replacement.
    """
    # Check standalone matches first (can auto-fix).
    for m in _RULE2_STANDALONE.finditer(cmd):
        _, in_single = _quote_state_at(cmd, m.start())
        if in_single:
            continue
        full_match = m.group(0)
        inner_cmd = m.group(2).strip()
        # Rule 2 is specifically "outer double-quote -> $() -> inner double-quote"
        # conflict. VAR="$(cmd)" without nested double quotes is valid bash — skip.
        if '"' not in inner_cmd:
            continue
        prefix = cmd[: m.start()]
        if _is_compound_prefix(prefix):
            return (full_match, None, m.start(), m.end())
        var = _var_name(inner_cmd, cmd)
        fixed = cmd[: m.start()] + f'"${var}"' + cmd[m.end() :]
        return (full_match, f"{var}=$({inner_cmd})\n{fixed}", m.start(), m.end())

    # Check embedded matches (manual guidance only).
    # Rule 2B: "$(cmd)" without inner double-quotes still triggers Claude Code's
    # parser (documented in .claude/rules/14-shell-quoting-hygiene.md).
    # Exception: standalone "$(cmd)" in an assignment context (VAR="$(cmd)") with
    # no inner double-quotes is valid bash — skip to avoid false positives.
    for m in _RULE2_EMBEDDED.finditer(cmd):
        _, in_single = _quote_state_at(cmd, m.start())
        if in_single:
            continue
        is_standalone = len(m.group(0)) == len(m.group(1)) + 2
        if is_standalone and '"' not in m.group(2).strip():
            prefix = cmd[: m.start()]
            # Only skip genuine shell assignments: VAR="$(cmd)" or A=x B="$(cmd)".
            # Check the last command segment (after any &&/||/;/| separator) to
            # avoid false skips for arguments like `echo VAR="$(cmd)"` while still
            # allowing valid assignments after separators like `cd repo && WT="$(cmd)"`.
            last_seg = re.split(r"&&|\|\||[;|&\n]", prefix)[-1].lstrip()
            if re.match(r"^(?:\w+=\S*\s+)*\w+=$", last_seg):
                continue
        inner_expr = m.group(1)  # e.g., "$(git rev-parse HEAD)"
        return (inner_expr, None, m.start(), m.end())

    return None


def _print_fix(header: str, detail: str, fix: str) -> None:
    sep = "  " + "-" * 50
    indented = "\n".join(f"  {line}" for line in fix.splitlines())
    print(f"BLOCKED: {header}")
    print()
    if detail:
        print(f"  {detail}")
        print()
    print("  Corrected command:")
    print(sep)
    print(indented)
    print(sep)


def main() -> None:
    t_start = time.monotonic()
    cmd = _load_command()
    if not cmd:
        sys.exit(0)

    result = _detect_rule2(cmd)
    elapsed = int((time.monotonic() - t_start) * 1000)
    if result is None:
        _log_event("smart-fix", cmd, exit_code=0, duration_ms=elapsed)
        sys.exit(0)

    token, fix, start, end = result
    if fix is None:
        # Manual guidance: use position-based replacement for precision.
        manual_cmd = cmd[:start] + '"$VAR"' + cmd[end:]
        _print_fix(
            "Rule 2 -- double-quoted $(cmd) subshell",
            f"Found: {token}  |  Split manually: extract VAR=$(...) before the separator",
            "# Manual fix required -- hoist order depends on context:\n"
            f"# VAR=(...)\n# {manual_cmd}",
        )
    else:
        _print_fix(
            "Rule 2 -- outer double-quote wrapping $(cmd) subshell",
            f"Found: {token}  |  Trigger: Unhandled node type: string",
            fix,
        )
    _log_event("smart-fix", cmd, exit_code=2, block_reason="rule2-doublequote", duration_ms=elapsed)
    sys.exit(2)


if __name__ == "__main__":
    main()

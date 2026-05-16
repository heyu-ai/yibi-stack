#!/usr/bin/env python3
"""Extract the git -C <path> target from a shell command string.

Supports double-quoted, single-quoted, and unquoted -C paths.
Resolves $VAR references using the last assignment before the git -C position.
Fails closed (exit 2) when the path is unresolvable (command substitution,
unbound variable).

Usage:
    python3 parse_git_dir.py <command-string>
    Prints the resolved path to stdout; exits 2 if unresolvable.
"""

from __future__ import annotations

import re
import sys

# Match: git -C <path> [global-options] push
# Groups: 1=double-quoted, 2=single-quoted, 3=unquoted
# Between the -C path and the push subcommand, only git global options are
# allowed: -c key=value pairs and other -flag/--flag tokens.  Non-flag tokens
# (e.g. "add", "commit") indicate a different subcommand, so the pattern will
# not match — preventing false positives for `git -C /wt add push` (where
# "push" is a pathspec/message argument, not the push subcommand).
_C_PUSH_RE = re.compile(
    r"""git\s+-C\s+(?:"([^"]+)"|'([^']+)'|([^\s"']+))"""
    r"""(?:\s+-c\s+\S+|\s+-\S+)*\s+push(?:\s|$)"""
)

# Match: VARNAME=<value> (double-quoted, single-quoted, or bare word)
_VAR_ASSIGN_RE_TMPL = r"""\b{varname}=(?:"([^"]*)"|'([^']*)'|([^\s;&|]+))"""

# Token prefixes that cannot be resolved by static parsing.
_UNRESOLVABLE_PREFIXES = ("$(", "`")

# Exit codes (caller-facing contract).
EXIT_OK = 0
EXIT_UNRESOLVABLE = 2


def _first_group(match: re.Match[str]) -> str:
    """Return the first non-empty capture group from a 3-alt quote pattern."""
    return match.group(1) or match.group(2) or match.group(3) or ""


def resolve_git_dir(cmd: str) -> tuple[str, int]:
    """Resolve the git -C <path> target in cmd.

    Returns:
        ("",     EXIT_OK)            — no `git -C ... push` found
        (path,   EXIT_OK)             — resolved literal or $VAR substitution
        ("",     EXIT_UNRESOLVABLE)   — command substitution or unbound $VAR;
                                        caller must fail closed
    """
    c_match = _C_PUSH_RE.search(cmd)
    if not c_match:
        return ("", EXIT_OK)

    raw = _first_group(c_match)

    if raw.startswith(_UNRESOLVABLE_PREFIXES):
        return ("", EXIT_UNRESOLVABLE)

    # Fail closed on any shell expansion embedded anywhere in the path token.
    # /tmp/$WT or /tmp/$(pwd) would be treated as a literal by the startswith
    # check but the actual shell would expand them — potentially to a different
    # directory with a different tracking branch.
    if not raw.startswith("$") and re.search(r"[$\x60]", raw):
        return ("", EXIT_UNRESOLVABLE)

    if not raw.startswith("$"):
        return (raw, EXIT_OK)

    # $VAR reference — strip optional ${...} braces, reject complex expansions.
    varname = raw[1:]
    if varname.startswith("{") and varname.endswith("}"):
        varname = varname[1:-1]
    if re.search(r"[^a-zA-Z0-9_]", varname):
        # Complex expansion like ${WT:-default} — unresolvable.
        return ("", EXIT_UNRESOLVABLE)

    # Find the last assignment before git -C (shell semantics).
    pattern = _VAR_ASSIGN_RE_TMPL.format(varname=re.escape(varname))
    git_pos = c_match.start()
    matches_before = [m for m in re.finditer(pattern, cmd) if m.end() <= git_pos]
    if not matches_before:
        # Variable referenced but no assignment found — unbound, fail closed.
        return ("", EXIT_UNRESOLVABLE)

    resolved = _first_group(matches_before[-1])
    if resolved.startswith(_UNRESOLVABLE_PREFIXES):
        return ("", EXIT_UNRESOLVABLE)
    # Fail closed if the resolved value itself contains any shell expansion
    # (e.g. WT="$ROOT/wt" resolves to "$ROOT/wt" which still has a $ in it).
    if re.search(r"[$\x60]", resolved):
        return ("", EXIT_UNRESOLVABLE)
    return (resolved, EXIT_OK)


if __name__ == "__main__":
    cmd_arg = sys.argv[1] if len(sys.argv) > 1 else ""
    path, exit_code = resolve_git_dir(cmd_arg)
    print(path)
    sys.exit(exit_code)

---
name: unfreeze
version: 0.1.0
description: Clear the freeze boundary set by /freeze, allowing edits to all directories again.
triggers:
  - unfreeze edits
  - unlock all directories
  - remove edit restrictions
allowed-tools:
  - Bash
  - Read
---
<!--
  Adapted from garrytan/gstack unfreeze skill (MIT, Copyright (c) 2026 Garry Tan);
  see LICENSE.gstack in this directory. Changes: boundary state lives under
  ~/.agents instead of ~/.gstack, and gstack analytics writes are removed.
-->

## When to invoke this skill

Use when you want to widen edit scope without ending the session. Use when asked
to "unfreeze", "unlock edits", "remove freeze", or "allow all edits".

# /unfreeze -- Clear Freeze Boundary

Remove the edit restriction set by `/freeze`, allowing edits everywhere again.

```bash
STATE_DIR="${CLAUDE_PLUGIN_DATA:-$HOME/.agents}"
if [ -f "$STATE_DIR/freeze-dir.txt" ]; then
  PREV=$(cat "$STATE_DIR/freeze-dir.txt")
  rm -f "$STATE_DIR/freeze-dir.txt"
  echo "Freeze boundary cleared (was: $PREV). Edits are now allowed everywhere."
else
  echo "No freeze boundary was set."
fi
```

Tell the user the result. The `/freeze` hooks stay registered for the session;
they simply allow everything while no boundary file exists. To re-freeze, run
`/freeze` again.

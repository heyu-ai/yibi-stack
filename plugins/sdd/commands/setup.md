---
description: Diagnose spectra CLI installation status and show setup instructions
model: sonnet
---
<!-- markdownlint-disable-file MD041 -->

Run the following to check the spectra CLI status:

```bash
spectra --version
echo "exit code: $?"
```

```bash
(set -o pipefail; spectra schemas 2>&1 | head -10) || echo "spectra schemas failed or unavailable"
```

Report the results:

- If `spectra --version` exits 0 with output: show the version and confirm the CLI is ready. The full spectra workflow (propose, analyze, validate, archive) is available.
- If `spectra --version` exits 0 but produces no output: report as anomalous — binary may be a broken wrapper.
- If exit code is 127: binary is absent. Print the following setup guidance:
- If exit code is non-zero but not 127: binary exists but is broken (corrupted install, Gatekeeper block, wrong arch).
  Show the actual output and do NOT recommend a fresh install — advise the user to investigate the existing binary first.

  ```text
  spectra CLI is not installed. To enable the full Spectra workflow:

  macOS (recommended):
    brew install --cask spectra-app

  After installing and launching Spectra.app once, the binary is typically symlinked at
  ~/.local/bin/spectra. Run `which spectra` to confirm the actual path on your machine.

  Upstream: https://github.com/kaochenlong/spectra-app

  Note: Spectra is macOS-only. On Linux/Windows, the spectra-amplifier methodology
  and all openspec templates in this plugin are still fully usable in degraded mode.
  ```

---
description: Diagnose spectra CLI installation status and show setup instructions
model: sonnet
---
<!-- markdownlint-disable-file MD041 -->

Run the following to check the spectra CLI status:

```bash
if ! command -v spectra >/dev/null 2>&1; then echo '[FAIL] spectra: not installed'; elif spectra --version; then echo '[OK] spectra: --version exited 0'; else echo '[FAIL] spectra: installed but --version failed'; fi
```

```bash
(set -o pipefail; spectra schemas 2>&1 | head -10) || echo "spectra schemas failed or unavailable"
```

Report the results:

- `[OK] spectra: --version exited 0` with a version line above it: show the version and confirm the CLI is ready. The full spectra workflow (propose, analyze, validate, archive) is available.
- `[OK] spectra: --version exited 0` but no version line above it: report as anomalous — binary may be a broken wrapper.
- `[FAIL] spectra: installed but --version failed`: binary exists but is broken (corrupted install, Gatekeeper block, wrong arch).
  Show the actual output and do NOT recommend a fresh install — advise the user to investigate the existing binary first.
- `[FAIL] spectra: not installed`: binary is absent. Print the following setup guidance:

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

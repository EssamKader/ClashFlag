label: ready-for-agent

# T-6: pyRevit pushbutton packaging

Implements US-6. Wrap the runner + picker + panel into a proper
`ClashFlag.pushbutton` bundle (icon.png, script.py, bundle.yaml, config) inside a
pyRevit extension, so it installs/loads the same way as the rest of the existing
pyRevit toolkit — no separate compiled add-in or manifest registration.

**Depends on:** T-1, T-2 (1001, 1002) — needs a working runner + picker to package;
T-3/T-4/T-5 can land as incremental updates to the same bundle after this ships.
**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — US-6.

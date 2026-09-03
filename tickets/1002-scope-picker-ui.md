label: ready-for-agent

# T-2: Category/link scope picker

Implements US-1. A pre-run WPF form listing available categories (checkboxes) and
currently loaded `RevitLinkInstance`s (checkboxes), returning the user's selection
to build the `ElementFilter` and link list that T-1's runner consumes instead of
its hardcoded defaults.

**Depends on:** T-1 (1001-interference-check-runner.md) — needs the runner's filter
inputs defined before the picker can feed it.
**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — US-1.

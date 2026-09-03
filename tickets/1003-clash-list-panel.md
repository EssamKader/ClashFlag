label: ready-for-agent

# T-3: Navigable clash list panel

Implements US-3. Modeless WPF window listing every `InterferenceResult` from T-1
(element names/categories/ids of the clashing pair), with next/previous controls
(and direct list selection) to move a "current clash" pointer through the results.

**Depends on:** T-1 (1001-interference-check-runner.md) — needs real results to list.
**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — US-3.

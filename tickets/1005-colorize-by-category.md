label: ready-for-agent

# T-5: Colorize clashes by category toggle

Implements US-5. A toggle in T-3's panel that, when on, applies
`OverrideGraphicSettings` to every clashing element in the active view, colored by
its clash's category/discipline pair (consistent color per pair across the whole
result set), and clears all overrides when toggled off or the panel closes.

**Depends on:** T-3 (1003-clash-list-panel.md) — needs the full result set and panel
to host the toggle.
**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — US-5.

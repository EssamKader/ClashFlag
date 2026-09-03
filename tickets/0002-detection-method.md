label: wayfinder:decision
type: Grill

# Detection method & tolerance

How should the tool actually detect a clash between elements (own model and/or linked models)?

Open questions:
- Bounding-box overlap (fast, coarse, many false positives) vs. solid/geometry intersection (slower, precise) vs. a first-pass bbox filter then solid check on candidates only
- Clearance tolerance (hard clash = 0, or flag near-misses within e.g. 25mm/1in)
- Hard clash vs. soft/clearance clash as separate categories

## User's answer (original, 2026-09-03)
Use the native `Document.PerformInterferenceCheck` approach (no custom tolerance
post-filter for v1) — matches the Research finding in 0004 directly, no extra
near-miss logic needed.

## Reopened at Phase 7 review (ticket 1001)

The native-API approach for cross-document (host-vs-link) checks was found to rest
on an unverified/likely-incorrect claim about automatic transform handling — see
the erratum in [0004-linked-model-api-research.md](0004-linked-model-api-research.md).

## User's decision on reopen (2026-09-03)
Default to manual transform: apply the `RevitLinkInstance` transform to linked
geometry explicitly (bbox pre-filter, then solid intersection on host-vs-link
pairs) rather than trusting the native check to do it. Native
`PerformInterferenceCheck` stays fine for host-vs-host category checks — only the
cross-document path changes. No tolerance/near-miss logic still — out of scope for
v1 regardless of method.

## Status: resolved (superseding the original answer)

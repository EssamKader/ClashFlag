label: done

# Wayfinder: Isolate both host and linked-model elements

Reopens US-7 / CONTEXT.md's "Isolate" entry, which currently states host-side-only is
possible because Revit's API has no way to isolate an element living inside a linked
document from the host view — and the spec's "Explicitly out of scope" list already
declined the one known workaround (editing the linked file) as not worth it for a
highlight Select already provides.

**Why reopened:** live user workflow — one host floor slab clashing against many pipes
from a linked MEP model. Select + camera fly-to already highlight/reframe on both
elements, but with "many pipes" still fully visible and unhidden in the view, picking
out which specific pipe is the current clash target is hard enough in practice that the
user now needs it. (Illustrated by the user's own Navisworks Clash Detective usage —
Navisworks isolates both clash items trivially because it flattens host+link into one
federated model; Revit's host/link separation is the real reason ClashFlag can't do the
same thing the same way, not a missing feature of ClashFlag itself.)

**Decision tickets under this map:**
- [1015 (Research)](1015-research-cross-doc-link-element-hide.md) — is there a
  non-invasive way (no writes to the linked file) to hide/isolate a *specific* element
  inside a link, scoped to the host view only?
- [1016 (Grill)](1016-grill-isolate-both-ux-fallback.md) — UX/fallback decision, informed
  by 1015's finding.

Resolved when both are resolved or explicitly deferred by the user.

## Resolution

Both resolved. Summary: link-side isolation will be built on `View.HideElements`/
`UnhideElements` with `LinkElementId` (host-view-scoped, no writes to the linked file) —
pending live confirmation once Revit is reachable. On Isolate, exactly two elements stay
visible total (the current clash's host element and link element), matching Navisworks'
own isolate behavior exactly; host-side Isolate is unchanged; no upfront performance
optimization; if live verification disproves the plan, stop and ask fresh rather than
falling back to editing the linked file. See 1015 and 1016 for full detail.

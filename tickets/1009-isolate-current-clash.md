label: ready-for-agent

# T-9: Isolate toggle for the current clash

Implements US-7 (2026-09-04 amendment). A new opt-in "Isolate" checkbox in the clash list
panel that, while checked, hides everything in the active view except the current clash's
host-side element and always also runs Select (host + link, via the existing
`select_clash_pair`/`Reference`/`CreateLinkReference`/`SetReferences` mechanism from T-4)
so the un-isolatable link-side element stays findable. Moving to a different clash while
Isolate is on replaces the isolation. Turning Isolate off, or closing the panel while it's
on, immediately restores the full view.

**Depends on:**
- T-3 (1003-clash-list-panel.md) — hosts the new checkbox, `current_index` as the single
  source of truth for "the current clash."
- T-4 (1004-camera-fly-to-clash.md) — reuses `select_clash_pair` and the
  `_RevitApiBridge`/`_revit_api_bridge` ExternalEvent bridge (a modeless window's later
  event handlers have no valid Revit API context; every Revit API call from this feature
  MUST go through the bridge, exactly like camera fly-to and colorize already do — this
  is a hard project rule from prior tickets' review history, not optional).
- T-5 (1005-colorize-by-category.md) — mirrors its exact "apply on check / clear on
  uncheck / clear on window Closed" lifecycle pattern (`colorize_active`,
  `_clear_colorize_if_active` wired to both the Unchecked handler and the `Closed` event).
  Reuse that pattern's shape for `isolate_active`/`_clear_isolate_if_active`; do not
  invent a different lifecycle.

**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — US-7.
**Context:** [CONTEXT.md](../CONTEXT.md) — Isolate, Select.

## Scope

- New `IsolateCheckBox` in the clash list XAML (same declarative `Checked=`/`Unchecked=`
  event-wiring pattern already used for `ColorizeCheckBox` and the nav buttons).
- `isolate_active` state on `ClashListWindow`, plus the view id that was isolated (mirror
  `colorize_view_id`'s reasoning: capture at apply time, don't re-read "whatever's active
  now" at clear time).
- Apply: `View.IsolateElementsTemporary` (or the correct current-API equivalent — verify
  the exact method/overload against the API docs before writing code, don't assume from
  memory) with only the current clash's host element id, routed through
  `_revit_api_bridge.raise_action(...)`. Then call the existing select-both-elements logic
  so host + link are highlighted at the same time.
- Navigating to a new clash (next/previous) while `isolate_active` is True must re-apply
  isolate + select for the newly-current clash (replace, not accumulate) — extend the
  existing `on_selection_changed`/`selection_changed_callback` hook from T-3/T-4 rather
  than inventing a second navigation hook.
- Clear: exit temporary isolate mode (verify the correct API call — e.g.
  `View.DisableTemporaryViewMode` with the matching `TemporaryViewMode` enum value; do not
  assume the name without checking) restoring full visibility, wired to both the
  `Unchecked` handler and the panel's existing `Closed` event handler (extend, don't
  duplicate — same instruction T-5 followed).
- Independent of Colorize: do not read or write `colorize_active`/colorize overrides from
  any isolate code path, and vice versa.
- Every Revit-API-touching call in this ticket goes through `_revit_api_bridge` — no
  direct `Transaction`/view-mode calls from a checkbox or selection-changed handler body.

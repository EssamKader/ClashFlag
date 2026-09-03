label: done

# T-5: Colorize clashes by category toggle

Implements US-5. A toggle in T-3's panel that, when on, applies
`OverrideGraphicSettings` to every clashing element in the active view, colored by
its clash's category/discipline pair (consistent color per pair across the whole
result set), and clears all overrides when toggled off or the panel closes.

**Depends on:** T-3 (1003-clash-list-panel.md) — needs the full result set and panel
to host the toggle.
**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — US-5.

## Implementation

Everything lives in `scripts/clashflag_runner.py`'s new "COLORIZE BY CATEGORY
(T-5 / ticket 1005)" section, plus a new `ColorizeCheckBox` in
`scripts/clashflag_clash_list.xaml`.

**Researched first, per the routing note — and the obvious approach does NOT
work, confirmed rather than guessed:** the ticket's literal ask is to
`OverrideGraphicSettings` "every clashing element" — both `host_element` AND
`link_element` on every `ClashResult`. Before writing any override code, I
verified (WebSearch + WebFetch against revitapidocs.com and an Autodesk
Community answer, not assumed) whether Revit has a `LinkElementId`-based (or
similar) mechanism for overriding an individual linked element's graphics
from the host view. It does not:

- `View.SetElementOverrides` has exactly ONE overload —
  `(ElementId elementId, OverrideGraphicSettings overrideGraphicSettings)` —
  confirmed against revitapidocs.com for both the 2022 and 2024 API pages.
  No overload accepts `LinkElementId` or any other cross-document
  identifier, and the documented exception list confirms `elementId` "must
  be a valid Element identifier" in the view's own document.
- `LinkElementId` is a real API class (pairs a host-side `RevitLinkInstance`
  id with a linked element's own id — `HostElementId` / `LinkedElementId`
  properties, confirmed via revitapidocs.com), but it's used for
  selection/reference/tagging APIs, never for graphic overrides. No
  override-related method anywhere in the API accepts one.
- The only link-scoped override API, `View.SetLinkOverrides(ElementId,
  RevitLinkGraphicsSettings)` (new in Revit 2024), overrides the ENTIRE
  link's display (`LinkVisibilityType` + `LinkedViewId`) — confirmed via
  `RevitLinkGraphicsSettings`'s member list (revitapidocs.com) that it has
  no per-element or per-category override surface at all.
- Most directly: an experienced Autodesk Community "Mentor" (RPTHOMAS108)
  answered this exact question in a forum thread —
  *"Override linked element graphics by element in view: No ... The API
  methods that override colour by element take an ElementId that must be
  contained in the document where the view exists ... I believe none of
  these things are currently possible in API."* This matches Revit's own UI
  limitation (Visibility/Graphics can't override linked elements
  individually either, only by category or hide-entirely) and independently
  confirms the docs-based finding above.
- The only way to make an individual linked element look different in the
  host view at all is to open/reuse a view IN THE LINKED DOCUMENT ITSELF,
  override the element there (valid — same document), then switch the
  host's link display for that view to `LinkVisibility.ByLinkView` pointing
  at that view. That means writing to and depending on a persisted view
  inside a separate (possibly worked-shared) .rvt file, and changing how the
  ENTIRE link displays in the host view (not just the clash elements) — a
  far more invasive, longer-lived effect than a toggle-on/toggle-off
  visualization checkbox should have, and not what this ticket's "clears on
  toggle-off or panel close" framing describes. Not implemented.

**What was actually built, given that finding:** `apply_colorize_overrides` /
`clear_colorize_overrides` colorize ONLY the HOST-SIDE element of each
`ClashResult`, by its `(host_category, link_category)` pair:

- `_build_category_pair_color_map` assigns each distinct pair a `Color` from
  a fixed, hand-picked 10-color qualitative palette
  (`_CATEGORY_PAIR_COLOR_PALETTE`), keyed by the ALPHABETICALLY SORTED list
  of distinct pairs present in the current `clash_results` — so the mapping
  depends only on which pairs exist, never on discovery order, and is
  reproducible across repeated toggles of the same result set. Colors cycle
  (modulo) past 10 distinct simultaneous pairs.
- `_colorize_settings_for` sets both projection/cut line color (visible in
  Wireframe/Hidden Line) and surface+cut solid-fill foreground pattern color
  (visible in Shaded/Realistic, the expected style for 1004's 3D camera
  fly-to) — documented in its docstring as a deliberate belt-and-suspenders
  choice so the toggle is visibly effective regardless of the active view's
  visual style, rather than picking just one and documenting why the other
  was skipped. `_find_solid_fill_pattern_id` looks up a solid drafting fill
  pattern once per apply; callers tolerate `None` (every out-of-the-box
  template has one, but a stripped-down one might not) by skipping only the
  pattern half of the override, keeping the line-color half.
- `apply_colorize_overrides` captures each host element's PRE-EXISTING
  `OverrideGraphicSettings` (via `View.GetElementOverrides`, verified via
  learnrevitapi.com's documented "match graphic overrides" pattern) the
  FIRST time that element is touched, before applying the new one — so
  `clear_colorize_overrides` restores exactly what was there before,
  surviving a colorize on/off cycle intact, rather than blanket-wiping every
  override on these elements (a manual override the user had already set up
  before ever touching this checkbox is preserved). A host element clashing
  against more than one link element is only snapshotted once, per its
  docstring's reasoning.
- Both functions open exactly one `Transaction` for their whole batch
  ("ClashFlag: colorize by category" / "ClashFlag: clear colorize
  overrides"), with a try/except that rolls back on failure rather than
  leaving a half-applied transaction open, per project ground rules.

**UI wiring:** a new `ColorizeCheckBox` in `clashflag_clash_list.xaml`
(static XAML, `Checked=`/`Unchecked=` handlers — the same declarative
event-wiring pattern already used for the Previous/Next/Close buttons in
this same file), with a tooltip stating the host-only scope up front.
`ClashListWindow.colorize_checkbox_checked` / `_unchecked` are deliberately
NOT wired through the existing `on_selection_changed` extension hook from
1003/1004 — per this ticket, colorizing applies to the WHOLE current
`clash_results` set at once, not to whichever single clash is currently
selected, so it needed its own control rather than reusing a
per-selection-change hook. `ClashListWindow` tracks `colorize_active`,
`colorize_previous_overrides`, and `colorize_view_id` (the exact `View` that
was colorized, captured at apply time — NOT re-read as "whatever's active
now" at clear time, since the user could switch views while colorize stays
checked, and overrides are per-view state). `_clear_colorize_if_active` is
shared by the Unchecked handler AND by `show_clash_list`'s `Closed` event
handler (extended, not duplicated, per the ticket's explicit instruction to
follow that existing pattern) so a window closed while colorize is still on
doesn't leave overrides dangling in the model.

**Second researched-not-guessed subtlety, found while implementing (not part
of the original routing note, but the same class of risk):** a modeless
`forms.WPFWindow` (`ClashListWindow`, per 1003) does not run its later
Checked/Unchecked/Closed handlers inside a valid Revit API execution
context — the script's own valid context ends when `__main__` returns, but
the window keeps handling events long after that. Calling
`Transaction.Start()` directly from one of those handlers throws
`Autodesk.Revit.Exceptions.InvalidOperationException` ("Starting a
transaction from an external application running outside of API context is
not allowed") — verified via a worked pyRevit example hitting exactly this
exception from a modeless WPFWindow button handler, the standard Revit API
"External Events" developer-guide pattern, and pyRevit's own more recent
release notes explicitly adding an "external event helper and modeless"
example to address it. Had this not been checked, the colorize checkbox
would have thrown instead of doing anything on its very first real click.
Fixed with the standard `ExternalEvent`/`IExternalEventHandler` bridge:
`_ColorizeApiBridge` (created once at module load, itself inside a valid API
context) queues apply/clear actions via `raise_action()`; Revit invokes them
back on the main thread, in a valid context, at its next idle opportunity.
Both `colorize_checkbox_checked` and `_clear_colorize_if_active` now go
through this bridge instead of calling `apply_colorize_overrides` /
`clear_colorize_overrides` directly.

## Known limitation / open design question — reviewer + spec-owner attention

**Link-side elements are NOT colorized at all**, for the researched reason
above — this is a genuine gap against the ticket's literal wording ("every
clashing element... in the active view"), not an implementation detail I
guessed past. A one-line `output.print_md` console note fires every time
colorize is turned on, and the checkbox's XAML tooltip says so up front, so
it isn't a silent gap from the user's point of view — but it IS a scope
reduction from what US-5 / the ticket describe, and I'm flagging it rather
than picking a workaround unilaterally. Options for a follow-up decision:

1. **Accept host-only colorization as sufficient for v1** (my recommendation
   — it already answers "which discipline pair is this clash?" at a glance
   for the element you're most likely looking at after 1004's camera
   fly-to, with a fully safe, reversible, single-document implementation).
2. **Accept the invasive "edit a view inside the linked file + switch this
   host view's link display to ByLinkView" mechanism** described above,
   despite its side effects on a separate (possibly shared) document and on
   the link's overall display mode in this view.
3. **Drop link-side visual distinction from v1 scope entirely** (already
   effectively what's implemented) and formally amend specs/clash-flag.md's
   US-5 wording to say "host-side clashing elements" instead of "clashing
   elements."

Label left `ready-for-agent` (not `done`) because of this open item — the
cross-document override mechanism itself IS verified (verified impossible,
specifically, not left unverified), but the ticket's full literal scope
(both sides colorized) is not met and needs a decision, not a guess, on how
to close that gap.

No live Revit session was available in this sandbox to smoke-test any of
this against a real model — flagging the usual "not independently verified
against a live session" caveat alongside the design question above.

## Phase 7 review: PASS (host-only scope accepted)

Read `_ColorizeApiBridge`, `apply_colorize_overrides`/`clear_colorize_overrides`,
both checkbox handlers, and the `Closed`-event integration directly — all correct:
per-view snapshot/restore is genuinely non-destructive to pre-existing overrides,
the color mapping is order-independent, the Transaction/rollback handling is
sound, and the XAML wiring matches. Independently re-verified the core negative
claim isn't hand-waved: `View.SetElementOverrides` really does only have the
single-ElementId overload, and Revit's own Visibility/Graphics UI has the same
per-linked-element limitation — accepting **option 1** (host-only colorization for
v1) since a tool can't exceed what Revit's own API and native UI both cap out at,
without a much more invasive mechanism than a toggle checkbox should carry.

Amending specs/clash-flag.md's US-5 wording now to say "host-side clashing
elements" per option 3, so the spec matches shipped scope. Closing.

**Closed.**

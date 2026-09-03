label: ready-for-agent

# T-4: Camera auto-navigation to selected clash

Implements US-4. When the "current clash" pointer in T-3's panel changes (next/prev
or direct selection), compute the combined bounding box of the two clashing
elements (transforming the linked element's bbox into host coordinates) and reframe
the active 3D view's camera on it — equivalent to what Revit's built-in Interference
Check "Show" button does.

**Depends on:** T-3 (1003-clash-list-panel.md) — needs the selection/pointer concept
to hook the camera move onto.
**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — US-4.

## Implementation

Everything lives in `scripts/clashflag_runner.py` (same file T-1/T-2/T-3 already
built up in place).

**`ClashResult` gained a 4th field, `link_instance_id`** (the `ElementId` of the
`RevitLinkInstance` the pair was found against), set from `link_instance.Id` right
where `run_interference_check` already has `link_instance` in scope when it builds
each `ClashResult`. Chosen over re-deriving "which `RevitLinkInstance` produced this
element" later by re-searching loaded links and matching on `link_name` (the only
other identifying field `ClashResult` carried before this ticket) — display names
aren't guaranteed unique and re-searching would be pure waste when the exact
instance was already known at creation time. This mirrors ticket 1002's existing
`link_element_id` → `resolve_link_instance_by_id` pattern: `ClashResult` stores the
id, not the live object reference, so the camera code re-resolves the actual
`RevitLinkInstance` (and reads a fresh `GetTotalTransform()`) at the moment it's
needed rather than trusting a reference to stay valid/meaningful for as long as the
modeless clash list window stays open.

**Combined bounding box (`_combined_host_space_bounding_box`):** reads
`host_element.get_BoundingBox(active_view)` (already host-space, per ticket 1001's
established "`Element` boxes are world-aligned, unlike `Solid.GetBoundingBox()`"
knowledge — no further transform needed) and `link_element.get_BoundingBox(None)`
(LINK-LOCAL space — `None` because there's no view of the link's own document to
pass; the active view belongs to the host document, and passing a host-document
view for an element of a different document isn't a valid combination). The link
box's 8 corners are run through `link_instance.GetTotalTransform()` — the exact
"transform all 8 corners, not just 2" technique `_outline_for_solid` already uses
for solids, extracted into a shared `_transform_all_corners(local_min, local_max,
transform)` helper and reused here rather than reimplemented, so a rotated/mirrored
link placement can't under-cover the true extents the same way it couldn't for the
detection pipeline. `resolve_link_instance_by_id`/`resolve_link_document` (ticket
1002) re-resolve the link from `link_instance_id` first, so an unloaded/removed
link surfaces as a specific `ClashFlagError` rather than a bare bounding-box
failure. The two host-space boxes are then unioned component-wise (min of mins, max
of maxes).

**Camera API choice — researched via WebSearch, not guessed:**
`UIView.ZoomAndCenterRectangle(viewCorner1, viewCorner2)`, called on the `UIView`
matching the active view's `Id` (found via `UIDocument.GetOpenUIViews()`), with the
two corners of the (padded) combined box, in model coordinates.
- Verified against revitapidocs.com's method description: "Zoom and center the view
  to a specified rectangle", both `viewCorner1`/`viewCorner2` documented as being in
  model coordinates — [ZoomAndCenterRectangle Method](https://www.revitapidocs.com/2019/d032146c-1fe9-82b8-74f1-0b62fb4fd097.htm).
- Verified against a real, working pyRevit-forum implementation of exactly this
  "zoom the active view to an element's bounding box" pattern
  (`get_BoundingBox(view)` → `ZoomAndCenterRectangle(min, max)`, no extra transform)
  — [Zoom \ Go to element - pyRevit Forums](https://discourse.pyrevitlabs.io/t/zoom-go-to-element/3544).
- The `GetOpenUIViews()` + match-on-`ViewId` pattern for finding the active view's
  `UIView` is the standard, documented approach — [Autodesk Developer Blog: Save and Restore 3D View Camera Settings](https://blog.autodesk.io/save-and-restore-3d-view-camera-settings/),
  [The Building Coder](https://jeremytammik.github.io/tbc/a/1870_save_restore_camera.html).
- Two alternatives were considered and rejected: `View3D.SetSectionBox` (rejected —
  it *crops* the view, a persisted view-state change needing a `Transaction`, a
  materially more invasive and longer-lived effect than the native Interference
  Check "Show" button produces — [SetSectionBox Method](https://www.revitapidocs.com/2025/e21471cd-63a4-c452-8c29-fad41362a59b.htm));
  manually computing a `ViewOrientation3D` (rejected — strictly more failure-prone,
  has to derive a correct eye distance from box size and FOV/aspect ratio by hand,
  for no behavioral gain over an API method built for exactly this purpose).

**UNVERIFIED / flagged for reviewer:** search also surfaced a forum report
([Strange behavior of UIView.ZoomAndCenterRectangle](https://forums.autodesk.com/t5/revit-api-forum/strange-behavior-of-uiview-zoomandcenterrectangle/td-p/8888088))
of aspect-ratio/orientation-related quirks with `ZoomAndCenterRectangle` in some 3D
scenarios. Neither that thread nor the working pyRevit-forum example pins down
**perspective (camera) 3D views specifically vs. orthographic 3D views** — this has
not been exercised against a live Revit session in this sandbox (none is available
here). If it visibly misbehaves on a perspective 3D view during first real testing,
documented fallbacks are noted directly in `reframe_active_view_on_clash`'s
docstring (require an orthographic 3D view, or switch to the `ViewOrientation3D`
approach).

**Active-view-not-3D handling:** if `host_doc.ActiveView` isn't a `View3D` (also
covers a `None`/missing active view), camera reframing is skipped entirely — no
view switch, no view creation. Reported via a one-line `output.print_md` console
note, deliberately NOT a modal `forms.alert`, since this runs on every clash-list
navigation step and a popup per click would be far more disruptive than a console
line. Matches the native Interference Check "Show" button's own behavior, which
also only ever reframes whatever 3D view is already active rather than managing
view selection for the user.

**No `Transaction`:** `ZoomAndCenterRectangle` only changes the transient on-screen
pan/zoom state of an already-open `UIView` window — the same kind of change a user
causes by scrolling/zooming with the mouse. It creates/deletes/modifies no element,
parameter, or persisted view property in either document, so no `Transaction` is
opened, consistent with the rest of the file's read-only design. (This is also
exactly why `SetSectionBox` was rejected above — that alternative WOULD need one.)

**Wiring (does not touch `ClashListWindow`'s navigation internals):**
`ClashListWindow.__init__` and `show_clash_list` both gained one new optional
trailing parameter, `selection_changed_callback`, forwarded straight through to the
constructor rather than set on the returned window instance afterward. This matters
for the *very first* clash: `ClashListWindow.__init__` auto-selects index 0 during
construction (before returning), which already fires the extension hook — a
callback attached only after `show_clash_list()` returns would silently miss that
initial auto-selection and only ever fire on subsequent Next/Previous/click
navigation, which would under-deliver on US-4 for the common single-clash-run case.
`__main__` defines a small closure (`_on_clash_selection_changed`) that calls the
new `reframe_active_view_on_clash(clash_result, doc, uidoc)` and passes it into
`show_clash_list(clash_results, selection_changed_callback=...)`. No existing
navigation code path (`_on_list_selection_changed`, `_set_current_index`,
Next/Previous handlers) was modified.

**Small UX addition beyond the literal ask:** `_pad_bounding_box` expands the
combined box outward by a fixed fraction (`CAMERA_REFRAME_PADDING_FRACTION = 0.15`)
of each axis's own extent before zooming, so the two clashing elements aren't left
flush against the view edge — matching how Revit's own "zoom to fit"-style behavior
(e.g. `UIDocument.ShowElements`) always leaves a margin. Falls back to a fixed
1-foot pad on a zero/near-zero-extent axis so a degenerate (flat) clash box never
produces a zero-thickness zoom rectangle.

File verified with `ast.parse` after edits — no syntax errors introduced. No live
Revit/pyRevit session available in this sandbox, so none of the above has been
exercised against a real model — see the reviewer-attention list below.

**Reviewer attention:**
- The perspective-vs-orthographic 3D view distinction for
  `ZoomAndCenterRectangle`, called out above, is the single biggest open question —
  it could not be pinned down definitively from available sources.
- `Element.get_BoundingBox(view)` for `host_element` and `Element.get_BoundingBox
  (None)` for `link_element` — both rely on the same "`Element` boxes are already
  expressed directly in their own document's coordinate system, no separate
  local-frame `Transform` step" claim ticket 1001 established for the detection
  pipeline (reviewed there without objection) — re-applied here for a different
  purpose (camera reframing) rather than re-verified from scratch, per this
  ticket's explicit instruction to treat it as established knowledge.
- `_transform_all_corners`'s extraction from `_outline_for_solid` is intended to be
  a pure refactor (identical corner-transform math, just shared) — worth a close
  read to confirm nothing changed for the existing detection pipeline's behavior.
- Padding fraction (0.15) and 1-foot degenerate-axis fallback are arbitrary,
  reasonable-looking defaults, not derived from any spec or research — easy to
  retune if real-world testing shows the camera ending up too tight/too loose.

Label kept as `ready-for-agent` rather than `done`: the core design (bounding-box
computation, transform reuse, hook wiring, no-Transaction reasoning) is complete and
internally consistent, but the central API choice — `ZoomAndCenterRectangle`'s
actual on-screen behavior for a 3D view, and specifically whether it behaves the
same for perspective vs. orthographic 3D views — could not be confirmed against a
live Revit session, and is exactly the kind of "looks right, could still be subtly
wrong" risk this project's review process (see 1001/1002 Phase 7 history) exists to
catch. This should move to `done` only after a real pyRevit/Revit smoke test
confirms the camera actually reframes correctly on both clash elements in an actual
3D view, or after review is satisfied the research above is sufficient without one.

## Phase 7 review round 1: PASS (superseded — see round 2 reopen below)

Read `_transform_all_corners`, `_combined_host_space_bounding_box`,
`reframe_active_view_on_clash`, and the `__main__`/`ClashListWindow` wiring
directly. Logic is sound: `_transform_all_corners` is a faithful extraction (not a
rewrite) of the existing, already-reviewed corner-transform technique;
`link_instance_id` threading through `ClashResult` avoids a fragile name-based
re-lookup; the callback-in-constructor timing fix for the first auto-selected
clash is correct and well-reasoned; no-Transaction reasoning is sound for a
transient zoom.

Independently re-verified the central API claim via a fresh search (not just
trusting the ticket's own citations): `UIView.ZoomAndCenterRectangle(XYZ, XYZ)`
takes model coordinates, and `UIDocument.GetOpenUIViews()` + matching on `ViewId`
is the standard, documented way to find the active view's `UIView` — confirmed via
[Autodesk's own UIView developer guide](https://help.autodesk.com/cloudhelp/2018/ENU/Revit-API/Revit_API_Developers_Guide/Basic_Interaction_with_Revit_Elements/Views/UIView.html).

The perspective-vs-orthographic 3D view uncertainty the implementer flagged is a
real-world calibration question ticket 1007 (live-model performance/correctness
validation) is positioned to catch, not a logic defect — not a blocker for closing
this ticket. Closing.

**Closed.** *(superseded — reopened below)*

## Reopened at Phase 7 review, round 2 (during ticket 1005's review)

**Confirmed regression, independently re-verified via WebSearch:** a modeless
`forms.WPFWindow` (`ClashListWindow`, per 1003) only runs inside a valid Revit API
execution context for as long as the pyRevit script's own `__main__` is still on
the call stack. `reframe_active_view_on_clash` is invoked directly from
`ClashListWindow.on_selection_changed` → `selection_changed_callback` — a WPF
event handler that keeps firing long after `__main__` has returned (every
Next/Previous click, every direct list-row click). Only the very first
auto-selected clash (fired synchronously during `ClashListWindow.__init__`,
itself still inside `__main__`) happens to be in a valid context; every
subsequent navigation would throw
`Autodesk.Revit.Exceptions.InvalidOperationException` the moment it touches
`host_doc.ActiveView` / `resolve_link_instance_by_id` /
`host_uidoc.GetOpenUIViews()` / `target_uiview.ZoomAndCenterRectangle`.

This exact constraint is what ticket 1005 (colorize) independently researched and
built `_ColorizeApiBridge` (an `ExternalEvent`/`IExternalEventHandler` bridge) to
work around — confirmed via multiple independent sources (Autodesk's own Revit
API developer guide on External Events, Jeremy Tammik's Building Coder, a
pyRevit-specific worked example hitting this exact exception from a modeless
WPFWindow handler).

**Fix:** route `reframe_active_view_on_clash` through the same bridge mechanism
1005 already built, rather than calling it directly from the selection-changed
callback in `__main__`. Since the bridge is no longer colorize-specific once
1004 also needs it, rename `_ColorizeApiBridge`/`_colorize_api_bridge` to a
neutral name (e.g. `_RevitApiBridge`/`_revit_api_bridge`) and update every call
site (1005's `colorize_checkbox_checked`/`_clear_colorize_if_active`, plus 1004's
camera callback) to use the renamed version. Route camera reframing through the
bridge unconditionally (including the very first auto-selected clash) rather than
keeping a special-cased "first call is fine, later ones need the bridge" branch —
uniform behavior is simpler and more robust than relying on that timing
distinction staying true forever.

**Status:** reopened, needs rework.

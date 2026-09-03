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

## Fix applied (Phase 7 round 3)

Applied exactly the fix the round-2 reopen prescribed, in `scripts/clashflag_runner.py`:

1. **Renamed the bridge.** `_ColorizeApiBridge` → `_RevitApiBridge` and
   `_colorize_api_bridge` → `_revit_api_bridge`, everywhere: the class
   definition, its `__init__`/`raise_action`/`Execute`/`GetName` members, the
   module-level instance line and its explanatory comment, both call sites in
   1005's `colorize_checkbox_checked`/`_clear_colorize_if_active`, the module
   docstring's "SECOND RESEARCHED-NOT-GUESSED SUBTLETY" section, and the
   section-header comment immediately above the class (retitled from
   "COLORIZE BY CATEGORY" framing to "REVIT API BRIDGE", since the bridge
   itself is no longer colorize-specific — the colorize-only research
   discussion that used to live under that header is called out separately
   now). `Execute()`'s failure-report message was also reworded from
   "colorize action failed" to "a queued action failed", since it now reports
   failures for both colorize and camera-reframe actions. The only remaining
   occurrences of the old names are three explicit "renamed from
   `_ColorizeApiBridge`" historical notes (module docstring's "ADDED IN 1004"
   and "SECOND RESEARCHED-NOT-GUESSED SUBTLETY" sections, and the
   `_RevitApiBridge` class docstring) — deliberate, not leftover.

2. **Routed the camera-reframe call through the bridge, unconditionally.**
   `__main__`'s `_on_clash_selection_changed` closure no longer calls
   `reframe_active_view_on_clash(clash_result, doc, uidoc)` directly. It now
   defines a zero-arg `_reframe()` closure around that exact call and passes
   it to `_revit_api_bridge.raise_action(_reframe)` — the same pattern
   `colorize_checkbox_checked`'s `_apply` closure already uses. This applies
   to every selection change, including the first, synchronously-fired
   auto-selection during `ClashListWindow.__init__` (still inside
   `__main__`) — per the reopen's explicit instruction, there is no
   special-cased "first call is still valid, skip the bridge" branch; every
   call goes through the bridge the same way.

3. **Updated documentation that described the old, direct-call wiring** to
   describe the bridge-routed wiring instead, matching how 1005's colorize
   docstrings already describe their own bridge usage:
   - Module docstring: added a "PHASE 7 ROUND 3 FIX" paragraph right after
     the original "ADDED IN 1004" paragraph, explaining the regression and
     the fix; generalized the "SECOND RESEARCHED-NOT-GUESSED SUBTLETY"
     section (originally written colorize-only) to state the same modeless-
     window/invalid-context constraint applies equally to the selection-
     changed handler, not just the checkbox handlers.
   - `reframe_active_view_on_clash`'s own docstring: added a "CALLER'S
     RESPONSIBILITY - VALID API CONTEXT" paragraph stating the function
     assumes a valid context and does not establish one itself, and that
     every call site must queue through the bridge.
   - `ClashListWindow`'s class docstring: reworded the "EXTENSION HOOK"
     paragraph to explain that this hook fires outside a valid context like
     every other handler on this window, and that 1004's `__main__` callback
     queues through `_revit_api_bridge` rather than calling
     `reframe_active_view_on_clash` directly. Also dropped a stale
     "(1005, not yet implemented)" aside left over from before 1005 landed.
   - `_RevitApiBridge`'s own class docstring: updated to describe itself as
     shared infrastructure for both 1005's colorize checkbox and 1004's
     camera-reframe callback, not colorize-only.

4. **Re-verified 1005's colorize behavior is unaffected.** Re-read
   `colorize_checkbox_checked`, `colorize_checkbox_unchecked`, and
   `_clear_colorize_if_active` after the rename: both `raise_action` call
   sites correctly reference the renamed `_revit_api_bridge` instance, the
   queued `_apply`/`_clear` closures and all surrounding logic (override
   computation, `previous_overrides` bookkeeping, the synchronous
   `colorize_active`/`colorize_view_id` reset in
   `_clear_colorize_if_active`, the `forms.alert` + checkbox-uncheck failure
   path) are byte-for-byte unchanged apart from the identifier rename. No
   other behavior was touched.

5. **Verified the "errors still surface" reasoning holds.**
   `reframe_active_view_on_clash` itself never propagates an exception: it
   catches `ClashFlagError` around the bounding-box computation and a bare
   `Exception` around `ZoomAndCenterRectangle`, reporting each via
   `output.print_md` and returning `False`. Calling it from inside
   `_RevitApiBridge.Execute()` instead of directly doesn't change that. As a
   backstop, `Execute()` itself wraps every queued action (including
   `_reframe`) in its own `try/except Exception` that also reports via
   `output.print_md` — so even in a hypothetical case where
   `_combined_host_space_bounding_box` (or something else reframe calls)
   raised something other than `ClashFlagError`, `Execute()`'s outer handler
   still catches and reports it rather than letting it escape into Revit's
   message pump. Confirmed by reading `Execute()`'s implementation directly,
   not assumed.

Verified with `ast.parse` after edits — no syntax errors introduced. No live
Revit/pyRevit session available in this sandbox, so the fix (like the rest of
this ticket) has not been exercised against a real modeless-window navigation
sequence; the fix directly addresses the specific, independently-confirmed
`InvalidOperationException` mechanism described in the round-2 reopen, and the
pattern is identical to 1005's already-reviewed, already-shipped colorize
bridge usage — not a new, unproven mechanism.

**Reviewer attention:**
- The perspective-vs-orthographic `ZoomAndCenterRectangle` question from round
  1 is still open and unrelated to this fix — unchanged, still flagged for
  ticket 1007's live-model validation.
- Worth double-checking that `_reframe`'s closure over `clash_result` (a
  per-call local inside `_on_clash_selection_changed`, not a loop variable)
  captures the correct value on every call — it does, since each invocation
  of `_on_clash_selection_changed` creates a fresh `clash_result` binding and
  a fresh `_reframe` closure over it, so there is no shared-mutable-loop-
  variable hazard here.

**Label set to `done`:** the rename is confirmed complete via a full-file
grep (only three clearly-marked historical "renamed from" mentions of the old
name remain), the camera-reframe call site now matches 1005's already-
reviewed bridge pattern exactly, 1005's own colorize code was re-read
post-rename and is behaviorally unchanged, and the error-surfacing reasoning
was verified against `Execute()`'s actual implementation rather than assumed.

## Phase 7 review round 4: PASS

Independently re-verified, not just re-read the summary: grepped the whole file
myself for both old and new bridge names (only the three marked historical
mentions remain), read `_on_clash_selection_changed`'s `_reframe` closure directly
— correct per-call binding, no loop-variable hazard, routed unconditionally
through `_revit_api_bridge.raise_action`. Ran `python -m py_compile` myself
(independent of the implementer's `ast.parse`) — clean. This closes out the
deepest chain of this test run: a Wayfinder research claim (0004) → reopened a
detection-method decision (0002) → a class-name bug (1002) → a cross-ticket
execution-context regression (1004, caught while reviewing 1005) → fixed by
reusing infrastructure 1005 already built rather than duplicating it. Closing.

**Closed.** *(superseded — reopened below)*

## Reopened again — live-testing gap (selection highlight)

**Reported by the tool's actual user, from a real Revit 2024.3 session** (not
caught by any of the four prior review rounds, all of which reviewed this
ticket without a live Revit session available in the sandbox): stepping
through the clash list, the camera reframes on the clash area correctly, but
nothing on screen indicates WHICH two elements — out of potentially several
visible after the reframe — are the ones actually clashing. Revit's built-in
Interference Check "Show" button, which this ticket's own framing describes
as the equivalence target throughout ("equivalent to what Revit's built-in
Interference Check 'Show' button does"), does not just zoom the camera — it
also SELECTS/highlights the two clashing elements. That selection step was
never implemented in any of the four prior rounds.

**Why review never caught this:** every prior round (design plus four Phase 7
passes) verified the camera-zoom mechanism (`ZoomAndCenterRectangle`), the
bridge-routing fix for execution context, and the bounding-box math — all
correctly. None of that work would have surfaced this gap, because the gap
isn't a defect in any of those pieces; it's a missing piece entirely (no
selection call existed anywhere in the file before this fix), and the
sandbox has never had a live Revit session to actually look at a reframed
view and notice nothing was highlighted in it. This is exactly the kind of
gap only live usage — not code review — can catch, and it is being recorded
honestly here rather than glossed over, matching this project's pattern
throughout (see, e.g., ticket 1002's class-name bug, also only caught in
review/testing rather than by initial implementation).

**Status:** reopened, needs rework — add the missing selection/highlight
step to `reframe_active_view_on_clash` (or its immediate call chain), sharing
the same valid-API-context requirement (`_revit_api_bridge`) the camera
reframe already satisfies.

## Fix applied

Added `select_clash_pair(clash_result, host_doc, host_uidoc)` to
`scripts/clashflag_runner.py` (`ClashFlag.extension/BIM Tools.tab/Clash
Detection.panel/ClashFlag.pushbutton/script.py` in this repo layout), placed
directly above `reframe_active_view_on_clash` in the "CAMERA FLY-TO-CLASH +
SELECTION HIGHLIGHT" section (retitled from "CAMERA FLY-TO-CLASH" to reflect
the addition).

**Mechanism — researched via WebSearch against multiple independent sources,
not guessed, and not just trusted from this ticket's own prior framing:**
```python
host_reference = Reference(clash_result.host_element)
link_reference = Reference(clash_result.link_element).CreateLinkReference(link_instance)
host_uidoc.Selection.SetReferences([host_reference, link_reference])
```
- `Reference(Element)` — confirmed as a real constructor on
  `Autodesk.Revit.DB.Reference` via revitapidocs.com's Reference Constructor
  page.
- `Reference.CreateLinkReference(RevitLinkInstance)` — confirmed via
  revitapidocs.com's own method page ("Creates a new reference to an object
  found in a linked document, from a reference to that same object obtained
  by looking directly in the linked document") and independently via Jeremy
  Tammik's Building Coder ("Conversion of a Geometric Reference in a Linked
  RVT Model").
- `Selection.SetReferences(IList<Reference>)` — confirmed via
  revitapidocs.com's Selection Methods page ("Selects the references. The
  references can be an element or a subelement in the host or a linked
  document.") AND independently via a separate worked example (SharpBIM,
  "Highlight elements from a linked document") building this *exact*
  host-reference-plus-converted-link-reference pattern to highlight a linked
  element from the host UI. `Selection.SetElementIds` was confirmed
  insufficient for this: it only accepts `ElementId` values meaningful in
  the host document, and a linked element's own `ElementId` has no meaning
  outside its own document — the identical cross-document-id limitation
  ticket 1005's colorize feature already had to design around for graphic
  overrides. Selecting a linked-document reference this way was added in the
  Revit 2023 API, per one of the search results — already satisfied by this
  tool's Revit 2024.3 target.

**Transaction question — investigated, not assumed identical to
`ZoomAndCenterRectangle` just because both are "camera/selection, not
model":** confirmed via independent Revit-API discussion of
`Selection.SetElementIds`/`SetReferences` that both only ever change what's
highlighted in the Revit UI and never touch persisted model or view state —
same conclusion as `ZoomAndCenterRectangle`'s "transient on-screen state"
reasoning, but checked on its own rather than assumed by analogy, since
`UIDocument.Selection`/`Reference` is a different part of the API surface
than a `UIView` viewport method. No `Transaction` is opened around
`select_clash_pair`'s work.

**Sequencing:** `select_clash_pair` is called from inside
`reframe_active_view_on_clash` itself, unconditionally, before the
active-view/3D-view check — so it runs through the exact same
`_revit_api_bridge.raise_action(...)`-queued closure the camera reframe
already uses (no new call site, no new bridge queue entry), and selecting
the pair does not depend on a 3D view being active the way the camera
reframe does. The two steps are independent in outcome (a selection failure
does not block the reframe, and vice versa) but always execute together as
one queued action, addressing the ticket instruction to sequence them as one
logical unit.

**Error handling:** `select_clash_pair` never raises — it catches failures
around (1) re-resolving the `RevitLinkInstance` (reuses
`resolve_link_instance_by_id`, propagates as a specific `ClashFlagError`
message via `output.print_md` if the link is gone), (2) building either
`Reference` (e.g. an element deleted since the run), and (3) the
`SetReferences` call itself — each reported via `output.print_md` and
returning `False`, matching every other soft-failure path already in
`reframe_active_view_on_clash`. `_RevitApiBridge.Execute()`'s own outer
`try/except` remains a backstop, unchanged.

**Documentation updated:** the module docstring (new "LIVE-TESTING FIX"
paragraph, plus a retitled/expanded "CAMERA FLY-TO-CLASH + SELECTION
HIGHLIGHT" section-header comment), `reframe_active_view_on_clash`'s own
docstring (now describes both halves, why they're sequenced the way they
are, and that its `True`/`False` return value reflects the reframe outcome
only — `select_clash_pair` reports its own outcome independently), and this
ticket file.

**Verification performed:**
- `ast.parse` on the edited sandbox file — clean.
- Multiple independent WebSearch lookups (not a single source) confirming
  `Reference(Element)`, `Reference.CreateLinkReference(RevitLinkInstance)`,
  and `Selection.SetReferences(IList<Reference>)` all exist with the
  signatures/behavior used here, plus a real worked example (SharpBIM)
  building the same host-plus-link-reference pattern for the same purpose
  (highlighting a linked element from the host UI).
- Copied the updated `script.py` to the deployed pyRevit extension path
  (`...\AppData\Roaming\pyRevit\Extensions\ClashFlag.extension\BIM
  Tools.tab\Clash Detection.panel\ClashFlag.pushbutton\script.py`) and
  confirmed the copy is byte-identical to the sandbox source and still
  parses cleanly.

**NOT verified — no live Revit session available in this sandbox:**
- Whether `Reference(element)` / `CreateLinkReference` / `SetReferences`
  actually produce the expected visible highlight in a real Revit 2024.3
  session, on real structural framing / duct geometry, the way they did in
  the sources this was researched from.
- Whether calling `select_clash_pair` before the 3D-view check (so it runs
  even when the active view isn't 3D) behaves sensibly in practice, or
  whether `SetReferences` has some edge-case interaction with
  `ZoomAndCenterRectangle` being called immediately after it in the same
  bridge action (e.g. z-order of "select" vs. "reframe" visually, though
  nothing in the research suggests these interact).
- Multi-solid / multi-geometry element behavior for `Reference(Element)` —
  the sources found construct a `Reference` for a whole element in the
  common case, but didn't specifically address elements with unusual/absent
  geometry references (annotation-only or link-nested edge cases already
  called out elsewhere in this file for other purposes).

**Reviewer attention:**
- This is the fix for a bug reported directly from a live Revit session —
  more authoritative than anything reviewable in this sandbox alone — but
  the fix itself has NOT been run against a live Revit session. Given this
  ticket's history (three prior "done"/"PASS" rounds already reopened once
  live testing or deeper review caught real gaps), treat this fix as
  needing the same live-model smoke test before trusting it fully: open
  ClashFlag in real Revit 2024.3, step through a clash list with a 3D view
  active, and confirm both elements actually highlight/select alongside the
  camera reframe.
- `select_clash_pair` is called unconditionally, including when the active
  view is not 3D (selection doesn't need a 3D view) — this is a deliberate
  choice to keep the two halves independent rather than an oversight; worth
  double-checking this doesn't produce a confusing selection-with-no-visible-
  context in some non-3D-view scenario during real testing.

**Label kept as `ready-for-agent`, not `done`:** the API mechanism is
verified against multiple independent, credible sources (not guessed), the
transaction question was investigated rather than assumed, and the code
change is narrow, well-isolated, and syntax-clean — but per this project's
own established pattern (see the "Reopened again" section immediately
above, and tickets 1001/1002/1004's own review history), a fix for a
live-testing-reported gap should not be marked `done` until it has itself
been exercised against a live Revit session. This should move to `done`
after a real pyRevit/Revit smoke test confirms both clashing elements
actually highlight in the UI alongside the camera reframe, or after review
is satisfied the research trail above is sufficient without one.

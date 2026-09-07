label: done

# T-18: Focus the link model on the current clash via a Section Box

Implements US-7 (revised again 2026-09-07). Supersedes
[1017](1017-isolate-link-element-via-hide.md) — read that ticket's "Superseded" note
first for why. Extends the existing Isolate toggle so that, alongside the unchanged
host-side isolate, the active 3D view gets a Section Box tightly padded around the
combined bounding box of the current clash's host and link elements — cropping every
other element in both models, uniformly, at the view level.

**Depends on:**
- T-9 (1009-isolate-current-clash.md) — `_isolate_host_element`/`_exit_temporary_isolate`/
  `_apply_isolate_for_clash`/`_clear_isolate_if_active`/`isolate_view_id` remain
  completely UNCHANGED. This ticket only ADDS a section-box step alongside them, exactly
  like 1017 was instructed to (that instruction still applies).
- T-4 (1004-camera-fly-to-clash.md) — reuse `_combined_host_space_bounding_box` and
  `_pad_bounding_box` AS-IS, not reimplemented. Read that ticket's own research note on
  why `SetSectionBox` was rejected for camera fly-to (it crops persistently — undesirable
  for a navigation aid) and understand why that same property is exactly what makes it
  the RIGHT choice here (Isolate already persists until toggled off).

**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — US-7 (revised 2026-09-07).
**Context:** [CONTEXT.md](../CONTEXT.md) — Isolate.

## The mechanism

- `View3D.SetSectionBox(BoundingBoxXYZ)` sets the crop region; `View3D.IsSectionBoxActive`
  toggles whether it's applied. Both confirmed real API via WebSearch this round
  (revitapidocs.com, an Autodesk Community thread on `SetSectionBox`) — not previously
  used anywhere in this codebase, but conceptually the same shape as
  `IsolateElementsTemporary`/`DisableTemporaryViewMode`: a `Transaction`-wrapped view-state
  toggle with an on/off lifecycle.
- Only works on a `View3D` — `_combined_host_space_bounding_box` and camera fly-to already
  have this exact constraint (`isinstance(active_view, deps.View3D)`), so mirror that
  same guard and console-note-on-skip posture, don't invent a different one.
- The box: compute `_combined_host_space_bounding_box(clash_result, host_doc, active_view, deps)`
  then `_pad_bounding_box(...)` — the identical two-function call camera fly-to already
  makes, reused verbatim, not reimplemented or approximated. Use `CAMERA_REFRAME_PADDING_FRACTION`
  or a similarly-named ticket-owned constant — decide which is more appropriate and say why
  in your Implementation section (a shared constant risks camera fly-to and Isolate's box
  drifting in lockstep for reasons that have nothing to do with each other; a separate one
  risks needless duplication for what might genuinely be the same "sensible margin" value —
  this is a small judgment call, make it and document it, don't leave it unconsidered).

## Scope

- Apply/clear lifecycle mirrors host isolate's exactly: `IsSectionBoxActive = True` +
  `SetSectionBox(box)` inside a `Transaction` on apply; `IsSectionBoxActive = False` inside
  a `Transaction` on clear (turning Isolate off, or closing the window while it's on).
  Reuse `isolate_view_id`'s existing session-scoped-view capture (don't add a second,
  separate "which view" tracking mechanism for the section box — it's the same view host
  isolate already captured and reuses).
- Navigating to a different clash while Isolate stays on: recompute the box for the new
  clash and call `SetSectionBox` again — this replaces the previous box outright (no delta
  logic needed here, unlike 1017's abandoned hide-by-identity approach; `SetSectionBox`
  natively replaces the whole box in one call, this is the "many pipes" fast path already
  built in, not something to build).
- Every Revit-API-touching call goes through `_revit_api_bridge`, same as every existing
  feature — no exception.
- Do not touch `_isolate_host_element`, `_exit_temporary_isolate`, colorize, or camera
  fly-to. Add alongside `_apply_isolate_for_clash`/`_clear_isolate_if_active`'s existing
  bodies, the same way 1009's own host-isolate code was added alongside earlier features.
- If the active view isn't a `View3D`: skip the section box for this apply with a console
  note (mirroring camera fly-to's exact wording style), leave host isolate working exactly
  as it does today. Do not block or fail the whole Isolate toggle over this.
- Known, accepted, already-documented trade-off — do not attempt to "fix" it in this
  ticket: a section box crops by region, not by identity, so a non-clashing element
  physically near the clash can remain visible. This was explicitly decided when this
  ticket was scoped; if it becomes a real problem in practice, that's a future ticket, not
  a reason to add per-element hiding back into this one.

## Verification expectations

Same standing limitation as every ticket in this project without a live Revit session:
confirm via a live-connection check first if one is available. If not:
- Write a standalone, no-Revit-dependency simulation (`scratchpad/verify_1018.py`) for
  whatever pure-Python logic exists here (the view-type guard branch, the
  apply/clear/re-apply state transitions) — there's much less to mock than 1017 had, since
  the box math itself is already verified elsewhere (ticket 1004) and this ticket only
  wires a `Transaction`-wrapped API call around it.
- Do not claim `SetSectionBox`'s exact behavior (e.g. whether it visibly crops linked
  geometry the instant it's set, without needing a view refresh) is verified from
  reasoning alone — flag plainly if it's untested against a live session.

## Deployment

Standard gate (not 1017's stricter one — this mechanism has no equivalent
never-before-used-this-way risk; `SetSectionBox` is a synchronous, well-documented,
Transaction-wrapped call, the same shape as everything else in this file): deploy to the
live pyRevit install after `py_compile` and the standalone verification pass, following
the same md5sum-confirmed copy procedure every prior ticket has used. If a live Revit
session is reachable during implementation, use it to confirm the section box actually
crops linked geometry as expected before closing this ticket.

## Implementation

Everything lives in `ClashFlag.extension\BIM Tools.tab\Clash Detection.panel\ClashFlag.pushbutton\script.py`'s
new "ISOLATE LINK VIA SECTION BOX (T-18 / ticket 1018)" section, placed immediately after
the unchanged "ISOLATE CURRENT CLASH" section and before the "HELPER DEPS CONTAINER"
section (both existing sections it depends on). No live Revit MCP tool was reachable in
this sandbox this round (only an unrelated Navisworks MCP connector was available) — the
"no live session" verification path was used throughout, exactly as flagged in the
ticket's own "Verification expectations".

**Two new Transaction-wrapped helpers, mirroring `_isolate_host_element`/
`_exit_temporary_isolate`'s exact shape and placement, UNCHANGED per hard requirement #1:**
`_apply_section_box_for_clash(host_doc, view, clash_result, deps)` and
`_clear_section_box(host_doc, view, deps)`. Both reuse
`_combined_host_space_bounding_box`/`_pad_bounding_box` verbatim (hard requirement #2) —
the exact same two-function call `reframe_active_view_on_clash` already makes for camera
fly-to, not reimplemented or approximated.

**The padding-constant judgment call (ticket instruction, hard requirement #2), made and
recorded rather than left unconsidered:** introduced a SEPARATE constant,
`SECTION_BOX_PADDING_FRACTION = 0.15`, rather than reusing
`CAMERA_REFRAME_PADDING_FRACTION`. Reasoning (documented in full at the constant's own
module-level comment, right after `CAMERA_REFRAME_PADDING_FRACTION`'s definition): the two
paddings answer genuinely different questions that happen to share a value today by
coincidence, not by necessity. Camera fly-to's padding is a *composition* concern — how
much empty margin looks good around the clash in the viewport, purely cosmetic, tunable for
"looks cramped" vs. "clash looks too small on screen." The section box's padding is a
*correctness* concern — how much margin is needed so the crop plane doesn't visibly slice
through the two clashing elements' own geometry at their exact bounding-box edge, which
would look like a rendering bug, not a stylistic choice. A future tuning pass on either
(e.g. "zoom in tighter for camera fly-to" or "the section box still clips a corner of a
diagonal pipe, pad it more") should not silently drag the other along for an unrelated
reason — a shared constant would make that an unavoidable coupling. Set equal to `0.15`
today only because that's already a proven-reasonable value for this exact box math with no
evidence yet that the section box needs a different one; independently adjustable from here
on, per the ticket's own framing of this as a real, not cosmetic, judgment call.

**The View3D guard (ticket instruction #4, hard requirement #4), designed to mirror, not
reinvent, `reframe_active_view_on_clash`'s existing posture:** `_apply_section_box_for_clash`
opens with `if not isinstance(view, deps.View3D): ... return False`, using the exact same
`isinstance` check, `deps.View3D` indirection (required by the T-12 broken-scope fix this
file's whole bridge-reached call graph already depends on), and "console note via
`output.print_md`, never a blocking `forms.alert`" posture as camera fly-to's own guard —
this note fires on EVERY apply/re-apply where it's skipped (not suppressed after the first,
unlike the unrelated "Isolate is ON" success note below it), matching camera fly-to's own
reasoning that a routine skip note is fine to repeat on every navigation step but a popup
would not be. `_clear_section_box` has its own, independent `isinstance` guard too (view
might not be a `View3D` even though host isolate's own `IsolateElementsTemporary` works on
any view type) — verified in the standalone simulation (test 7 below) that this guard is
checked BEFORE ever touching `IsSectionBoxActive`, not after (a subtly-wrong naive
implementation could read the property first and only isinstance-check on an
`AttributeError`, which would behave identically for a real `View3D`'s attribute but is a
strictly worse, more fragile order to write it in).

**One easy-to-get-subtly-wrong edge case designed against explicitly:** `_isolate_host_
element` places NO View3D requirement on its own target view at all — `IsolateElementsTemporary`
works on ANY `View` type. So a user can turn Isolate on while a 2D plan or section view (not
a `View3D`) is active: host isolate succeeds fine on that view, and — per hard requirement
#3 — `isolate_view_id` captures and reuses that exact (non-3D) view for the rest of the
session, same as it would for a 3D view. A naive implementation that checked "is the active
view a `View3D`?" only ONCE, e.g. in `isolate_checkbox_checked` at the moment the box is
first checked, and cached that answer for the session, would behave identically to the
correct version for the common case but would go subtly wrong the moment the user's
*actual* active view later differs from the *captured* one in View3D-ness in either
direction (e.g. checked while a 3D view was active, cached "apply the box," then the user
switches to a plan view and clicks Next — a cached-true answer would try to call
`SetSectionBox` against the captured 3D view regardless, which is actually still correct
here since the captured view never changes; but a naive re-check against
`doc.ActiveView` instead of the captured view, mirroring the SAME "don't re-read
`doc.ActiveView`" mistake `_apply_isolate_for_clash`'s own docstring already warns against
for host isolate, would silently apply or skip the section box based on the wrong view
entirely). Designed against by having `_apply_section_box_for_clash` take `view` as an
explicit parameter and run its `isinstance` check fresh on every single call, against
whatever `view` its caller (`_apply_isolate_for_clash`'s own already-correct session-view
resolution) hands it — never caching the guard's outcome and never re-deriving it from
`doc.ActiveView` on its own. This guarantees the section-box guard and the host-isolate
target always agree on which view is in play, every time, with no separate "which view are
we guarding" state of its own to drift out of sync with `isolate_view_id`.

**Wiring, added alongside (not inside) `_apply_isolate_for_clash`'s/`_clear_isolate_if_
active`'s existing bodies, per hard requirement #1:** in `_apply_isolate_for_clash`'s
`_apply` closure, `section_box_fn` (`_apply_section_box_for_clash`) is called immediately
after the existing `isolate_host_element_fn` call succeeds (so a section-box-specific
failure — including its own internal soft "not a View3D" skip, which returns `False`
rather than raising — never happens before host isolate has already committed, and never
undoes it), wrapped in its own try/except that reports failures via `output.print_md`
without resetting `isolate_active`/unchecking the box (unlike a host-isolate failure, which
still does both, unchanged). It runs before the existing `select_clash_pair_fn` call and the
existing "Isolate is ON" success note, which was extended (not replaced) to also describe
the section box and its region-vs-identity trade-off, still only printed once per session
per the existing suppress-on-repeat pattern. In `_clear_isolate_if_active`'s `_clear`
closure, `clear_section_box_fn` (`_clear_section_box`) is called independently, right after
the existing `exit_temporary_isolate_fn` call, in its own separate try/except — a failure in
either clear path is reported on its own and does not prevent the other from running, the
same independence posture the module docstring already establishes between Colorize and
Isolate.

**Session-view reuse (hard requirement #3), confirmed by inspection, not just claimed:**
neither new function nor either new call site introduces any new "which view" state —
`_apply_section_box_for_clash`/`_clear_section_box` both take `view` as a plain parameter,
supplied by the exact same `view` local `_apply_isolate_for_clash`'s/`_clear_isolate_if_
active`'s own closures already resolve from `self.isolate_view_id` (or `doc.ActiveView` on
the very first apply of a session) for host isolate. Grepped the new code for any new
`self.*_view_id` or similar attribute and found none.

**Every Revit-API-touching call goes through `_revit_api_bridge`** (hard requirement #5):
`_apply_section_box_for_clash`/`_clear_section_box` are captured as `self._apply_section_
box_for_clash_fn`/`self._clear_section_box_fn` in `ClashListWindow.__init__` (the one
delegate-free constructor call, per ticket 1011's established pattern) and only ever invoked
from inside the `_apply`/`_clear` closures already queued via `bridge.raise_action(...)` —
never called directly from a WPF event handler body.

**`BoundingBoxXYZ` added to the module's `Autodesk.Revit.DB` import list** (not previously
imported anywhere in this file) and to `_helper_deps` (`deps.BoundingBoxXYZ`), alongside
`SECTION_BOX_PADDING_FRACTION` (`deps.SECTION_BOX_PADDING_FRACTION`) — both needed by
`_apply_section_box_for_clash`'s own bare-name-lookup-is-broken-inside-the-bridge
constraint (T-12 / ticket 1012), the same reasoning behind every other `deps.X` reference in
this file's bridge-reached call graph.

**Verified, not just asserted correct**, via a standalone, no-Revit-dependency
re-implementation (`scratchpad/verify_1018.py`) that copies `_apply_section_box_for_clash`/
`_clear_section_box` VERBATIM (not re-derived from memory) and exercises them against mock
`View`/`View3D`/`Transaction`/`BoundingBoxXYZ` objects, covering:
1. `apply`'s `isinstance(view, deps.View3D)` guard: returns `False`, opens no Transaction,
   prints a console note.
2. `apply`'s "no bounding box available" soft-skip: returns `False`, opens no Transaction.
3. `apply`'s `ClashFlagError` (link unresolved) soft-skip: returns `False`, opens no
   Transaction, surfaces the specific error message.
4. A full successful `apply`: exactly one Transaction (`Start` then `Commit`, never
   `RollBack`), `IsSectionBoxActive` set `True`, `SetSectionBox` called exactly once with a
   box reflecting the padded combined bounding box, returns `True`.
5. A REPLACE, not accumulate, re-apply for a different clash on the SAME `View3D` mock:
   `SetSectionBox` called a SECOND time — confirmed this needs no delta/bookkeeping logic
   at all (unlike ticket 1017's abandoned approach), since `SetSectionBox` natively replaces
   the box in one call.
6. A genuine `SetSectionBox` failure: rolls back (`Start` then `RollBack`, never `Commit`)
   and re-raises — never swallowed.
7. `clear`'s `isinstance` guard runs BEFORE ever touching `IsSectionBoxActive` — verified
   against a mock `View` whose `IsSectionBoxActive` access deliberately raises
   `AttributeError`, confirming the guard order and not just its final behavior.
8. `clear`'s "already inactive" guard: no Transaction opened.
9. A full successful `clear`: exactly one Transaction (`Start` then `Commit`),
   `IsSectionBoxActive` set `False`.
10. The full session state-transition sequence a real Isolate toggle drives — apply(A),
    re-apply(B), clear — all against the SAME captured view object throughout, matching
    `isolate_view_id`'s session-scoping contract this ticket was required to reuse rather
    than reinvent.

All 28 checks pass (`ALL CHECKS PASSED`). Ran `python -m py_compile` against the edited
`script.py` — passes cleanly (syntax-only, same caveat as every other ticket in this file:
it imports `Autodesk.Revit.DB`/`pyrevit` and cannot actually execute outside Revit).

**Not verified, and not claimed to be — flagged plainly per the ticket's own explicit
instruction:** no live Revit session or Revit MCP tool was reachable in this sandbox this
round (only an unrelated Navisworks MCP connector was available in this environment, which
cannot inspect or drive Revit). This means: (a) whether `View3D.SetSectionBox`/
`IsSectionBoxActive` are exactly correct method/property names and signatures against the
live Revit 2024.3 API was NOT independently re-confirmed this round beyond the ticket's own
cited sources (revitapidocs.com, an Autodesk Community `SetSectionBox` thread, and ticket
1004's own prior research into and rejection of the same API for a different purpose) — the
same "recalled from established knowledge, not independently re-verified this session"
posture ticket 1009 flagged for its own Isolate API surface before a later live-Revit-MCP
review round confirmed it; and (b) whether setting these two members visibly and
immediately crops linked-model geometry in a real Revit view, without needing an explicit
view refresh/redraw, was NOT exercised against a live model at all. Recommend a reviewer
with Revit MCP or live-session access specifically re-confirm both before this ships to a
real user's daily workflow, mirroring exactly the kind of follow-up 1009's own Phase 7
review round performed for its own new API surface.

**Deployed:** confirmed the pre-existing deployed `script.py` at
`C:\Users\Essam.Lap\AppData\Roaming\pyRevit\Extensions\ClashFlag.extension\BIM Tools.tab\Clash Detection.panel\ClashFlag.pushbutton\script.py`
was byte-identical to this repo's pre-edit `HEAD` version of the same file (both
md5 `b88ba7dbb9746bac1a5e73852f55ed73`) before overwriting — no undocumented drift to
clobber. After copying the updated `script.py` over it, both the sandbox and deployed
copies match: md5 `c98131c32db99f58d50c9773ff7f90f8` on both.

Label left `ready-for-agent` per the ticket instructions — review phase to flip to `done`
on pass.

## Phase 7 review: PASS (with one flagged edge case, not blocking)

Read the full diff directly (not just the implementer's summary). Confirmed: zero changes
to `_isolate_host_element`, `_exit_temporary_isolate`, Colorize, or camera fly-to (grepped
the diff for removed function definitions — none). `_apply_section_box_for_clash`/
`_clear_section_box` correctly mirror the host-isolate helpers' exact
Transaction/rollback shape, correctly guard on `View3D` before touching any
`View3D`-only member (avoiding an `AttributeError` on a non-3D captured view), and
correctly reuse `_combined_host_space_bounding_box`/`_pad_bounding_box` verbatim rather
than approximating. The `SECTION_BOX_PADDING_FRACTION` judgment call (separate constant,
same starting value, independently tunable) is sound reasoning, not just asserted.

Independently re-ran verification rather than trusting the summary: `python -m py_compile`
clean; `scratchpad/verify_1018.py` re-executed directly — all 28 checks pass, including
the two hardest-to-get-right ones (the `View3D` guard runs *before* any
`IsSectionBoxActive` access, so a non-3D captured view can never throw; re-applying for a
new clash calls `SetSectionBox` a second time with a genuinely new box, not a mutated
old one). Confirmed sandbox and deployed `script.py` md5s match
(`c98131c32db99f58d50c9773ff7f90f8` on both) — deployment is real, not just claimed.

**One edge case worth flagging, not worth blocking on:** `_clear_section_box` only
toggles `IsSectionBoxActive` off — it never restores a section box's prior *bounds*. If a
user already had their own manual section box active on this view before ever turning on
Isolate, `_apply_section_box_for_clash` overwrites those bounds with the clash's box, and
turning Isolate off correctly turns the box off but leaves it holding ClashFlag's last
bounds rather than the user's original ones. Unlike host isolate's Temporary Isolate mode
(inherently transient, resets cleanly by design), a Section Box is real persisted view
state — this is a narrow but genuine "don't mess with the whole tool" gap the ticket
didn't anticipate. Not blocking closure on it (no clash-solving workflow described so far
combines a manual section box with Isolate), but worth a follow-up ticket if it ever
surfaces in practice — e.g. capturing the view's existing box bounds (not just whether it
was active) at first apply, and restoring them exactly on clear.

**Still unverified, as the ticket's own risk section always said would be true**: whether
`SetSectionBox`/`IsSectionBoxActive` visibly crop linked geometry immediately in a real
Revit view. This is a `View3D`-scoped, straightforward, well-documented API surface —
materially lower risk than 1017's abandoned `PostCommand` mechanism — but genuinely
untested against a live session in this round. Closing on the strength of the code and
its verification, with a live spot-check recommended (not required) whenever Isolate is
next used with a linked model open.

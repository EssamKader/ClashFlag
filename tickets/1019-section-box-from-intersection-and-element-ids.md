label: done

# T-19: Section Box sized from the real clash intersection, split into its own checkbox; element IDs in the clash list

Implements US-3 (revised), US-7 (reverted to host-only), US-9 (new). Reopens ticket
1018's Section Box after live testing found two real problems with it — read
[1018](1018-isolate-link-section-box.md) in full first, then this ticket's four pieces of
work, which all live in the same file and are sequenced below because #2 depends on #1
and #4 depends on #2.

**Depends on:**
- T-9 (1009-isolate-current-clash.md) — Isolate's host-side code
  (`_isolate_host_element`/`_exit_temporary_isolate`) is untouched throughout this
  ticket; only its BUNDLING with the section box (added in 1018) is removed.
- T-18 (1018-isolate-link-section-box.md) — `_apply_section_box_for_clash`/
  `_clear_section_box` (the two Transaction-wrapped helpers) are REUSED, not deleted,
  but their box-source input changes (see #3 below), and their call sites move from
  Isolate's checkbox handlers to a new, independent checkbox's handlers.
- T-1/T-2 (1001, the detection engine) — `solids_clash`, `find_clashing_pairs`,
  `ClashResult` are foundational, carefully-reviewed code. Read them in full before
  touching them. Only ONE call site of `solids_clash` exists
  (`find_clashing_pairs`, confirmed by grep) — safe to change its return shape, but do
  not change its actual clash-confirmation LOGIC (the `Volume > MIN_CLASH_VOLUME_FEET3`
  check), only what it additionally returns alongside that.

**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — US-3, US-7, US-9 (all revised
2026-09-07, round 2).
**Context:** [CONTEXT.md](../CONTEXT.md) — Isolate, Section Box.

## 1. Capture the intersection bounding box during detection (root fix)

`solids_clash(solid_a, solid_b)` already computes `result_solid = BooleanOperationsUtils.
ExecuteBooleanOperation(solid_a, solid_b, BooleanOperationsType.Intersect)` to confirm a
clash, then discards `result_solid` and returns only a bool. Change it to also return
`result_solid`'s own bounding box (small by construction — it's just the actual overlap
region) using the SAME `_outline_for_solid` helper the rest of this file already uses for
exactly this purpose (rotation-safe, host-space-correct — do not write a second, simpler
extraction). Decide the exact return shape yourself (e.g. `(is_clash, intersection_min,
intersection_max)` or a small named tuple) and use it consistently — do not leave two
different conventions in different places.

In `find_clashing_pairs`: the loop already does `if solids_clash(host_solid, link_solid):
found_clash_for_pair = True; break` — capture the intersection box from THIS call (the
one that set `found_clash_for_pair = True`) and thread it through to
`clashing_pairs.append(...)` (currently `(host_element, link_element)` — extend the
tuple). Per this function's own existing docstring, an element pair is only ever reported
once even if multiple solid-pairs clash — you only need the intersection from whichever
one was found first, not a union of all of them.

In `ClashResult.__init__`: add two new plain attributes (e.g. `self.intersection_min`,
`self.intersection_max`, both `XYZ` objects in host space — NOT the `Solid` object
itself; do not keep a live Solid reference alive past the detection pass) and thread the
new value through from wherever `ClashResult(...)` is constructed (find the call site —
likely in `run_interference_check` or similar; grep for `ClashResult(`).

**Do not change**: the pre-filter (`Outline.Intersects` bbox check), the
`MIN_CLASH_VOLUME_FEET3` confirmation threshold, or the "report once per element pair"
behavior. This is a pure additive capture of data that's already being computed, not a
change to what counts as a clash.

## 2. Show both Element IDs in the clash list

`ClashResult.describe()` currently shows `describe_element(self.host_element)`/
`describe_element(self.link_element)` (category + type name, no ID). Add each element's
`Id.IntegerValue` to the description — decide the exact format (e.g. "Host: Walls - Basic
Wall [id 123456]") and apply it consistently to both sides. This is independent of #1/#3
below and can be done first or last; it's listed here because it's small and touches the
same `describe()` method other pieces of this ticket don't need to touch.

## 3. Fix the Section Box's sizing — use the intersection, not the two full elements

`_apply_section_box_for_clash` (added in ticket 1018) currently calls
`_combined_host_space_bounding_box(clash_result, host_doc, view, deps)` — the combined
bounding box of the two FULL elements — then pads it. Change it to build the box directly
from `clash_result.intersection_min`/`intersection_max` (captured in #1 above) instead,
padded the same way via `_pad_bounding_box(clash_result.intersection_min,
clash_result.intersection_max, deps.SECTION_BOX_PADDING_FRACTION, deps)`. This does NOT
need `_combined_host_space_bounding_box` at all anymore for this purpose — that function
stays exactly as-is for camera fly-to (T-4), which still legitimately wants the two full
elements in frame; do not change or touch `_combined_host_space_bounding_box` or camera
fly-to in this ticket.

Handle the case where `intersection_min`/`intersection_max` are unavailable (e.g. an
older `ClashResult` somehow missing them, or the intersection solid's own bounding box
extraction failed at detection time — `_outline_for_solid` can return `None`) the same
way `_apply_section_box_for_clash` already handles "no bounding box" today: a console
note via `output.print_md`, return `False`, no Transaction opened. Keep the existing
`View3D` guard exactly as it is (unrelated to this change).

## 4. Split Section Box into its own independent checkbox

Currently (ticket 1018) `_apply_section_box_for_clash`/`_clear_section_box` are called
from INSIDE `ClashListWindow._apply_isolate_for_clash`'s `_apply` closure and
`_clear_isolate_if_active`'s `_clear` closure, alongside the host-isolate calls. Remove
those calls from there — `_apply_isolate_for_clash`/`_clear_isolate_if_active` revert to
doing ONLY what they did before ticket 1018 (host isolate + Select, nothing else).

Add a new, independent checkbox, `SectionBoxCheckBox` in `clashflag_clash_list.xaml`
(new `Grid.Row`, shift the Previous/Next/Close button row down by one, add a
`RowDefinition` — follow `IsolateCheckBox`'s exact XAML shape/comment style directly
above it), wired to new `section_box_checkbox_checked`/`_unchecked` handlers in
`ClashListWindow` (script.py) that mirror `isolate_checkbox_checked`/`_unchecked`'s exact
structure and lifecycle:
- Own state: `self.section_box_active`, `self.section_box_view_id` (mirror
  `isolate_active`/`isolate_view_id`'s exact "capture once per session, reuse by id,
  never re-read `doc.ActiveView` on re-apply" pattern — read `_apply_isolate_for_clash`'s
  own docstring for why, and apply the identical reasoning here).
- Own apply/clear methods (e.g. `_apply_section_box_for_clash_toggle`/
  `_clear_section_box_if_active` — pick clear names that don't collide with the existing
  module-level `_apply_section_box_for_clash`/`_clear_section_box` functions from 1018)
  that queue `_apply_section_box_for_clash`/`_clear_section_box` via `_revit_api_bridge`,
  exactly like `_apply_isolate_for_clash`/`_clear_isolate_if_active` do for their own
  helpers.
- Re-applies on every Next/Previous/list-click navigation while checked — hook into the
  same `on_selection_changed`/selection-hook mechanism `_apply_isolate_for_clash` and
  `_apply_isolate_for_clash`'s colorize counterpart already use (there is an existing,
  shared "fire on every navigation step while this toggle is active" hook — find and
  reuse it, do not invent a second one).
- Clears on `Unchecked` AND on the window's `Closed` event, exactly mirroring
  `_clear_isolate_if_active`'s own dual call sites (`isolate_checkbox_unchecked` and
  `show_clash_list`'s Closed handler) — add the equivalent third call alongside the
  existing `_clear_colorize_if_active()`/`_clear_isolate_if_active()` calls there.
- Independent of Isolate and Colorize: do not read or write `isolate_active`/
  `colorize_active`/their state from this new code, and do not have this new toggle's
  state read from either of those — verify by grep once done, the same way ticket 1009's
  review verified Isolate/Colorize independence.
- Follows the T-11/T-12 bridge-scoping conventions exactly (capture every module-level
  name this new code needs as a `self.*` attribute in `__init__`, thread `deps` through
  every function in this call graph, register new entries in `_helper_deps` for anything
  referenced bare from inside another graph function's body) — grep for how
  `isolate_view_id`/`_isolate_host_element_fn` etc. are captured and match that pattern
  precisely, do not guess at a different shape.

## Verification expectations

No live Revit session assumed available by default — check first. If unreachable:
- Write a standalone, no-Revit-dependency simulation (`scratchpad/verify_1019.py`)
  covering: (a) `solids_clash`'s new return shape and that the intersection box it
  returns is genuinely smaller than either input solid's own full bounding box in a
  constructed mock scenario (a small mock "intersection" solid vs. two much larger mock
  "element" solids) — this is the single most important thing to prove, since it's the
  entire point of this ticket; (b) the new checkbox's apply/clear/re-apply state
  transitions, mirroring how ticket 1018's own `verify_1018.py` covered the equivalent
  for the (now-removed) bundled version; (c) confirm independence from Isolate/Colorize
  state by construction (the new code never reads their attributes).
- Run `python -m py_compile` on the edited `script.py`.
- Do NOT claim `SetSectionBox`'s live visual behavior is verified without a real session
  — same standing caveat ticket 1018 already carries forward, unchanged by this ticket.

## Deployment

Standard gate (same as 1018 — this ticket doesn't introduce any new async/PostCommand
risk, it changes a box-sizing input and splits a checkbox). Deploy after verification
passes, following the established md5sum-confirmed copy procedure.

## Implementation

Everything lives in `ClashFlag.extension\BIM Tools.tab\Clash Detection.panel\ClashFlag.pushbutton\script.py`'s
detection pipeline (`solids_clash`/`find_clashing_pairs`/`ClashResult`, all near the top of
the file, unchanged in location), the renamed "SECTION BOX FOCUSED ON THE CLASH (T-19 /
ticket 1019)" section (formerly ticket 1018's "ISOLATE LINK VIA SECTION BOX", right where
that section already was), and `ClashListWindow`'s new `section_box_checkbox_checked`/
`_unchecked`/`_apply_section_box_for_clash_toggle`/`_clear_section_box_if_active` methods
(placed directly after the reverted `_clear_isolate_if_active`, before
`_on_list_selection_changed`) plus a new `SectionBoxCheckBox` in
`clashflag_clash_list.xaml`. No live Revit session or Revit MCP tool was reachable in this
sandbox this round (only an unrelated Navisworks MCP connector was available) — the "no
live session" verification path was used throughout, exactly as the ticket anticipated.

### Part 1 — capturing the intersection box at detection time

`solids_clash(solid_a, solid_b)` now returns a 3-tuple `(is_clash, intersection_min,
intersection_max)` instead of a bare bool. The `is_clash` decision itself
(`result_solid.Volume > MIN_CLASH_VOLUME_FEET3`, plus the existing defensive
try/except-as-"not a confirmed clash" posture around the boolean op) is **byte-for-byte
unchanged** — verified by inspection, since the whole point of this ticket is to capture
data ALONGSIDE an existing decision, not to change the decision. When `is_clash` is `True`,
`result_solid` — the exact intersection solid already computed to make that decision, and
previously discarded immediately afterward — is handed to `_outline_for_solid`, the SAME
helper every other solid-to-host-space-bbox conversion in this file already uses (the
rotation-safe "transform all 8 corners of the solid's own local bbox frame, not just the two
extreme ones" technique, factored out originally for the pre-filter and reused since 1004
for link-element bounding boxes too). This was a deliberate reuse, not a second
implementation: `Outline`'s own `MinimumPoint`/`MaximumPoint` properties are read off the
`Outline` `_outline_for_solid` already returns, rather than writing a parallel, simpler
"just read `Solid.GetBoundingBox().Min/Max` directly" shortcut that would have silently
reintroduced the exact under-coverage bug `_outline_for_solid`'s own docstring warns about
for any solid whose local bbox frame carries rotation (a very real possibility here, since
the intersection solid inherits the orientation of whichever geometry it overlaps — a
rotated pipe run, a mirrored link placement, etc.). A **live Solid reference is never kept
alive past this function** — only its two `XYZ` corner points are returned — per the
ticket's explicit instruction; `result_solid` itself falls out of scope the moment
`solids_clash` returns.

One subtlety designed against explicitly: `is_clash=True` and "an intersection box is
available" are NOT the same fact and must not be conflated. `_outline_for_solid` can itself
return `None` (e.g. a degenerate result solid whose own `GetBoundingBox()` fails) even when
the clash confirmation already succeeded — in that narrow case `solids_clash` returns
`(True, None, None)`, not `(False, None, None)`. A naive implementation that let
`intersection_outline is None` also flip `is_clash` to `False` would silently make a real,
confirmed clash disappear from the results entirely the moment its own bounding-box
extraction happened to fail — a strictly worse failure mode than "this real clash shows up
in the list but can't offer a Section Box." Verified in `scratchpad/verify_1019.py`'s
"(a2)" section with a `_ExplodingSolid` mock whose `GetBoundingBox()` raises: confirms
`is_clash` stays `True` while the box comes back `None`.

`find_clashing_pairs`'s inner double loop already tracked `found_clash_for_pair`/`break`
exactly at the point the first confirming solid-pair was found; the intersection box from
THAT SAME call is now captured into two new locals (`intersection_min`/`intersection_max`)
right alongside `found_clash_for_pair = True`, and threaded into the appended tuple —
`clashing_pairs` entries are now 4-tuples, not 2-tuples. The function's own documented
contract — "a given element pair is only reported once even if several of their respective
solids clash" — is untouched: exactly one intersection box is captured per reported pair
(whichever solid-pair happened to confirm the clash first), never a union across every
solid-pair that clashed, per the ticket's explicit "you only need the intersection from
whichever one was found first, not a union of all of them" instruction. `solids_clash` has
exactly one call site (confirmed by grep before touching it), so changing its return shape
required no shim/compatibility layer anywhere.

`ClashResult.__init__` gained two new trailing keyword-defaulted parameters,
`intersection_min`/`intersection_max` (default `None`), stored as plain `self.*` attributes
— both `XYZ` objects in host space, or both `None`. Defaults (rather than required
positional args) were chosen deliberately so a `ClashResult` can still be constructed
without them and so every consumer (`_apply_section_box_for_clash`, see Part 3) is forced by
this same shape to handle the "not captured" case rather than assume it's always there — the
ticket's own explicit instruction. `run_interference_check`'s single `ClashResult(...)`
construction site (found by grep) was updated to unpack the now-4-tuple `clashing_pairs`
entries and pass the two new values through.

### Part 2 — Element IDs in the clash list

`ClashResult.describe()` now appends `[id N]` (`Id.IntegerValue`) after each side's
`describe_element(...)` text, applied identically to both the host and link side per the
ticket's "apply consistently to both sides" instruction:
`"Host: {cat} - {type} [id {N}]   <->   Link [{link_name}]: {cat} - {type} [id {N}]"`. This
was independent of parts 1/3/4 and touched nothing else in `describe()`'s existing
formatting/structure.

### Part 3 — fixing the Section Box's box source (the actual bug fix)

`_apply_section_box_for_clash` no longer calls `_combined_host_space_bounding_box` at all.
It now reads `clash_result.intersection_min`/`intersection_max` directly and pads THAT via
the unchanged `_pad_bounding_box(..., deps.SECTION_BOX_PADDING_FRACTION, deps)` call — same
padding helper and constant as ticket 1018, wrapped around a genuinely different, much
tighter source box. `_combined_host_space_bounding_box` itself was not touched in any way —
confirmed by inspection (its own function body, docstring, and the one other call site that
legitimately still needs it, `reframe_active_view_on_clash`'s camera fly-to, are all
byte-identical to before this ticket) — it remains exactly what camera fly-to (T-4) uses.

The **missing-intersection-data guard** (ticket instruction #3, explicit) is handled the
same way this function already handled "no bounding box available" before this ticket: a
console note via `output.print_md`, `return False`, no `Transaction` opened — not a new,
differently-shaped failure mode. Verified concretely in `scratchpad/verify_1019.py`'s test
(b) section 5: a `ClashResult` with `intersection_min=None`/`intersection_max=None` causes
`apply_section_box_for_clash` to return `False` with zero side effects
(`IsSectionBoxActive` stays `False`), never raising.

The `View3D` guard, the Transaction/rollback shape, and `_clear_section_box`'s own
"isinstance guard before ever touching `IsSectionBoxActive`" ordering are all **unchanged**
from ticket 1018 — this ticket only replaces the box-SOURCE computation, per the ticket's
own framing ("Keep the existing View3D guard exactly as it is — unrelated to this change").

**Concretely reproducing the bug this fixes**, not just asserting the new box is smaller in
the abstract: `scratchpad/verify_1019.py`'s test (a) builds a 40×40×1 ft mock "floor slab"
host element, a 30×2×2 ft mock "duct run" link element, and a small 2×2×1 ft true
intersection region positioned inside both — then computes what ticket 1018's OLD
(combined-full-elements) box would have been from the exact same two elements. Result: the
old combined box has volume **3200 ft³**, the new intersection-based box has volume **4
ft³** — an 800× difference, concretely demonstrating exactly the "barely crops anything when
one element dwarfs the other" failure mode US-9 and this ticket's header describe, not a
synthetic toy example unrelated to the real motivating scenario.

### Part 4 — splitting Section Box into its own independent checkbox

`_apply_isolate_for_clash`'s `_apply` closure and `_clear_isolate_if_active`'s `_clear`
closure had their `section_box_fn`/`clear_section_box_fn` calls (and the `self._apply_
section_box_for_clash_fn`/`self._clear_section_box_fn` locals that fed them) removed
entirely — both methods are now, line-for-line, back to exactly what they did before ticket
1018 touched them (host isolate + Select on apply; exit Temporary Isolate mode only on
clear). Confirmed by code inspection in `scratchpad/verify_1019.py`'s test (c): a regex
extracts each method's real body (docstrings and `#` comments stripped first, so a
docstring's own explanatory mention of "no longer calls section_box_fn" doesn't
false-negative the check) and asserts `"section_box_fn("`/`"clear_section_box_fn("` do not
appear as an actual call anywhere in either method.

New, fully independent state on `ClashListWindow`: `self.section_box_active`/
`self.section_box_view_id`, added in `__init__` immediately after the existing
`isolate_active`/`isolate_view_id` block, mirroring that block's exact shape and the same
"capture the view ONCE at the first Checked of a session, reuse by id for every later
re-apply, never re-read `doc.ActiveView`" reasoning `_apply_isolate_for_clash`'s own
docstring lays out — applied here as its OWN, separately-tracked view, deliberately NOT
`isolate_view_id`. This matters for the same "stranded view" reason ticket 1009 originally
designed against for Isolate: since Section Box and Isolate are now two fully independent
toggles that a user can turn on/off at different times (per US-9's "any combination"), each
needs its own session-captured view — sharing `isolate_view_id` would have silently
re-coupled the two toggles the ticket explicitly requires stay decoupled, and would have
broken the moment a user checked Section Box, then Isolate, on two different active views.

New methods, named to avoid colliding with the existing module-level `_apply_section_box_
for_clash`/`_clear_section_box` functions they call, per the ticket's explicit naming
instruction:
- `section_box_checkbox_checked`/`_unchecked` — the XAML-wired `Checked=`/`Unchecked=`
  handlers, structurally identical to `isolate_checkbox_checked`/`_unchecked` (read
  already-held plain state, hand off to a shared apply/clear method, nothing Revit-API-
  touching called directly from the handler body).
- `_apply_section_box_for_clash_toggle` — shared by `section_box_checkbox_checked` (first
  apply of a session) and the new branch in `on_selection_changed` (every re-apply on
  Next/Previous/list-click navigation while `section_box_active` stays `True`) — the exact
  "one shared implementation so both call sites can never drift apart" reasoning
  `_apply_isolate_for_clash` itself already documents. Captures `reuse_view_id =
  self.section_box_view_id` in the raw handler body (a plain already-held-attribute read,
  no bridge needed, same as `isolate_view_id`'s own precedent) before queuing the actual
  `_apply_section_box_for_clash` call through `_revit_api_bridge.raise_action(...)`. On a
  soft skip (`applied=False` — not a View3D, or no intersection data captured, both already
  self-reporting via `output.print_md` inside `_apply_section_box_for_clash`), the toggle
  itself is deliberately left CHECKED rather than force-unchecked — per ticket instruction
  #3's "does not need to block or fail the whole toggle" framing, mirroring how a skipped
  camera reframe never fails the overall navigation step, so a later re-apply (e.g. after
  switching to a View3D) can still succeed without the user re-checking the box. A genuine
  Transaction/API failure (an exception, not a soft skip) DOES reset state and uncheck the
  box, matching `_apply_isolate_for_clash`'s own failure-handling posture.
- `_clear_section_box_if_active` — shared by `section_box_checkbox_unchecked` and the new
  `window._clear_section_box_if_active()` call added to `show_clash_list`'s `Closed`
  handler, alongside the existing (untouched) `_clear_colorize_if_active()`/
  `_clear_isolate_if_active()` calls. State reset (`section_box_active = False`,
  `section_box_view_id = None`) happens synchronously in the raw method body, not deferred
  into the queued bridge closure — identical double-fire-safety reasoning to
  `_clear_isolate_if_active`'s own docstring.

**Navigation re-apply reuses the existing shared hook, not a new one** (ticket instruction,
explicit): `on_selection_changed` gained one new, independent `if self.section_box_active:
self._apply_section_box_for_clash_toggle(clash_result)` branch, directly alongside (not
replacing) the existing `if self.isolate_active: ...` branch — the same one hook ticket 1004
built and ticket 1009 already extended once before. Verified in `scratchpad/verify_1019.py`
test (c) that this exact branch shape is present in the real method body, gated only on its
own flag.

**Independence, verified by code inspection, not just asserted** (`scratchpad/
verify_1019.py`, test (c)): for each of the four new Section Box methods AND each of the
four Isolate methods, the method's real body (docstrings/comments stripped) is grepped for
any reference to the OTHER feature's state attributes
(`self.isolate_active`/`self.isolate_view_id`/`self.colorize_active`/
`self.colorize_view_id`/`self.colorize_previous_overrides` for the Section Box methods, and
`self.section_box_active`/`self.section_box_view_id`/`self.colorize_active`/
`self.colorize_view_id` for the Isolate methods) — zero hits in either direction. All
in-docstring mentions of the other feature's attribute names (there are several, explaining
the independence itself in prose) were confirmed to be exactly that — comments/docstrings,
not live code — by re-running the same grep without stripping and manually inspecting every
hit before writing the stripping logic, so the automated check isn't accidentally
undercounting real references that merely happen to also appear near a comment.

New `SectionBoxCheckBox` added to `clashflag_clash_list.xaml`: a new `Grid.Row="5"`, with the
Previous/Next/Close button row shifted from `Grid.Row="5"` to `Grid.Row="6"` and one new
`RowDefinition` added, directly mirroring `IsolateCheckBox`'s exact XAML shape/comment style
(a header comment above it explaining what it does and how it relates to the sibling
toggles, `Checked=`/`Unchecked=` wired to the new handlers, a `ToolTip` explaining the
region-vs-identity trade-off and the "independent of Isolate and Colorize" framing). `__init__`'s
existing "disable checkboxes when there are zero clashes" block gained one line,
`self.SectionBoxCheckBox.IsEnabled = False`, alongside the existing Colorize/Isolate lines.

### Verification

`scratchpad/verify_1019.py` — standalone, no-Revit-dependency, run directly with `python
scratchpad/verify_1019.py`. **41/41 checks pass (`ALL CHECKS PASSED`)**:

- **(a) Intersection box smaller than either full element (8 checks)**: a mock 40×40×1 ft
  "floor slab" host solid, a mock 30×2×2 ft "duct run" link solid, and a mock 2×2×1 ft true
  intersection solid, run through a verbatim-ported copy of the real (post-fix)
  `solids_clash`/`_outline_for_solid`/`_transform_all_corners`. Confirms: a clash is
  reported; the returned intersection corners exactly match the true intersection solid's
  own corners (not a union, not either element alone); the intersection box's volume (4 ft³)
  is smaller than BOTH the host's (1600 ft³) and the link's (120 ft³) own full bounding
  boxes; and — the single most important check per the ticket's own framing — the OLD
  ticket-1018 combined-full-elements box (3200 ft³, computed from the same two elements)
  is **800× larger** than the new intersection-based box, concretely reproducing the exact
  "barely crops anything when one element dwarfs the other" bug this ticket exists to fix,
  not a hypothetical.
- **(a2) is_clash False / no-geometry edge cases (5 checks)**: zero-volume boolean result,
  `None` boolean result, and a real clash whose own bbox extraction fails (`GetBoundingBox`
  raising) — confirming the last case returns `is_clash=True` with `(None, None)`, NOT
  `is_clash=False`, per the "these are two independently-failable things" reasoning above.
- **(b) Section Box checkbox apply/clear/re-apply state transitions (15 checks)**: a mock
  `View`/`View3D`/`Transaction`/`Document` harness (mirroring ticket 1018's own
  `verify_1018.py` style) exercising: first apply targets `doc.ActiveView` at that moment;
  switching the mocked "active view" mid-session then re-applying for a new clash reuses the
  ORIGINALLY captured view (never the new "active" one) and calls `SetSectionBox` a SECOND
  time with a genuinely different box (replace, not accumulate); unchecking clears the
  session's own view even though a different view is "active" by then, and never touches
  that other view; a non-`View3D` view is a true soft no-op (no Transaction, checkbox stays
  in a valid, retriable state); and a `ClashResult` with no captured intersection data is
  also a true soft no-op with zero side effects.
- **(c) Independence from Isolate/Colorize by code inspection (13 checks)**: reads the real,
  deployed-candidate `script.py` off disk (not a hand-copied snippet) and greps each of the
  four new Section Box methods and each of the four Isolate methods (docstrings/comments
  stripped first) for the other feature's state attribute names — zero hits either
  direction. Also confirms, as real code (not docstring text), that `_apply_isolate_for_
  clash`/`_clear_isolate_if_active` no longer call `section_box_fn(`/`clear_section_box_fn(`
  at all; that `on_selection_changed` gates each toggle's re-apply on its own flag only; and
  that `ClashResult.describe()`'s real body includes both `Id.IntegerValue` reads (Part 2).

`python -m py_compile` on the edited `script.py` passes cleanly (syntax-only — it imports
`Autodesk.Revit.DB`/`pyrevit` and cannot actually execute outside Revit, same caveat as
every other ticket in this file). `clashflag_clash_list.xaml` re-validated as well-formed
XML via `xml.etree.ElementTree.parse`.

**Not verified, and not claimed to be** — per the ticket's own explicit "Do NOT claim
`SetSectionBox`'s live visual behavior is verified without a real session" instruction: no
live Revit session or Revit MCP tool was reachable in this sandbox this round (only an
unrelated Navisworks MCP connector was available). Whether the new, tighter Section Box
actually visibly crops linked-model geometry down to the true clash region in a real Revit
2024.3 view — as opposed to the mock-verified control-flow/state-machine correctness above —
was not exercised against a live model. This is the same standing caveat ticket 1018 already
carried forward unchanged (per this ticket's own "Deployment" section, "same standing
caveat ticket 1018 already carries forward, unchanged by this ticket"). Recommend a reviewer
with live-session access spot-check this the next time Isolate/Section Box are used together
against a real model with a genuinely large-vs-small element pair (e.g. a floor slab vs. a
pipe), since that's precisely the scenario this ticket was written to fix.

### Deployment

Before overwriting, confirmed the pre-existing deployed `script.py`/`clashflag_clash_list.xaml`
at `C:\Users\Essam.Lap\AppData\Roaming\pyRevit\Extensions\ClashFlag.extension\BIM Tools.tab\Clash Detection.panel\ClashFlag.pushbutton\`
were consistent with this repo's pre-edit `HEAD` versions of the same two files — `git show
HEAD:...script.py` initially md5-mismatched the deployed copy
(`7a498dc8bab2eeb511d2ef78473b4f87` vs. deployed `c98131c32db99f58d50c9773ff7f90f8`), but this
was confirmed to be a line-ending artifact, not real content drift: piping `git show HEAD:...`
through `unix2dos` (CRLF-normalizing, matching how the working tree/deployed copy are checked
out on this Windows machine) produces the identical `c98131c32db99f58d50c9773ff7f90f8` — i.e.
`HEAD`'s `script.py` and the deployed copy already agreed content-wise before this ticket's
edits, and the earlier ticket 1018 deployment record (`c98131c32db99f58d50c9773ff7f90f8` for
both sandbox and deployed) checks out. `clashflag_clash_list.xaml`'s pre-edit `HEAD` and
deployed copies matched exactly, byte-for-byte, with no line-ending caveat needed
(`6456e676dd1e2285b2cca055cf5c731f` both). No undocumented drift to clobber either way.

After copying this ticket's updated `script.py` and `clashflag_clash_list.xaml` over the
deployed copies, both the sandbox and deployed copies of each file match exactly:
`script.py` → `fb250ba5838c8e0d97101dc4fd66685f` on both; `clashflag_clash_list.xaml` →
`83b6d218b66a5fc135ca9de8cf4558aa` on both — confirming byte-identical deployment, not just
claimed.

Label left `ready-for-agent` per the ticket instructions — review phase to flip to `done` on
pass.

## Phase 7 review: PASS

Read the full diff directly (734-line script.py diff, 53-line XAML diff, plus CONTEXT.md/
spec — the last two were mine, already correct). Traced all four pieces by hand:

- **`solids_clash`'s new 3-tuple return** correctly separates "is this a clash" (unchanged
  `Volume > MIN_CLASH_VOLUME_FEET3` logic, byte-for-byte) from "could a box be extracted
  for it" — the one subtle case (`is_clash=True, box=None`) is handled explicitly rather
  than silently collapsed into either "not a clash" or "assume the box exists." Confirmed
  only one call site of `solids_clash` exists, so the signature change is safe.
  `find_clashing_pairs` threads the box from whichever solid-pair broke the loop, matching
  its own pre-existing "report once per pair" contract exactly. Confirmed by reading the
  actual `ClashResult(...)` construction call site (line ~4036) that the new values are
  genuinely passed through positionally, not left to silently default to `None` at
  runtime.
- **`_apply_section_box_for_clash`** now sources its box from `clash_result.
  intersection_min`/`intersection_max` (with a defensive `getattr` fallback beyond the
  `__init__` default), never `_combined_host_space_bounding_box` — confirmed that function
  and camera fly-to are both completely untouched in the diff.
- **The Isolate revert is clean**: grepped the diff for `section_box` inside
  `_apply_isolate_for_clash`/`_clear_isolate_if_active` and found only removals, no
  remaining calls — Isolate is provably back to host-isolate-plus-Select, nothing else.
- **The new `SectionBoxCheckBox`** correctly mirrors `isolate_view_id`'s session-capture
  pattern with its own independent `section_box_view_id`, hooks into the existing shared
  `on_selection_changed` navigation hook (not a second one), and clears from both
  `Unchecked` and the window's `Closed` handler.

Independently re-ran verification rather than trusting the summary: `python -m py_compile`
clean; `scratchpad/verify_1019.py` re-executed directly — all 41 checks pass, including
the one that matters most: a mock 40×40×1 ft slab vs. a 30×2×2 ft duct produces the OLD
(1018-style) combined box at 3200 ft³ and the NEW intersection-based box at a fraction of
that — a concrete, reproducible demonstration of the bug this ticket fixes, not just an
assertion. Also independently grepped `section_box_checkbox_checked`/`_unchecked`/
`_apply_section_box_for_clash_toggle`/`_clear_section_box_if_active`'s bodies myself and
confirmed zero live references to `isolate_active`/`colorize_active` outside of docstring
prose. Confirmed both changed files (`script.py` and `clashflag_clash_list.xaml`) are
byte-identical between the sandbox and the deployed pyRevit install.

**Still unverified, as expected**: `SetSectionBox`'s live visual behavior on the new,
tighter box — same standing caveat carried since ticket 1018, unresolved this round for
the same reason (no live Revit/MCP session reachable). Recommend the live spot-check
happen on the real large-slab-vs-small-pipe case that motivated this whole round.

No design or correctness issues found. Closing as `done`.

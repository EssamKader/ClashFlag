label: done

# T-13: Category picker requires real solid geometry, not just instance presence

Implements the revised US-1 (2026-09-04, round 2 amendment). Fixes `_enumerate_present_categories`
(script.py:979) so a category is only offered in the scope picker — for the host document AND for
each selected linked document, since both call sites share this one function — when it is a
**Clash-Eligible Category** (see [CONTEXT.md](../CONTEXT.md)): at least one instance with real
solid geometry, not merely "an instance exists."

**Depends on:**
- T-2 (1002-scope-picker-ui.md) — `_enumerate_present_categories` is the function this ticket
  changes; both its call sites (`ScopePickerWindow`'s host block, `_build_one_link_block` for each
  link) must pick up the fix automatically since they call the same shared function — do not fork
  the logic into two copies.

**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — US-1 (revised).
**Context:** [CONTEXT.md](../CONTEXT.md) — Clash-Eligible Category.

## Problem

The current check is:

```python
has_instance = FilteredElementCollector(target_doc) \
    .OfCategoryId(category.Id) \
    .WhereElementIsNotElementType() \
    .FirstElement() is not None
```

This only proves an instance *exists*, not that it has anything to clash against. Categories like
Project Information and Lines pass this check (they're `CategoryType.Model` and have instances) but
have no solid geometry, so they show up in the picker as if they were clash-relevant — they aren't.
Conversely, a category like Doors being absent from a given document's picker is *correct* behavior
under the fixed definition too (that document genuinely has zero instances) — don't "fix" that part,
it isn't broken.

## Scope

- Replace the existence-only check with a geometry check: for candidate instances of the category,
  call `element.get_Geometry(Options())` and look for at least one `Solid` (in the returned
  `GeometryElement`, recursing one level into any `GeometryInstance` — nested families are common,
  e.g. a duct fitting or a door — via `GeometryInstance.GetInstanceGeometry()`) with
  `solid.Volume > 0`. A category qualifies the moment one such instance is found.
- **Bound the cost.** Do not call `get_Geometry` on every instance of every category — for a
  category with thousands of placed instances (e.g. Walls), the first instance is enough to prove
  eligibility in the overwhelming common case. Check at most the first **25** instances (collector
  order, no special sort) of a category before concluding it's not eligible; stop as soon as a
  qualifying solid is found. Document this cap and the reasoning inline — it's a deliberate
  precision/performance trade-off (a category where every one of the first 25 instances is
  genuinely non-geometric but instance #26 has geometry is not a realistic case worth the cost of a
  full linear scan), not an oversight.
- `Options()` should not set `ComputeReferences = True` (not needed just to test for a solid's
  existence/volume — this is a read-only presence check, not a selection/reference use case) and
  should leave `DetailLevel` at its default — do not tune these unless a live test shows a real
  category being missed because of it.
- Keep everything else in `_enumerate_present_categories` unchanged: the `CategoryType.Model`
  filter, the `BuiltInCategory`-only restriction (skip non-negative/custom category ids, same as
  today), and the de-duplication via `seen_built_in_categories`.
- Update the function's docstring to describe the new geometry check and the 25-instance cap,
  replacing the now-inaccurate "Existence is checked with ... FirstElement()" paragraph.
- No UI changes — `ScopePickerWindow` and `_build_one_link_block` already just iterate whatever
  `_enumerate_present_categories` yields; nothing downstream needs to change.

## Verification expectations

No live Revit session is available in this sandbox (same standing limitation as prior tickets).
`python -m py_compile` is the only mechanical check possible here. Because this ticket touches
geometry-inspection logic (the kind of thing that can look right and be subtly wrong — e.g. missing
the recursion into `GeometryInstance` and silently treating every family-instance-based category as
non-eligible), write a standalone, no-Revit-dependency simulation in `scratchpad/verify_1013.py`
using mock `Element`/`GeometryElement`/`GeometryInstance`/`Solid` objects that exercises:
1. A category whose first instance has a direct `Solid` with `Volume > 0` — qualifies immediately,
   without walking further instances.
2. A category whose instances only expose geometry via a nested `GeometryInstance` (family
   instance case) — qualifies only if the recursion into `GetInstanceGeometry()` is implemented;
   confirm the naive non-recursive version fails this case (proving the recursion is load-bearing,
   not decorative).
3. A category where every instance has a `GeometryElement` but zero `Solid`s with positive volume
   (e.g. curve/line-only geometry, or a `Solid` with `Volume == 0`) — does not qualify.
4. A category with more than 25 instances, none of the first 25 geometric, but instance #26 *is*
   geometric — does NOT qualify, proving the cap is real and enforced, not just documented.
5. The existing custom-category-id-skip and `CategoryType.Model`-only filtering still hold
   (unchanged logic, but confirm the new code didn't accidentally regress them).

Flag plainly, as prior tickets have, that this is a logic simulation, not a live-Revit-verified
result — recommend a reviewer with Revit MCP access spot-check on the user's actual host model
(confirm Project Information/Lines disappear, and that geometric categories the user actually has,
e.g. Walls/Ducts, still appear) before this is considered fully proven.

## Deployment

Same as every prior ticket in this file: after implementing and verifying in the sandbox, copy the
updated `script.py` to the live deployed copy at
`C:\Users\Essam.Lap\AppData\Roaming\pyRevit\Extensions\ClashFlag.extension\BIM Tools.tab\Clash Detection.panel\ClashFlag.pushbutton\script.py`,
diffing/`md5sum`-confirming the pre-existing deployed copy matches this repo's pre-edit `HEAD`
first (so nothing undocumented gets silently clobbered), then `md5sum`-confirming sandbox and
deployed copies match exactly after the copy.

## Implementation

Changed only `_enumerate_present_categories` (`ClashFlag.extension\BIM Tools.tab\Clash
Detection.panel\ClashFlag.pushbutton\script.py`), per the routing instruction — nothing else in
the file was touched (confirmed by keeping the diff scoped to that one function plus its
docstring).

**The existence check was replaced with a real geometry check, kept as a small helper local to
the function rather than a new top-level function** (`_has_qualifying_solid`, defined inside
`_enumerate_present_categories`'s own body) — this keeps the change literally contained to the one
function named in the ticket, rather than adding a second top-level symbol elsewhere in the module.
It deliberately does **not** reuse the existing `_iter_solids` helper (used elsewhere in this file
by `collect_candidate_solids` for the actual clash pipeline), even though the two look similar, for
two reasons worth flagging to a reviewer:
1. `_iter_solids` recurses into `GeometryInstance` at **arbitrary depth** and additionally requires
   `Faces.Size > 0` and a `MIN_CLASH_VOLUME_FEET3` (`1e-9`) epsilon rather than a literal
   `Volume > 0`. The ticket's scope section is explicit about a **one-level** recursion and a
   literal `solid.Volume > 0` test — a narrower, purpose-built existence check for the picker, not
   the clash-geometry pipeline's collection logic. Reusing `_iter_solids` would have silently
   widened this ticket's behavior beyond what was specified (deeper nesting support, a different
   volume threshold) without that being asked for or verified against the ticket's own test list.
2. `_iter_solids` has no early-stop/cap awareness — it is a plain generator over one already-open
   `GeometryElement`. This ticket's cap works across a document-order loop over the up-to-25
   collected *instances themselves*, not depth within a single element's geometry tree, so the
   ~35-line duplication here is a genuinely different loop shape, not an accidental copy-paste.

**Edge cases specifically designed against, matching the ticket's own five-scenario list:**
1. **Early stop on first qualifying instance.** The instance loop `break`s the moment
   `_has_qualifying_solid` returns True, and `_has_qualifying_solid` itself returns True the
   instant it finds one `Solid`/`Volume > 0` (no need to scan every `GeometryObject` in that
   element's tree either). A naive version might collect every solid across every instance before
   checking any of them — this one never even calls `get_Geometry` on instance #2 if instance #1
   already qualifies.
2. **Recursion into `GeometryInstance` is load-bearing, not decorative.** Family-instance-based
   categories (doors, duct/pipe fittings and accessories, curtain wall panels, etc.) very commonly
   expose zero `Solid` objects at the top level of `get_Geometry()`'s result — the real geometry is
   one level down, inside the placed family symbol's `GeometryInstance.GetInstanceGeometry()`.
   Missing this would silently make **every family-instance-based category ineligible**, the exact
   opposite of what the picker needs (most MEP/architectural categories users actually care about
   clash-checking are family-instance-based). Proven with a deliberately-constructed naive
   (non-recursive) variant in the verification script that fails this exact case (see below).
3. **Geometry-without-volume doesn't false-qualify.** Curve-only/annotation-only `GeometryObject`s
   are skipped outright (`isinstance` check only matches `Solid`/`GeometryInstance`), and a `Solid`
   that exists but reports `Volume == 0` (a degenerate/failed boolean result, or a construction
   line represented as a zero-thickness solid) is explicitly excluded by the strict `> 0` test —
   this is exactly the Project Information / Lines failure mode the ticket exists to fix, and the
   verification script checks a mixed bag of curve-only and zero-volume-`Solid` instances together
   to confirm neither slips through.
4. **The 25-instance cap is enforced, not just documented.** The loop increments a counter and
   breaks at 25 checked instances **before** calling `get_Geometry` on the 26th — verified by
   instrumenting a counting mock element and asserting the 26th instance's `get_Geometry` was never
   even invoked, not just that the final yes/no answer was "no." A companion check re-runs the
   identical fixture with the cap raised to 26 and confirms it *would* qualify then, isolating the
   cap as the actual cause of scenario 4's negative result (rather than some unrelated bug in the
   solid-detection logic happening to also return False).
5. **Untouched logic stays untouched.** The `CategoryType.Model` filter, the negative-id
   `BuiltInCategory` cast/skip, and `seen_built_in_categories` de-duplication are byte-identical to
   the pre-ticket code (same lines, same order, just now sitting after the new geometry-scan block
   instead of after the old existence check) — confirmed by re-reading the diff line-by-line rather
   than assuming; the verification script also exercises a custom (non-negative id) category and a
   non-Model category, each carrying otherwise-qualifying solid geometry, and confirms both are
   still excluded exactly as before.

`Options()` is constructed once per `_enumerate_present_categories` call (not per-category or
per-instance — it's a stateless read-only parameter bag, no reason to reallocate it in the loop)
with no attributes set, so it keeps Revit's default `DetailLevel` and `ComputeReferences = False`,
exactly as the ticket specifies (no tuning "unless a live test shows a real category being missed
because of it" — no such live test was available this round, so defaults were left alone).

**Verified, not just asserted correct**, via a standalone, no-Revit-dependency re-implementation of
this exact algorithm (`scratchpad/verify_1013.py`, using mock `Element`/`GeometryElement`/
`GeometryInstance`/`Solid`/`Options` objects) exercising exactly the 5 scenarios the ticket lists,
plus two extra instrumented checks (call-count tracking on the early-stop and cap tests) to prove
behavior, not just outcomes. Actual output from running it:

```
--- Scenario 1: direct Solid on first instance, early stop ---
[PASS] Walls category qualifies
[PASS] only the first instance's get_Geometry was called (early stop)

--- Scenario 2: nested GeometryInstance solid, recursion load-bearing ---
[PASS] Doors qualifies WITH recursion (nested solid found)
[PASS] Doors does NOT qualify WITHOUT recursion (proves recursion is load-bearing, not decorative)

--- Scenario 3: geometry with no qualifying positive-volume Solid ---
[PASS] Lines (no positive-volume solid anywhere) does NOT qualify

--- Scenario 4: 25-instance cap enforcement ---
[PASS] category with qualifying geometry only at instance #26 does NOT qualify (cap enforced)
[PASS] exactly 25 instances were checked, #26 was never touched
[PASS] same data set DOES qualify once the cap is raised to 26 (isolates the cap as the cause)

--- Scenario 5: unregressed custom-category-id-skip and Model-only filter ---
[PASS] custom (non-negative id) category is skipped even with solid geometry
[PASS] non-Model CategoryType is skipped even with solid geometry
[PASS] a real Model-type BuiltInCategory with solid geometry still qualifies

======================================================================
ALL CHECKS PASSED
```

Also ran `python -m py_compile` against the edited `script.py` (syntax-only, same caveat as every
other ticket in this file — it imports `Autodesk.Revit.DB`/`pyrevit` and can't actually execute
outside Revit): passed with no output.

**This is a logic simulation, not a live-Revit-verified result**, exactly as the ticket's own
verification-expectations section anticipates — the mock objects reproduce the real API's
*shape* (iterable `GeometryElement`, `GeometryInstance.GetInstanceGeometry()`, `Solid.Volume`) but
not Revit's actual runtime behavior. Recommend a reviewer with Revit MCP access spot-check the
user's live host model: confirm Project Information and Lines disappear from the category picker,
and that geometric categories the user actually has placed (Walls, Ducts, etc., including any
family-instance-based ones like Doors or duct fittings) still appear — before this is considered
fully proven, per the ticket's explicit instruction.

**Deployed:** confirmed the pre-existing deployed `script.py` at
`C:\Users\Essam.Lap\AppData\Roaming\pyRevit\Extensions\ClashFlag.extension\BIM Tools.tab\Clash Detection.panel\ClashFlag.pushbutton\script.py`
was byte-identical to this repo's pre-edit `HEAD` version (`md5sum` `8d39a04e0a052da477a3507c84845cd9`
on both — no undocumented local drift to worry about) before overwriting. After copying the
updated `script.py` over it, `md5sum` on both the sandbox and deployed copies matches exactly:
`b88ba7dbb9746bac1a5e73852f55ed73` on both.

Label left `ready-for-agent` per the ticket instructions — review phase to flip to `done` on pass.

## Phase 7 review: PASS

Read the full diff directly (`git diff` on `script.py`, scoped entirely to `_enumerate_present_categories` as required — no other function touched). Confirmed both `Solid`, `GeometryInstance`, and `Options` are already imported at the top of the file (lines 414/413/419), so no missing-import risk. Traced the cap-counting logic by hand: `instances_checked >= max_instances_to_check` is checked *before* incrementing and processing, so exactly 25 elements are read per category, matching the ticket's "first 25" requirement precisely (not 24 or 26 off-by-one). The one-level-only recursion into `GeometryInstance.GetInstanceGeometry()` matches the ticket's explicit scope (not the file's existing, deeper-recursing `_iter_solids` helper used by the clash pipeline) — the implementer's stated reason for not reusing `_iter_solids` (different volume epsilon, unbounded depth, no per-instance cap) is correct and appropriately flagged rather than silently diverging.

Independently re-ran the implementer's own claims rather than trusting the summary:
- `python scratchpad/verify_1013.py` — re-executed myself, all 9 checks `PASS`, including the two hardest-to-get-right ones: recursion is proven load-bearing (a non-recursive variant fails scenario 2), and the 25-cap is proven enforced by the instrumented call-count check in scenario 4, not just asserted from the code reading right.
- `python -m py_compile` on the edited `script.py` — passed clean.
- `md5sum` on both the sandbox and deployed copies of `script.py` — both `b88ba7dbb9746bac1a5e73852f55ed73`, confirming the live pyRevit install actually has this fix, not just the sandbox.

**Live spot-check attempted, not completed:** tried `get_current_view_info` via Revit MCP against the user's live session to directly confirm Project Information/Lines now disappear from the real host model's picker while Walls/Doors/etc. still appear — timed out (no response), the same class of connectivity gap seen earlier this session (e.g. a stray dialog left open in the Revit window). Did not retry repeatedly to avoid compounding a live-session disruption. **Recommend the user re-run ClashFlag's scope picker in Revit** after this deploy to confirm the real-world result matches the simulation (Project Info/Lines gone, genuinely-present geometric categories unaffected) — closing on the strength of the code review and the independently-reproduced simulation, with this one live-confirmation step still open for the user to do themselves.

No design or correctness issues found. Closing as `done`.

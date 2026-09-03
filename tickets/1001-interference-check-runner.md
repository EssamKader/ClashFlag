label: done

# T-1: Core interference-check runner

Implements US-2. Thin tracer-bullet slice: a pyRevit script that calls
`Document.PerformInterferenceCheck` against the active document + one hardcoded
linked instance, with a fixed category filter, and prints the resulting
`InterferenceResult` pairs (element ids + categories) to the pyRevit output console.
No UI yet — proves the native-API integration works end-to-end before anything is
built on top of it.

**Depends on:** none.
**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — US-2.

## Phase 7 review comments (round 1 → rework required)

`scripts/clashflag_runner.py` v1 used `InterferenceCheckOptions.LinkInstance2` to
check host-vs-link directly. That rests on an unverified claim (see
[0004's erratum](0004-linked-model-api-research.md) and
[0002's reopened decision](0002-detection-method.md)) that the native check
auto-applies the link's transform — it likely doesn't for the cross-document case.

**Rework scope:** replace the `LinkInstance2`-based call with the manual pipeline:
collect host candidates + linked candidates (via the same fixed category filter as
before, e.g. structural framing vs. ducts) separately, transform the linked
elements' geometry into host space via `RevitLinkInstance.GetTotalTransform()` +
`SolidUtils.CreateTransformed`, do a bbox-overlap pre-filter, then
`BooleanOperationsUtils.ExecuteBooleanOperation(..., Intersect)` on surviving pairs
to confirm real intersections. Keep everything else the same (still read-only, no
Transaction; still prints clash pairs to the pyRevit output console; still no UI —
that's 1002+).

This is exactly the kind of subtle, easy-to-get-silently-wrong geometry/coordinate
work the `implementer-hard` tier exists for — route the rework there instead of the
plain implementer.

**Status:** reopened, needs rework.

## Rework complete

`scripts/clashflag_runner.py` no longer calls
`InterferenceCheckOptions.LinkInstance2` for the host-vs-link comparison. It now
implements the manual pipeline from the 0004 erratum / 0002 reopened decision:

- Host candidates (`OST_StructuralFraming`) are collected directly from the
  active document — already host coordinate space, no transform needed.
- Linked candidates (`OST_DuctCurves`) are collected from
  `RevitLinkInstance.GetLinkDocument()` — link-local coordinate space at that
  point.
- `RevitLinkInstance.GetTotalTransform()` (link-local → host; chosen over
  `GetTransform()` because it also folds in true-north) is applied to every
  linked `Solid` via `SolidUtils.CreateTransformed` before any comparison, so
  every solid downstream is guaranteed to be in host space.
- A per-solid bbox pre-filter using `Outline.Intersects` (not raw
  `Element.BoundingBox`, and not a naive corner-transform of an element's
  overall bbox) runs before the expensive check.
- `BooleanOperationsUtils.ExecuteBooleanOperation(..., Intersect)` on
  surviving pairs confirms a real, non-zero-volume intersection; wrapped in
  try/except since boolean ops can throw on some solid inputs.

Edge cases specifically designed for:
- **Multi-solid elements** (curtain walls, family instances with nested
  geometry): geometry is walked recursively through
  `GeometryInstance.GetInstanceGeometry()`, and every solid on an element —
  not just the first — is checked and, on the link side, individually
  transformed and bbox-tested.
- **Zero-volume / annotation-only geometry**: solids below a tiny
  floating-point-noise volume threshold are filtered out during collection,
  so elements with no real geometry are skipped rather than producing
  spurious zero-volume "clashes."
- **`Solid.GetBoundingBox()`'s local-frame + separate `Transform` return
  shape** (different from `Element.BoundingBox`, which is already
  world-aligned): all 8 corners of the local box are transformed and
  re-min/maxed, rather than just the two corner points, so a rotated bbox
  transform (e.g. from a rotated link placement) can't silently under-cover
  a solid and cause the pre-filter to drop a real clash.
- **Multiple loaded instances of the same link** at different placements:
  explicitly NOT handled by this tracer-bullet version (documented in a code
  comment next to `LINKED_MODEL_INSTANCE_NAME` and `find_link_instance`) —
  `find_link_instance` still resolves to the first loaded match by name only.
  Full multi-instance support remains out of scope for this ticket, matching
  the original tracer-bullet scope.

Kept unchanged from v1: read-only (no `Transaction`), fixed hardcoded category
filters and link instance name, pyRevit output-console reporting, one printed
line per clashing element pair (deduplicated even when several solids on the
same two elements independently intersect), no UI, no tolerance/near-miss
logic.

Not independently verified (no live Revit session in this sandbox) — flagged
for reviewer attention: the exact runtime behavior of
`RevitLinkInstance.GetTotalTransform()` vs `GetTransform()` on a real project
with a non-identity/rotated/mirrored link placement, and whether
`Solid.GetBoundingBox()`'s "local frame + Transform" return shape behaves
exactly as documented across the Revit version this ultimately targets.

**Status:** rework complete, ready for review (round 2).

## Phase 7 review — round 2: PASS

Independently verified `RevitLinkInstance.GetTotalTransform()` via web search
(revitapidocs.com + an Autodesk forum thread confirming it folds in true-north) —
checks out, unlike round 1's unverified claim. The `Solid.GetBoundingBox()`
local-frame gotcha the code guards against is also a real, documented trap.
Pipeline design (bbox pre-filter → per-solid transform → boolean intersection) is
sound and matches 0002's reopened decision.

Minor non-blocking note for a future ticket: `element.Id.IntegerValue` is
deprecated in Revit 2024+ in favor of the 64-bit `.Value` property — worth
revisiting if this targets a recent Revit version.

**Closed.**

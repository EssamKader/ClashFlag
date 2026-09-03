label: wayfinder:decision
type: Research

# Revit API approach for cross-model (linked) clash detection

## Finding

Don't hand-roll geometry transform + solid intersection. Revit's API exposes the same
engine the built-in Interference Check command uses:

```csharp
Document.PerformInterferenceCheck(InterferenceCheckOptions options)
```

`InterferenceCheckOptions` takes `Document1` / `Document2` (or `LinkInstance1` /
`LinkInstance2` in newer overloads) plus optional `ElementFilter`s per side. When
`Document2` is a linked document, the API automatically applies the link's transform
— no manual `RevitLinkInstance.GetTransform()` + `SolidUtils.CreateTransformed()`
bookkeeping needed. Returns `IList<InterferenceResult>`, each with the two clashing
`Element`s and their intersecting `Solid`.

Implications for the design decisions still open:
- **Detection method (0002)**: the native check already does bbox-first-pass then
  solid intersection internally — building a custom bbox/solid pipeline would just
  duplicate slower, buggier logic. Tolerance (near-miss clearance) is NOT supported
  natively — that requires post-filtering: offset one solid's bounding box by the
  tolerance before re-checking, or fall back to `Solid.IntersectWithSolid` /
  `ShortestDistanceTo` manually for the "soft clash" case only.
- **Scope (0003)**: category filtering is just an `ElementCategoryFilter` (or
  `LogicalOrFilter` of several) passed as the per-document `ElementFilter` — cheap to
  make configurable.
- **Multiple link instances**: if the same link is loaded more than once (different
  placements), each `RevitLinkInstance` must be checked separately — `Document2`
  alone doesn't disambiguate which placement.
- **Performance**: this is the native, compiled path Revit's own UI uses, so it scales
  far better than a manual O(n×m) geometry loop on large federated models. No custom
  spatial partitioning needed for v1.

## Erratum (Phase 7 review, after ticket 1001)

The claim above that `Document2` pointed at a linked document "automatically applies
the link's transform" could not be verified — revitapidocs.com isn't indexed by
search and the Autodesk forum blocked fetch — and is very likely **wrong**. The
well-documented behavior is that elements returned via
`RevitLinkInstance.GetLinkDocument()` are in the **link's own local coordinate
space**, not the host's. Using them directly in `PerformInterferenceCheck` risks
silently missing real clashes (or flagging phantom ones) on any link that isn't at
an identity transform relative to the host — i.e. almost always.

**Corrected approach:** don't rely on the native API's document-vs-document
overload for the linked side. Instead:
1. Collect candidate elements from host + link separately (with the chosen category
   filters).
2. Get `RevitLinkInstance.GetTotalTransform()` and apply it to each linked
   element's geometry (`SolidUtils.CreateTransformed(solid, transform)`, or
   transform the bounding box for a first-pass filter) before any comparison.
3. Do a bbox-overlap pre-filter (fast) then `BooleanOperationsUtils
   .ExecuteBooleanOperation(solidA, solidB, Intersect)` (or `Solid` clash check) on
   surviving candidate pairs for the precise result.
4. `PerformInterferenceCheck` is still fine for **host-vs-host** clashes (Document1
   == Document2 == active document, different category filters) — the risk is
   specifically the cross-document/linked case.

## Status: reopened → corrected (see Erratum). Feeds back into 0002.

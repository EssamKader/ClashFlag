# ClashFlag

A pyRevit tool that detects hard clashes between the active (host) model and
selected linked models, then lets a BIM engineer review them one at a time.

## Language

**Select**:
Highlighting a clash's two elements (via `Selection.SetReferences`) without
hiding anything else in the view. Works for both the host-side and link-side
element, since Revit's selection API supports cross-document references.
_Avoid_: Isolate, highlight, focus

**Isolate**:
Temporarily hiding every element in the HOST view except one clash's
host-side element (Revit's native Temporary Isolate mode,
`View.IsolateElementsTemporary`) — host-side only, unchanged since ticket
1009. Two link-side approaches were tried and superseded before this
settled here: ticket 1017's `PostCommand`-based per-element hide (abandoned
before shipping — see that ticket's "Superseded" note), then ticket 1018's
attempt to bundle a Section Box into this same checkbox (reverted, ticket
1019 — a section box sized to the FULL host+link elements barely cropped
anything when one element was much larger than the other, e.g. a large
floor slab vs. a small pipe, and bundling it into Isolate removed the
ability to use it without also hiding host elements). Isolate itself is
back to exactly its original ticket-1009 scope; link-side focus now lives
entirely in the separate **Section Box** entry below. An opt-in toggle, not
ClashFlag's default behavior. Stepping to a different clash while Isolate is
on *replaces* the isolation (never accumulates). Independent of Colorize
and Section Box: turning Isolate on never forces the isolated element into
its category-pair color and never affects the section box, and vice versa —
a user can toggle any combination. Turning Isolate on always also Selects
both elements of the current clash (unchanged since ticket 1009 — the
link-side element still can't itself be isolated, so this keeps it findable).
Turning Isolate off, or closing the clash-list window while it's on,
immediately exits Temporary Isolate mode and restores the full host view.
_Avoid_: Select, highlight, focus

**Section Box**:
An opt-in toggle, independent of Isolate and Colorize (own checkbox, own
on/off lifecycle — added 2026-09-07, ticket 1019, after being tried and
reverted as part of Isolate in ticket 1018), that crops the active 3D
view's Section Box tightly around the CLASH ITSELF — not the two full
elements. Sized from the actual intersection geometry the detection engine
already computes to confirm the clash (`BooleanOperationsUtils.
ExecuteBooleanOperation(..., Intersect)` in `solids_clash`, captured onto
`ClashResult` at detection time rather than discarded), padded by a small
margin — so the box stays small and centered on the true clash point
regardless of whether the host element, the link element, or neither is
large. This is the fix for Isolate's own now-superseded Section Box attempt
(1018), which sized the box to the two FULL elements' combined bounding box
and barely cropped anything when one side (e.g. a large floor slab) dwarfed
the other (e.g. a small pipe). Crops geometry uniformly across host and
every linked model at the view-rendering level, with no per-element
identification needed — every other element outside that small region
simply doesn't render, in either model. **Known, accepted trade-off,
unchanged from 1018's original finding**: crops by 3D region, not by
element identity — a different, non-clashing element that happens to sit
physically close to the clash (e.g. a parallel pipe in the same MEP
corridor) can still appear inside the box. Only works on a `View3D`; if the
active view isn't one, turning Section Box on is skipped with a console
note. Stepping to a different clash while it's on replaces the box, never
accumulates. Turning it off, or closing the clash-list window while it's
on, immediately restores full visibility (`IsSectionBoxActive = False`).
_Avoid_: Isolate — a section box crops a 3D region; Isolate hides specific
elements. They compose (both can be on together) but are not the same
concept and no longer share a checkbox.

**Category Pair**:
The unordered pair of Revit Categories on either side of one clash (e.g.
Walls + Air Terminals). Order-independent by design: which category happens
to be "host" vs. "link" depends only on which file you opened ClashFlag from,
not on anything about the clash itself — a Walls/Air-Terminals clash must
read and colorize identically whichever side is host that day.
_Avoid_: (host category, link category) as an ordered tuple — this was an
early implementation bug, not the intended concept.

**Colorize**:
An opt-in toggle that overrides the HOST-side element of every clash in the
current result set with a color keyed by its Category Pair, so clash types
are visible at a glance across the whole model. Link-side elements are never
recolored — Revit's API and native UI have no mechanism to override an
individual linked element's *graphics* from the host view (unlike hiding
one, which Isolate now uses — a graphic-override limitation and a
visibility limitation are different capability ceilings, and only the
latter has a workaround). Colors are assigned by hashing the Category Pair's name directly into a hue
(fixed saturation/lightness tuned for visibility against a typical Revit
view) rather than cycling a small fixed palette — no saved/editable table,
no setup, and no collision as the model grows — so the same pair renders the
same color every run, every model, any discipline, with zero configuration.
_Avoid_: highlight, tag

**Legend**:
A read-out of the current Category-Pair-to-color mapping, shown inline in
the clash list panel itself (e.g. a color swatch next to each clash entry)
so a color's meaning is always visible alongside the clash it belongs to,
never a lookup you have to go find elsewhere.

**Clash-Eligible Category**:
A Model-type Category offered in ClashFlag's category picker for a given
document (host or a selected link). A category qualifies only if at least
one of its instances carries real solid geometry (a non-null `Solid` with
`Volume > 0`) — not merely "at least one instance exists." This is what
correctly excludes categories like Project Information and Lines, which can
have instances but nothing that actually occupies space to clash against.
Doors/Windows being absent from a given model's picker is not a bug under
this definition — it means that document genuinely has zero instances of
that category, geometric or otherwise.
_Avoid_: "present category" — the prior implementation's instance-count-only
check, which is the bug this term corrects.

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
Temporarily hiding every element in the view except one clash's elements
(Revit's native Temporary Isolate mode). Host-side only — Revit's API has no
way to isolate an element that lives inside a linked document alongside host
elements in the same operation, unlike Select. An opt-in toggle, not
ClashFlag's default behavior. Stepping to a different clash while Isolate is
on *replaces* the isolation (only the new clash's host element is shown) —
it never accumulates a working set across clashes. Independent of Colorize:
turning Isolate on never forces the isolated element into its category-pair
color, and turning Colorize on never isolates anything — a user can toggle
either, both, or neither. Because the link-side element can't be isolated,
turning Isolate on always also Selects both elements of the current clash —
this keeps the link-side element findable inside the still-fully-visible
link model. Turning Isolate off, or closing the clash-list window while it's
on, immediately exits Temporary Isolate mode and restores the full view
(same lifecycle as Colorize's clear-on-uncheck/close).
_Avoid_: Select, highlight, focus

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
recolored (same Revit API limitation as Isolate). Colors are assigned by hashing the Category Pair's name directly into a hue
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

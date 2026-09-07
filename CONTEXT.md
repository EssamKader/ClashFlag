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
Temporarily hiding every element in the view except one clash's two
elements — both the host-side AND the link-side element, full parity with
Navisworks' own clash-isolate behavior (revised 2026-09-07; previously
host-side only). Host-side isolation uses Revit's native Temporary Isolate mode
(`View.IsolateElementsTemporary`), unchanged since ticket 1009. Link-side
isolation (revised again, ticket 1018, superseding an abandoned
`PostCommand`-based approach from ticket 1017 — see that ticket's own
"Superseded" note for why) uses a **Section Box**
(`View3D.SetSectionBox`/`IsSectionBoxActive`): a 3D region, tightly padded
around the combined bounding box of both clashing elements, that crops
geometry uniformly across the host document AND every linked model at the
view-rendering level, with no awareness of document boundaries at all — so
every other pipe/element outside that region simply doesn't render, without
ClashFlag ever needing to identify or hide link elements one by one. This
reuses the exact `_combined_host_space_bounding_box`/`_pad_bounding_box`
math already built for camera fly-to (ticket 1004), and — unlike the
abandoned approach — is a normal synchronous, `Transaction`-wrapped API
call, the same shape as every other feature in this tool. **Known,
accepted trade-off**: a section box crops by 3D region, not by element
identity — a different, non-clashing element that happens to sit physically
close to the clash (e.g. a parallel pipe in the same MEP corridor) can still
appear inside the box. Only works on a `View3D`; if the active view isn't
one, link-side isolation is skipped with a console note (host isolation
still applies) — see US-7's "not a 3D view" handling, same posture camera
fly-to already has. An opt-in toggle, not
ClashFlag's default behavior. Stepping to a different clash while Isolate is
on *replaces* the isolation on both sides (never accumulates a working set
across clashes). Independent of Colorize: turning Isolate on never forces
the isolated element into its category-pair color, and turning Colorize on
never isolates anything — a user can toggle either, both, or neither.
Turning Isolate on still always also Selects both elements of the current
clash, unchanged from before — no longer load-bearing for "findability"
now that the link element is genuinely visible on its own, but kept as
matching, deliberately-unchanged host-side behavior per the 2026-09-07
Wayfinder round's explicit choice not to touch it. Turning Isolate off, or
closing the clash-list window while it's on, immediately exits Temporary
Isolate mode on the host AND restores every hidden link element (same
lifecycle as Colorize's clear-on-uncheck/close).
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

# Changelog

All notable changes to ClashFlag are recorded here, one entry per tagged release.
A version number here is a **deploy gate**: it marks a point that's been reviewed
and verified, not just merged. See `tickets/` for the full paper trail behind
every line below.

## [v0.6.0] - 2026-09-07

### Added
- **Section Box** — a new, independent toggle that crops the active 3D view tightly
  around a clash's actual intersection geometry, across both the host model and every
  linked model, regardless of how large either clashing element is (e.g. a small pipe
  clashing a large floor slab). Sized from the real overlap solid the detection engine
  already computes to confirm the clash, not the two elements' full extents — an earlier
  attempt at this (bundled into the Isolate toggle) was reverted after live testing found
  it barely cropped anything when one element dwarfed the other (tickets 1018, 1019).
- Both elements' Revit Element IDs now shown in the clash list, so a specific clashing
  element can be referenced precisely — e.g. telling a contractor exactly which pipe to
  move — without a separate lookup in Revit (1019).
- CODEOWNERS and a CI workflow that syntax-checks every `script.py` change against
  Python 2.7 (IronPython's baseline) on each pull request.

### Changed
- "Isolate current clash" reverts to its original, host-side-only scope (ticket 1009) —
  link-side focus now lives entirely in the new, independent Section Box toggle above,
  so either can be used without the other.

### Known limitations (updated from v0.5.0)
- The link-side element of a clash still can't be *isolated* by identity (a Revit API
  ceiling) — Select still highlights it, and Section Box now additionally crops the view
  down to the clash region in both models, which was the practical need this limitation
  was blocking.

## [v0.5.0] - 2026-09-04

First tagged release — the point-in-time snapshot of everything built and
verified before formal versioning started.

### Added
- Clash detection between the host model and selected linked models, using a
  manual bbox-prefilter + link-transform + solid-intersection pipeline
  (tickets 1001, 1007).
- Scoped run setup: pick categories and loaded links before running (1002).
- Navigable clash list with next/previous stepping (1003).
- Camera auto-fly-to-clash on selection (1004, hardened across three rounds
  for the shared ExternalEvent bridge).
- Colorize-by-category-pair, host-side elements only (1005), later made
  order-independent with hash-derived colors so the same pairing always
  renders identically regardless of which file is open as host (1008).
- "Isolate current clash" toggle, always paired with Select since the
  link-side element can't itself be isolated (1009).
- Per-row color swatches (legend) in the clash list (1010).
- Packaged as a pyRevit extension (1006).
- Category picker now requires real solid geometry on an instance, not
  merely its existence — Project Information/Lines no longer appear;
  genuinely absent categories (e.g. no Doors in a given model) correctly
  stay absent (1013).

### Fixed
- A previously-undocumented IronPython/pyRevit engine behavior: any function
  reached through a .NET delegate/interface-dispatch boundary (WPF event
  handlers, the ExternalEvent bridge) loses access to its module's real
  global namespace. Root-caused and fixed across tickets 1011, 1012, and a
  follow-up hotfix for a two-hop closure case in camera fly-to.

### Known limitations (explicitly out of scope for now)
- No tolerance/near-miss detection — hard clashes only.
- No CSV/Excel export.
- The link-side element of a clash can be Selected but not Isolated (a
  Revit API ceiling, not a bug) — evaluated 2026-09-04, accepted as-is.

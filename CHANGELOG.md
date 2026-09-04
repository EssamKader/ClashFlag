# Changelog

All notable changes to ClashFlag are recorded here, one entry per tagged release.
A version number here is a **deploy gate**: it marks a point that's been reviewed
and verified, not just merged. See `tickets/` for the full paper trail behind
every line below.

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

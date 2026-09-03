# Spec: ClashFlag — clash flagging tool for Revit models + linked models

Source: [tickets/0001-wayfinder-map.md](../tickets/0001-wayfinder-map.md) (all decisions resolved)

## Locked decisions carried in from Wayfinder
- Detection: manual transform pipeline (0002, revised after Phase 7 review of ticket
  1001 found the native cross-document check couldn't be verified to apply the
  link's transform) — bbox pre-filter, then `SolidUtils.CreateTransformed` using
  `RevitLinkInstance.GetTotalTransform()` on linked geometry, then solid
  intersection on surviving candidate pairs. Native `PerformInterferenceCheck`
  remains fine for host-vs-host category checks. No tolerance/near-miss in v1.
- Scope: user picks categories + which loaded links to include, per run (0003).
- UI: interactive clash list with up/down navigation, camera auto-fly-to-clash on selection, optional colorize-by-category (0005).
- Delivery vehicle: **pyRevit pushbutton + modeless WPF window** — assumed default per your pyRevit-first toolchain; flag if you want the C# `IDockablePane` route instead.
- Performance validation: deferred to first real implementation pass against a live federated model (0006).
- Tool name: `ClashFlag` (0007).

## User stories

**US-1 — Scoped run setup**
As a BIM engineer, I want to pick which categories and which loaded linked models are checked before running, so that I control clash scope per run instead of always checking everything.

**US-2 — Fast, reliable detection**
As a BIM engineer, I want clash detection across the host model and my selected links to be geometrically correct — explicitly accounting for each link's placement transform — so that I don't get missed or phantom clashes because of how a link happens to be positioned. (Revised after Phase 7 review: uses a bbox pre-filter + explicit link-transform + solid intersection pipeline for the cross-document case, rather than trusting the native check to handle link transforms automatically.)

**US-3 — Navigable clash list**
As a BIM engineer, I want all detected clashes to appear in a list I can step through one at a time (next/previous), so that I can review every clash methodically without losing track of where I am.

**US-4 — Camera auto-navigation**
As a BIM engineer, I want the 3D view to automatically reframe on the two clashing elements when I select a clash from the list, so that I don't have to manually hunt for and zoom to each clash location.

**US-5 — Colorize by category**
As a BIM engineer, I want an option to color-code the host-side clashing elements by their category/discipline pair (e.g. MEP-vs-Structural vs. MEP-vs-MEP) directly in the view, so that I can visually triage clash types at a glance across the whole model. (Revised after Phase 7 review of ticket 1005: Revit's API — and its own native UI — has no mechanism to override an individual linked element's graphics from the host view, so only the host-side element of each clash is colorized. This matches Revit's own capability ceiling, not a regression.)

**US-6 — Fits existing workflow**
As a BIM engineer, I want ClashFlag delivered as a pyRevit pushbutton, so that it installs and runs the same way as the rest of my pyRevit toolkit, with no separate compiled add-in to deploy.

## Explicitly out of scope for v1
- Tolerance / near-miss (soft) clash detection — only hard clashes via the native check.
- Export to Excel/CSV or integration into the Revit Warning Analysis System — the chosen UI is interactive-in-Revit, not report-based. Can be a follow-up ticket later if wanted.
- Performance tuning/spatial partitioning — deferred per US context above; native API assumed fast enough until proven otherwise on a real model.

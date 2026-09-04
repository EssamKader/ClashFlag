# Spec: ClashFlag — clash flagging tool for Revit models + linked models

Source: [tickets/0001-wayfinder-map.md](../tickets/0001-wayfinder-map.md) (all decisions resolved)

## Amendment (2026-09-04): Isolate, universal colorize, legend

Source: live-testing feedback, resolved via `/grill-with-docs` (grilling +
domain-modeling skills) instead of a new Wayfinder round — see
[CONTEXT.md](../CONTEXT.md) for the resulting glossary (**Select**,
**Isolate**, **Category Pair**, **Colorize**, **Legend**). Two real problems
drove this round:
1. Live testing surfaced that US-5's Category Pair key was accidentally
   ordered (`(host_category, link_category)`), so the same real-world pairing
   (e.g. Walls vs. Air Terminals) silently got a different color depending on
   which file happened to be open as host — not what US-5 ever intended.
   US-5 below is revised to fix this.
2. Two net-new capabilities were requested and grilled to a fully resolved
   design: an **Isolate** toggle (US-7) and a **Legend** (US-8, folded into
   the existing clash list from US-3).

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

**US-5 — Colorize by category (revised)**
As a BIM engineer, I want an option to color-code the host-side clashing elements by their category/discipline pair (e.g. MEP-vs-Structural vs. MEP-vs-MEP) directly in the view, so that I can visually triage clash types at a glance across the whole model. Only the host-side element of each clash is colorized (Revit's API and native UI have no mechanism to override an individual linked element's graphics from the host view — this matches Revit's own capability ceiling, not a regression). **Revised in the 2026-09-04 amendment:** the category pair is order-independent — Walls-vs-Air-Terminals colorizes identically no matter which file is open as host that day — and its color is produced by hashing the pair's name directly into a hue (fixed saturation/lightness for view readability) rather than cycling a small fixed palette, so the mapping is stable across every run and every model and never collides as new category pairs are discovered, with zero configuration or stored state. Independent of the new Isolate toggle (US-7): either can be on, off, or both.

**US-6 — Fits existing workflow**
As a BIM engineer, I want ClashFlag delivered as a pyRevit pushbutton, so that it installs and runs the same way as the rest of my pyRevit toolkit, with no separate compiled add-in to deploy.

**US-7 — Isolate the current clash** *(added 2026-09-04)*
As a BIM engineer, I want an opt-in "Isolate" toggle that, while on, hides everything in the view except the current clash's host-side element and highlights (selects) both the host and link elements of that clash, so that I can focus on one clash without visual clutter from the rest of the model. Moving to a different clash while Isolate is on replaces the isolation (never accumulates); the link-side element can't itself be isolated (same API ceiling as colorize), so Select always runs alongside Isolate to keep it findable. Turning Isolate off, or closing the clash list window while it's on, immediately restores the full view. Independent of Colorize (US-5).

**US-8 — Legend for the color mapping** *(added 2026-09-04)*
As a BIM engineer, I want a color swatch shown next to each entry in the clash list, so that I can see what each color means right where I'm using it, without a separate lookup.

## Explicitly out of scope for v1
- Tolerance / near-miss (soft) clash detection — only hard clashes via the native check.
- Export to Excel/CSV or integration into the Revit Warning Analysis System — the chosen UI is interactive-in-Revit, not report-based. Can be a follow-up ticket later if wanted.
- Performance tuning/spatial partitioning — deferred per US context above; native API assumed fast enough until proven otherwise on a real model.

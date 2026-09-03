label: wayfinder:decision
type: Grill

# Output format & delivery mechanism

## User's answer (verbatim intent)

A UI with the clash list as a dropdown/list; up/down navigation moves through
clashes one at a time; on each selection the 3D view camera auto-moves to frame
the two clashing elements (like Revit's native Interference Check "Show" button);
plus an option to colorize clashes by category (e.g. color-code by discipline
pair — MEP-vs-Structural, MEP-vs-MEP, etc.) directly in the view.

## Implications

This needs a persistent, interactive window — not a one-shot export. Two ways to
build it, both viable, to be locked at Phase 3 spec time:
- **pyRevit modeless WPF window** (Python + XAML) — fits the pyRevit-first default,
  no compiled add-in / reinstall cycle. Camera nav via `UIDocument.ShowElements()`
  or manual `View3D` orientation set from the clash's combined bounding box.
- **C# add-in with `IDockablePane`** — a true dockable panel like Revit's own
  panels, heavier to build/deploy (needs a compiled DLL + manifest), only worth it
  if a floating modeless window isn't good enough in practice.
- Colorize-by-category: `OverrideGraphicSettings` per element, keyed off the
  category pair of each clash, applied/cleared per active view via a Transaction.

## Status: resolved (user answer captured above; implementation vehicle to be locked in Phase 3)

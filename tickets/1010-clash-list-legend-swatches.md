label: ready-for-agent

# T-10: Legend swatches in the clash list

Implements US-8 (2026-09-04 amendment). A small color swatch next to each entry in the
existing clash list, showing the color its category pair would get from Colorize — so the
color-to-meaning mapping is visible right in the panel, with no separate lookup.

**Depends on:**
- T-3 (1003-clash-list-panel.md) — the list control being annotated.
- T-8 (1008-universal-category-pair-color.md) — needs the corrected, order-independent
  hash-based color function to look up each entry's swatch color; do not implement this
  ticket against the old ordered-tuple/fixed-palette function, since its output would be
  wrong/inconsistent with what Colorize actually applies.

**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — US-8.
**Context:** [CONTEXT.md](../CONTEXT.md) — Legend.

## Scope

- Each row in the clash list shows a small solid-color swatch (e.g. a fixed-size
  `Rectangle`/`Border` with `Background` bound or set to the pair's color) next to its
  existing label text, using the SAME color function T-8 ships (call it directly — do not
  duplicate or approximate the hash/HSL logic in the UI layer).
- The swatch reflects what a clash's category pair WOULD colorize to, regardless of
  whether the Colorize checkbox is currently on — it's a legend for the mapping itself,
  not a live indicator of applied overrides.
- No new toggle or interactivity — this is a static per-row visual addition to the
  existing list, not a separate control.
- Purely WPF/XAML + read-only color lookup — no Revit API calls, no `_revit_api_bridge`
  involvement, no Transaction.

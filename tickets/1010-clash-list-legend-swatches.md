label: done

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

## Implementation

Everything lives in `ClashFlag.extension\BIM Tools.tab\Clash Detection.panel\ClashFlag.pushbutton\script.py`'s
new "LEGEND SWATCHES (T-10 / ticket 1010)" section (placed directly above `ClashListWindow`, right
after `_open_clash_list_windows`), plus a small module-docstring comment update in
`clashflag_clash_list.xaml` — no XAML markup changes were needed (see "Approach chosen" below).

**Color source, called directly, not re-derived:** `_wpf_color_for_category_pair(clash_result)`
calls `_color_for_category_pair(_category_pair_key(clash_result))` — the exact two T-8 functions,
unmodified — and converts the resulting `Autodesk.Revit.DB.Color` (0-255 int R/G/B) into a
`System.Windows.Media.Color` via `MediaColor.FromRgb(revit_color.Red, revit_color.Green,
revit_color.Blue)`. These are two unrelated .NET types that happen to share the name `Color` (the
Revit one is already imported plain as `Color`; the WPF one is imported aliased as `MediaColor`
specifically to avoid that collision) — there is no implicit cast between them, so this is an
explicit byte-by-byte conversion, not a reinterpret. Because the swatch always calls this same
lookup regardless of `self.colorize_active`, it satisfies the ticket's "reflects what the pair
WOULD colorize to, regardless of whether Colorize is checked" requirement by construction — the
row-building code never reads `colorize_active`/`ColorizeCheckBox` at all.

**Approach chosen over a DataTemplate/binding-based ListBox:** this codebase has no
MVVM/`INotifyPropertyChanged` convention anywhere (`ClashResult`, `ScopeSelection`, etc. are all
plain, non-bindable Python objects), and `ScopePickerWindow` already establishes this file's own
pattern for "content not knowable until run time" UI — build the controls directly in Python code
(`_build_host_categories_ui`/`_build_one_link_block` build `CheckBox`/`TextBlock`/`StackPanel`
objects and `.Children.Add()` them) rather than declaring a static XAML template and binding to
it. `_build_clash_list_row(clash_result)` follows that exact same pattern: it builds a small
`Border` (the swatch, `Width`/`Height` 14, black `BorderBrush`, `Background` set to a
`SolidColorBrush` of the converted color) and the existing `describe()` `TextBlock`, side by side
in a horizontal `StackPanel`, and returns that `StackPanel` as the finished row visual.
`ClashListWindow.__init__`'s item-population loop now does
`self.ClashListBox.Items.Add(_build_clash_list_row(clash_result))` instead of the old
`self.ClashListBox.Items.Add(clash_result.describe())` — one line changed, no DataTemplate, no
binding, no new XAML controls to wire up.

**Why this can't break `SelectedIndex`-based navigation, verified two ways:**
1. By WPF's own documented `ItemsControl` contract: `Items` accepts any object, and when that
   object is itself a `UIElement` (a `StackPanel` is), it's used directly as that row's visual,
   wrapped in an implicitly-generated `ListBoxItem` container — exactly like a plain string item
   would be wrapped in one showing a default `TextBlock`. Nothing about how `ListBoxItem`
   generation, click-selection, or `SelectedIndex` works depends on what the underlying `Items`
   entry's *type* is.
2. By re-reading every consumer of `ClashListBox` in this file (`_on_list_selection_changed`,
   `_set_current_index`, `_current_clash_result`, `next_button_click`, `previous_button_click`) and
   confirming each one reads/writes only `ClashListBox.SelectedIndex` (an integer position) or
   `self.clash_results[self.current_index]` (a plain Python list indexed by that same integer) —
   none of them ever reads `ClashListBox.SelectedItem`, `Items[i].ToString()`, or anything else
   that would depend on an `Items` entry being a string. This is exactly why the class docstring's
   own "Navigation model" paragraph already states `self.current_index` (backed by
   `SelectedIndex`) as "the single source of truth" — the item's *content* was never part of that
   contract in the first place, so swapping a string item for a `StackPanel` item at the exact same
   index changes nothing downstream.
   Additionally spot-checked in a standalone, no-Revit-dependency harness (not committed —
   scratchpad-only) that (a) `_color_for_category_pair`'s output is unaffected by which order the
   two category names are passed to `_category_pair_key` (re-confirming T-8's order-independence
   guarantee is exactly what T-10's swatch relies on, not a fresh claim of its own), and (b) a
   minimal simulation of `_on_list_selection_changed`'s "compare `SelectedIndex` to
   `current_index`, then index into a separate list of `ClashResult`-like values" logic behaves
   identically whether the `Items` collection holds strings or arbitrary non-string row objects.

**Scope discipline:** no Revit API import, call, or `Transaction` was added anywhere in this
ticket's diff; `_revit_api_bridge` is never referenced from the new code; `ColorizeCheckBox`'s and
`IsolateCheckBox`'s Checked/Unchecked handlers, and `on_selection_changed`, were not modified — the
swatch has no interactivity of its own, matching the ticket's "static per-row visual addition, not
a separate control" scope line.

**Deployment:** the updated `script.py` and `clashflag_clash_list.xaml` were copied byte-for-byte
to the live pyRevit install at
`C:\Users\Essam.Lap\AppData\Roaming\pyRevit\Extensions\ClashFlag.extension\BIM Tools.tab\Clash Detection.panel\ClashFlag.pushbutton\`
and confirmed identical via `md5sum` against the sandbox copies (matching hashes for both files).

## Phase 7 review: PASS

Read the full diff directly. Swatch color is sourced by calling T-8's `_category_pair_key`/
`_color_for_category_pair` verbatim — no re-derived hash logic, so the legend can't drift out
of sync with what Colorize actually applies. Confirmed `Autodesk.Revit.DB.Color` (byte
Red/Green/Blue properties) and `System.Windows.Media.Color` are correctly kept distinct via the
`MediaColor` import alias, with an explicit `FromRgb` conversion rather than an assumed cast.
Re-checked every `ClashListBox` consumer (`_on_list_selection_changed`, `_set_current_index`,
`_current_clash_result`, nav button handlers) myself — all key off `SelectedIndex`/
`self.clash_results[self.current_index]`, never `SelectedItem` or item content, so swapping
string items for `StackPanel` items is safe by construction, matching the reviewer note already
in the ticket. Scope discipline held: no Revit API import, no `_revit_api_bridge` reference, no
`Transaction`, Colorize/Isolate handlers untouched. Independently re-ran `python -m py_compile`
(passed) and `md5sum` on both sandbox and live-deployed `script.py`/`clashflag_clash_list.xaml`
pairs — identical. Closing.

This closes all three tickets from the 2026-09-04 grilling amendment (1008, 1009, 1010). US-5
(revised), US-7, and US-8 are now fully implemented, reviewed, and deployed to the live pyRevit
install. Outstanding: ticket 1005's still-open `_revit_api_bridge` `UnboundNameException` — until
it's root-caused, both Colorize and (per 1009's review note) Isolate are likely non-functional in
the live tool despite being correctly implemented in source.

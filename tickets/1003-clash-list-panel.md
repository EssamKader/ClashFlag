label: done

# T-3: Navigable clash list panel

Implements US-3. Modeless WPF window listing every `InterferenceResult` from T-1
(element names/categories/ids of the clashing pair), with next/previous controls
(and direct list selection) to move a "current clash" pointer through the results.

**Depends on:** T-1 (1001-interference-check-runner.md) — needs real results to list.
**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — US-3.

## Implementation

Built against the actual current interface of `scripts/clashflag_runner.py` (post
1001 rework + 1002 scope picker), not the ticket's original `InterferenceResult`
wording — as of this ticket, `run_interference_check` iterates
`scope_selection.link_selections` and computes `clashing_pairs` (list of
`(host_element, link_element)` tuples) per selected link, with no flat
cross-link list existing anywhere. This ticket adds that flat list and a new
modeless window to display/navigate it.

**New data type (`ClashResult`, in `scripts/clashflag_runner.py`):** a small
class carrying `host_element`, `link_element`, and `link_name` (the display
name of the `RevitLinkInstance` the pair was found against — needed because
one run can check several distinct links, so a flattened list must say which
link each row came from). `.describe()` builds the one-line list-row text via
the existing `describe_element()` helper, reused for both sides so the panel
and the console output describe elements identically.

**Flat list assembly:** `run_interference_check` now also builds
`all_clash_results` (a `list[ClashResult]`) alongside its existing per-link
loop, appending one `ClashResult` per confirmed pair in the same order
`find_clashing_pairs` returns them, and returns that flat list at the end
(empty list, never `None`, when nothing clashed). **Kept, not removed:** the
existing per-link/per-pair `output.print_md` console reporting — it's grouped
per-link with candidate/skip counts and a per-link sub-total, which is a run
LOG, distinct in purpose from the flat list's role as UI-navigation STATE;
both are cheap to build from the same already-computed `clashing_pairs`, so
there was no reason to rip one out for the other.

**New modeless window (`ClashListWindow(forms.WPFWindow)`)** in the same file,
paired with a new sibling `scripts/clashflag_clash_list.xaml` (empty
`ListBox` populated from Python at construction, same "static XAML skeleton +
Python-built contents" convention `clashflag_scope_picker.xaml` already
established). Opened via `.Show()` (not `.ShowDialog()` like the T-2 scope
picker) specifically because, per US-4/ticket 1004 (camera fly-to — NOT
implemented by this ticket), the user needs to keep interacting with the
Revit view while this panel stays open; a modal window would block that. A
module-level `_open_clash_list_windows` list keeps the window object alive
against .NET GC once the script's `__main__` scope exits (Show() is
non-blocking, unlike the picker's ShowDialog()), with entries removed on the
window's `Closed` event.

**Navigation model:** `self.current_index` is the single source of truth.
Next/Previous buttons and direct `ListBox` row clicks both ultimately change
`ClashListBox.SelectedIndex`; `_on_list_selection_changed` is the *only* place
`current_index` is updated and the only place the extension hook fires — so
there is exactly one navigation code path regardless of how the user
triggered the change, per the ticket's "don't make Next/Previous the only way
to navigate" instruction. A `StatusText` label ("Clash N of M") and
enabled/disabled state on the Previous/Next buttons at the list boundaries
were added as a small UX addition beyond the ticket's literal ask.

**Extension hook for 1004/1005:** every time the current clash changes,
`ClashListWindow.on_selection_changed(self, clash_result, index)` is called
with the newly-current `ClashResult` (or `None`/`-1` if nothing is selected).
Its default implementation forwards to `self.selection_changed_callback` if
one has been set (a plain assignable callback attribute), so a later ticket
can hook in EITHER by setting that callback on an instance OR by subclassing
`ClashListWindow` and overriding `on_selection_changed` — both documented in
the class docstring. Ticket 1004 would read `clash_result.host_element` /
`.link_element` to reframe the view; ticket 1005 would read the same two
elements' categories to pick a colorize override. Neither is implemented
here — this ticket only provides the hook point.

**Wiring:** `scripts/clashflag_runner.py`'s `__main__` block now captures
`run_interference_check`'s return value and calls `show_clash_list(...)` only
when it's non-empty; a zero-clash run relies on the existing console "Total: 0
clash pair(s)" reporting instead of opening an empty panel, per instruction 5.

**Read-only:** no `Transaction` anywhere in this ticket's code — the window
only reads already-computed `ClashResult` values and manages its own UI
state (`current_index`, list selection, button enabled-state).

**Reviewer attention (no live Revit/pyRevit session in this sandbox to
verify against):**
- `forms.WPFWindow`'s modeless `.Show()` behavior, and whether pyRevit's
  IronPython/STA-thread setup for a `ShowDialog()`-based window (already
  proven working by the T-2 picker) carries over cleanly to a non-blocking
  `.Show()` window running alongside continued Revit interaction — this is
  the standard pattern for pyRevit modeless tool windows, but untested here.
- The `_open_clash_list_windows` GC-keepalive approach is a reasonable,
  commonly-used pattern for this exact problem, but hasn't been exercised
  against a real repeated-run/close/reopen cycle in an actual pyRevit
  session.
- `ClashListBox.SelectedIndex = clamped_index` not firing `SelectionChanged`
  when set to its own current value (relied on so Next/Previous no-op
  cleanly at the list boundaries) is standard WPF `Selector` behavior, but
  worth a quick smoke-test on first real run.

File verified with `ast.parse` after edits — no syntax errors introduced.

## Phase 7 review: PASS

Read the actual `ClashResult`/`ClashListWindow`/`show_clash_list` code and the new
XAML directly. Navigation logic genuinely funnels through one path
(`_on_list_selection_changed`), boundary clamping and button-enabled logic check
out, `ClashResult(element1, element2, link_name)` construction matches
`find_clashing_pairs`' `(host_element, link_element)` return order, and XAML
`x:Name`s/`Click` handlers match the Python side. The extension hook contract
(`on_selection_changed` / `selection_changed_callback`) is clean and well-documented
for 1004/1005 to consume. No new instances of the `.IntegerValue` deprecation note
beyond the ones already flagged. Closing.

**Closed.**

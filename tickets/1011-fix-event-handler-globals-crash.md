label: done

# T-11: Fix IronPython delegate-globals crash in WPF event handlers

Root-causes and fixes the live crash tracked as "Reopened" in
[tickets/1005-colorize-by-category.md](1005-colorize-by-category.md) (`_revit_api_bridge` is
not defined) and flagged as a shared risk in
[tickets/1009-isolate-current-clash.md](1009-isolate-current-clash.md)'s review. This is a
cross-cutting bug fix, not a new user story — no spec change.

## Root cause (found live, 2026-09-04, via Revit MCP reflection against the user's actual
running Revit 2024.3 session — not guessed)

`ClashListWindow` and `ScopePickerWindow` both subclass `forms.WPFWindow`, which ultimately
subclasses `System.Windows.Window` — a .NET type. IronPython must generate a real dynamic
.NET subtype (`IronPython.NewTypes.System.Windows.Window_29$30`, confirmed via
`instance.GetType()` on the live window) to satisfy that inheritance. Any Python method on
such a class that gets wired to a CLR event — an XAML `Checked=`/`Unchecked=`/`Click=`
attribute (resolved by `wpf.LoadComponent`), OR a plain `+=` registration in Python code
(`self.ClashListBox.SelectionChanged += self._on_list_selection_changed`) — ends up invoked
through a genuine .NET delegate. Reflecting on that delegate's target directly (via
`EventHandlersStore`/`GetRoutedEventHandlers`, since these are WPF routed events) shows its
`Target` is a 3-element `object[]` closure array whose first element is the real
`IronPython.Runtime.Method` (`__func__`/`__self__` intact - `self` really is the right
instance). But that method's underlying `PythonFunction.func_globals` is a **freshly
initialized 5-key `PythonDictionary`** (`__builtins__`, `__file__`, `__name__`, `__doc__`,
`__deref`) - NOT the real module's globals dict (which has ~200+ names, everything the
script imports and defines at top level).

**Verified this affects every delegate-wired method checked, not just colorize's:**
`colorize_checkbox_checked`, `isolate_checkbox_checked`, `isolate_checkbox_unchecked`,
`next_button_click`, `previous_button_click`, and `_on_list_selection_changed` (registered
via plain `+=`, not even an XAML string) ALL show the identical 5-key globals when reflected
on live. Next/Previous/selection-changed only *appear* to work because their own bodies
never reference a bare module-level name (only `self.` attribute/method access, which is
unaffected - `self` is an ordinary parameter, not a global). Colorize and Isolate's handlers
directly reference `_revit_api_bridge`, `doc`, `output`, `apply_colorize_overrides`,
`clear_colorize_overrides`, `_isolate_host_element`, `_exit_temporary_isolate`,
`select_clash_pair`, and (in the exception branch) `forms` — every one of those is unbound
in this scope, so the first one evaluated throws `IronPython.Runtime.UnboundNameException`.

**Also found the identical latent bug in `ScopePickerWindow.run_button_click`** (also
XAML `Click=`-wired): its two validation-failure branches call bare `forms.alert(...)` -
currently dormant (only reachable if the user clicks Run with no host category, or no
link+category, selected) but a certain crash instead of the intended validation message
if it ever is hit.

**Why nested closures don't save you:** `colorize_checkbox_checked`'s inner `_apply`/`_clear`
functions inherit their enclosing method's SAME broken `func_globals` (a Python nested
function's globals are fixed to its lexically enclosing function's globals at compile time,
regardless of how/when it's later called) - so fixing only the OUTER
`_revit_api_bridge.raise_action(...)` call is not enough; the queued closure's own body
(`doc.ActiveView`, `apply_colorize_overrides(...)`, `output.print_md(...)`, etc.) would still
crash the moment it actually runs.

**Why `__init__` is NOT affected (and is therefore the fix's foundation):** `__init__` is
never wired to a CLR event - it's invoked through an ordinary Python constructor call
(`ClashListWindow(xaml_path, results, callback)` from `show_clash_list`, a plain top-level
function). This is consistent with the live evidence (the clash list itself, including T-10's
per-row legend swatches built by calling the bare module-level `_build_clash_list_row`
function from inside `__init__`'s item-population loop, renders correctly - if `__init__`
were affected, the window would fail to even open).

## The fix

In each affected window's `__init__` (unaffected, correct globals), capture every
module-level object its delegate-wired methods need as **instance attributes** -
`self.<x> = <x>` reads `<x>` correctly here, once, since `__init__` has the real globals.
Then, in every delegate-wired method (and any closure nested inside one), replace every bare
reference to one of those names with a **local variable assigned from `self.<x>` at the top
of the method** (e.g. `host_doc = self._doc`) - nested closures capture that local via
Python's normal enclosing-scope/cell mechanism (`LOAD_DEREF`), which is unrelated to global
lookup and unaffected by the broken `func_globals`. Do NOT reference `self._doc` (or any
`self.` attribute) directly from inside a nested closure if it's simpler to capture it into a
local first for clarity - either works (both go through `self`, not a bare name), but match
existing style (`_apply_isolate_for_clash` already captures `self.isolate_view_id` into a
local `reuse_view_id` before defining its nested closure, for a different but related
reason - follow that precedent).

**In `ClashListWindow.__init__`, add (alongside the existing state fields):**
```python
self._doc = doc
self._uidoc = uidoc
self._output = output
self._forms = forms
self._bridge = _revit_api_bridge
self._apply_colorize_overrides_fn = apply_colorize_overrides
self._clear_colorize_overrides_fn = clear_colorize_overrides
self._isolate_host_element_fn = _isolate_host_element
self._exit_temporary_isolate_fn = _exit_temporary_isolate
self._select_clash_pair_fn = select_clash_pair
```
Then rewrite `colorize_checkbox_checked`, `_clear_colorize_if_active`, `isolate_checkbox_checked`
(via `_apply_isolate_for_clash`), and `_clear_isolate_if_active` so every bare reference to
`doc`, `uidoc`, `output`, `forms`, `_revit_api_bridge`, `apply_colorize_overrides`,
`clear_colorize_overrides`, `_isolate_host_element`, `_exit_temporary_isolate`, and
`select_clash_pair` inside those methods (including their nested `_apply`/`_clear` closures)
goes through one of the `self.*` attributes above instead - captured into a local at the top
of the outer method, exactly like `_apply_isolate_for_clash` already does for
`self.isolate_view_id`/`reuse_view_id`.

**In `ScopePickerWindow.__init__`, add:**
```python
self._forms = forms
```
and rewrite `run_button_click`'s two `forms.alert(...)` calls to use a local captured from
`self._forms` at the top of the method.

**Do not touch** `next_button_click`, `previous_button_click`, `_on_list_selection_changed`,
`_set_current_index`, `_update_status_and_buttons`, `_current_clash_result`,
`_fire_selection_hook`, `on_selection_changed`, `close_button_click`, `cancel_button_click`,
`_build_host_categories_ui`, `_build_links_ui`, `_build_one_link_block` - none of them
reference a bare module-level name (verified by reading each one directly), so none of them
need this treatment; do not add unnecessary `self.*` captures to them.

**Verify, don't guess (this project's standing rule)** - after the fix, if a live Revit
session is available, reflect on the live bound methods again (same technique used to
diagnose this: `EventHandlersStore.GetRoutedEventHandlers` → delegate `Target` → `object[]`
→ `IronPython.Runtime.Method.__func__` → `PythonFunction.func_globals`) is NOT expected to
show a different count (the fix doesn't change `func_globals` - it works around it) - instead
verify by actually clicking Colorize/Isolate live (or, if no live session, by tracing through
the rewritten code by hand) and confirming no `UnboundNameException` is thrown and the
correct behavior (overrides applied / view isolated) occurs.

## Implementation

No live Revit session was available in this session, so this was verified by hand-tracing
every rewritten method (below) plus a Python AST walk over the two affected classes (see
"AST verification" below) rather than by live reflection - flagged for the next live-testing
pass to confirm by actually clicking Colorize/Isolate, per the ticket's own "verify, don't
guess" instruction.

File changed: `ClashFlag.extension\BIM Tools.tab\Clash Detection.panel\ClashFlag.pushbutton\script.py`

**`ClashListWindow.__init__`** - added the ten `self.*` captures exactly as specified in the
ticket (`self._doc`, `self._uidoc`, `self._output`, `self._forms`, `self._bridge`,
`self._apply_colorize_overrides_fn`, `self._clear_colorize_overrides_fn`,
`self._isolate_host_element_fn`, `self._exit_temporary_isolate_fn`,
`self._select_clash_pair_fn`), placed right after the existing `isolate_view_id` state field
and before the `ClashListBox.Items` population loop.

**`ClashListWindow.colorize_checkbox_checked`** - added five locals at the top of the outer
method (`host_doc`, `apply_overrides_fn`, `show_forms`, `print_output`, `bridge`, each read
from the matching `self.*`), then rewrote every bare reference inside the nested `_apply`
closure (`doc.ActiveView` → `host_doc.ActiveView`; `apply_colorize_overrides(...)` →
`apply_overrides_fn(...)`; `forms.alert(...)` → `show_forms.alert(...)`;
`output.print_md(...)` → `print_output.print_md(...)`) and the outer method's own
`_revit_api_bridge.raise_action(_apply)` → `bridge.raise_action(_apply)`.

**`ClashListWindow._clear_colorize_if_active`** - added `host_doc`, `print_output`,
`clear_overrides_fn`, `bridge` locals at the top (after the early-return guard, before the
state-reset lines that were already there), rewrote the nested `_clear` closure's
`doc.GetElement(...)` → `host_doc.GetElement(...)`, `clear_colorize_overrides(...)` →
`clear_overrides_fn(...)`, both `output.print_md(...)` calls → `print_output.print_md(...)`,
and the outer `_revit_api_bridge.raise_action(_clear)` → `bridge.raise_action(_clear)`.

**`ClashListWindow._apply_isolate_for_clash`** - added `host_doc`, `host_uidoc`,
`print_output`, `isolate_host_element_fn`, `select_clash_pair_fn`, `bridge` locals at the top
(alongside the pre-existing `reuse_view_id`/`is_first_apply_in_session` capture, which was
left untouched as the style precedent), then rewrote every bare reference inside the nested
`_apply` closure: both `doc.GetElement(...)`/`doc.ActiveView` → `host_doc.*`,
`_isolate_host_element(...)` → `isolate_host_element_fn(...)`, all three
`output.print_md(...)` calls → `print_output.print_md(...)`, `select_clash_pair(clash_result,
doc, uidoc)` → `select_clash_pair_fn(clash_result, host_doc, host_uidoc)`, and the outer
`_revit_api_bridge.raise_action(_apply)` → `bridge.raise_action(_apply)`.
`isolate_checkbox_checked` itself was left untouched - its own body never references a bare
module-level name (only `self.*` and a call into `_apply_isolate_for_clash`), matching the
ticket's "via `_apply_isolate_for_clash`" phrasing.

**`ClashListWindow._clear_isolate_if_active`** - added `host_doc`, `print_output`,
`exit_temporary_isolate_fn`, `bridge` locals at the top (after the early-return guard),
rewrote the nested `_clear` closure's `doc.GetElement(...)` → `host_doc.GetElement(...)`,
`_exit_temporary_isolate(...)` → `exit_temporary_isolate_fn(...)`, both `output.print_md(...)`
calls → `print_output.print_md(...)`, and the outer `_revit_api_bridge.raise_action(_clear)`
→ `bridge.raise_action(_clear)`.

**`ScopePickerWindow.__init__`** - added `self._forms = forms`, placed right after the
existing `self.result = None` state field and before `_build_host_categories_ui()`/
`_build_links_ui()` are called.

**`ScopePickerWindow.run_button_click`** - added `show_forms = self._forms` at the top of the
method, then rewrote both `forms.alert(...)` calls (the "pick at least one host category"
and "pick at least one loaded link..." validation branches) to `show_forms.alert(...)`.

**Not touched** (confirmed by reading each - no bare module-level name reference in any of
them): `colorize_checkbox_unchecked` and `isolate_checkbox_unchecked` (each only calls
`self._clear_colorize_if_active()` / `self._clear_isolate_if_active()` - the fix lives in the
callee, not the caller), plus every method the ticket explicitly lists as unaffected
(`next_button_click`, `previous_button_click`, `_on_list_selection_changed`,
`_set_current_index`, `_update_status_and_buttons`, `_current_clash_result`,
`_fire_selection_hook`, `on_selection_changed`, `close_button_click`, `cancel_button_click`,
`_build_host_categories_ui`, `_build_links_ui`, `_build_one_link_block`).

**Also deliberately left untouched, and flagged for reviewer attention**: `show_clash_list`'s
`_on_window_closed` closure (registered via `window.Closed += _on_window_closed`) references
the bare module-level `_open_clash_list_windows` list, and `_build_one_link_block`'s
`_on_link_toggled` closure is likewise registered via `+=`
(`link_checkbox.Checked += _on_link_toggled`) - both are, on the surface, the same "closure
wired to a CLR event" shape the root-cause writeup describes. They were NOT added to this
fix because the diagnosed root cause is specific to `IronPython.Runtime.Method` (a *bound
method* of the dynamically-generated `Window`-derived subtype, per the live reflection
evidence: `Target` is a 3-element array whose first element is an `IronPython.Runtime.Method`
with intact `__self__`) - `_on_window_closed` and `_on_link_toggled` are plain
(non-method) `PythonFunction` closures defined inside ordinary top-level functions
(`show_clash_list`, `_build_one_link_block`), never bound to `self` or wrapped as an
`IronPython.Runtime.Method`, so it is not established that the same globals-corruption
mechanism applies to them. This is consistent with the ticket's own affected-method list
(neither closure was reflected on or listed as affected) and with these two closures
apparently working correctly in the live-testing rounds referenced elsewhere in this file
(window-close cleanup and link-checkbox enable/disable have not been reported broken). Left
as a genuine open question rather than guessed either way - a reviewer with live reflection
access should check `window.Closed`'s and `link_checkbox.Checked`'s registered delegate
targets the same way `EventHandlersStore.GetRoutedEventHandlers` was used for this ticket's
diagnosis, to confirm plain-function closures really are unaffected before ruling this out
for good.

**Verification performed:**
- `python -m py_compile script.py` - passed with no output (syntax-valid).
- A Python `ast`-based scan of every `ast.Name`/`ast.Attribute` node inside the
  `ScopePickerWindow` and `ClashListWindow` `ClassDef` bodies, checked against the ten
  affected names: the only remaining bare (non-`self.`) references are (a) each class's own
  `class Foo(forms.WPFWindow):` statement (evaluated once at module-import time, not through
  a CLR delegate) and (b) the `forms.WPFWindow.__init__(self, xaml_file_path)` call and the
  ten new `self._x = x` assignment lines inside `__init__` itself (the one method confirmed
  NOT delegate-wired, per the ticket's own root-cause section) - i.e. no bare reference to
  any of the ten names remains in any delegate-wired method or nested closure.
- Hand-traced every rewritten method's nested closure to confirm each free variable it uses
  resolves to an enclosing-scope local (captured from `self.*` in the outer method), not a
  bare global.
- Copied the identical file to the live pyRevit install
  (`C:\Users\Essam.Lap\AppData\Roaming\pyRevit\Extensions\ClashFlag.extension\BIM Tools.tab\Clash Detection.panel\ClashFlag.pushbutton\script.py`)
  and confirmed both files are byte-identical via `md5sum`
  (`ff4f850110843b919f57c22488510deb` on both).
- Not done (no live Revit session in this sandbox): actually clicking Colorize/Isolate live,
  or re-reflecting on the live bound delegates to confirm the `UnboundNameException` no
  longer fires - left for the next live-testing pass, per the ticket's own "verify, don't
  guess" instruction.

## Phase 7 review: PASS

Read the full diff directly. Every bare reference to the ten affected names
(`_revit_api_bridge`, `doc`, `uidoc`, `output`, `forms`, `apply_colorize_overrides`,
`clear_colorize_overrides`, `_isolate_host_element`, `_exit_temporary_isolate`,
`select_clash_pair`) inside `colorize_checkbox_checked`, `_clear_colorize_if_active`,
`_apply_isolate_for_clash`, `_clear_isolate_if_active`, and `run_button_click` (including
every nested `_apply`/`_clear` closure) is now routed through a `self.*` attribute captured
in the owning window's `__init__`. Independently re-scanned both class bodies with a script
that flags any bare occurrence of these names outside `__init__`/the class declaration line
(both unaffected, per the root-cause diagnosis) — the only remaining hits are inside
docstrings/comments (inert) or are substring false-positives on the new local variable names
(`select_clash_pair_fn`, etc.) — zero genuine bare references left.

Investigated the implementer's flagged open question (whether plain nested closures wired via
`+=` — `show_clash_list`'s `Closed` handler, `_build_one_link_block`'s `_on_link_toggled` —
share this bug) live: `_on_list_selection_changed`'s delegate target resolved to an
`IronPython.Runtime.Method` (a bound method of the NewType), which is what has broken
globals. `_on_window_closed` is a plain closure lexically nested inside `show_clash_list` (a
normal top-level function, never itself delegate-bound), and `_on_link_toggled` doesn't
reference any of the ten names regardless — neither is a practical risk. Attempted to confirm
`Window.Closed`'s handler globals directly via `EventHandlersStore` reflection but its backing
key (`Window.EVENT_CLOSED`) isn't a plain `EventPrivateKey`-compatible call in this WPF
version, so that specific reflection didn't resolve — noting as an accepted gap rather than
blocking on it, since the closure-nesting reasoning independently explains why it's safe.

Independently re-verified deployment: `python -m py_compile` clean, and `md5sum` on both the
sandbox and live-deployed `script.py` — identical (`ff4f850110843b919f57c22488510deb`).
Closing.

**Live re-verification still needed**: the user's currently-open Revit session loaded the OLD
script.py before this fix was deployed — pyRevit needs a reload (or the ClashFlag window
closed and the tool re-run from the ribbon) to pick up the new file before Colorize/Isolate
can be retested.

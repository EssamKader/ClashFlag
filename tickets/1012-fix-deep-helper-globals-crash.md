label: done

# T-12: Fix the SAME globals crash one layer deeper - the whole helper call graph

Ticket 1011 fixed the *immediate* body of `ClashListWindow`'s delegate-wired methods
(`colorize_checkbox_checked`, `_clear_colorize_if_active`, `_apply_isolate_for_clash`,
`_clear_isolate_if_active`) by routing their own bare module-level references through
`self.*` attributes. **Live retesting after 1011 deployed shows the bug goes deeper than
that fix reached**, in the same live Revit 2024.3 session:

- Isolate now throws: `ClashFlag: could not isolate this clash's host element: name 'List'
  is not defined` - this is `IsolateElementsTemporary`'s call site inside
  `_isolate_host_element` itself.
- Colorize now throws: `ClashFlag could not apply colorize overrides: name
  '_build_category_pair_color_map' is not defined` - inside `apply_colorize_overrides`
  itself.

Both `_isolate_host_element` and `apply_colorize_overrides` are **plain top-level
functions, never part of any class, never themselves wired to a delegate** - yet they are
STILL hitting the identical `IronPython.Runtime.UnboundNameException` on their OWN bare
module-level references, when called (indirectly, via `self._isolate_host_element_fn(...)`/
`self._apply_colorize_overrides_fn(...)`) from inside a closure that itself runs inside
`_RevitApiBridge.Execute()` (the `IExternalEventHandler.Execute` callback Revit invokes).

## Revised understanding of the root cause

1011's write-up described the bug as a property of *individual delegate-bound methods*.
Live re-testing shows that's incomplete: **the broken/near-empty scope appears to apply to
the ENTIRE call stack for as long as it originated from a .NET-to-Python boundary crossing**
(a WPF delegate invocation, OR `_RevitApiBridge.Execute()`'s own interface-dispatch
invocation from Revit) - not just to the one function IronPython directly invoked across
that boundary. Once inside such a call, EVERY subsequent bare (module-level) name lookup,
in EVERY function called from there, hits the same near-empty scope - regardless of
whether that function is itself a class method, a NewType-related method, or a completely
ordinary top-level function that has never been anywhere near a delegate. Only genuine
Python builtins (`Exception`, `None`, `len`, `bool`, string methods, etc. - resolved via
the `__builtins__` fallback, which IS present and intact in the broken scope) and
parameters/locals/`self.` attribute access are unaffected.

This means 1011's fix pattern (capture in `__init__`, read via `self.*`/a local) was
necessary but insufficient: it only covers the OUTER method's own body. Every function
transitively called from one of the four `_revit_api_bridge`-queued closures - and, it turns
out, from ticket 1004's camera-fly-to closure too, which routes through the exact same
`Execute()` path - needs the SAME treatment.

## Full affected call graph (traced by reading every function's body directly - not guessed)

Reachable from `colorize_checkbox_checked`'s `_apply` / `_clear_colorize_if_active`'s
`_clear` (already partly fixed by 1011 at the outer layer):
- `apply_colorize_overrides(clash_results, host_doc, active_view)` - bare:
  `_build_category_pair_color_map`, `_find_solid_fill_pattern_id`, `Transaction`,
  `_category_pair_key`, `_colorize_settings_for`.
- `clear_colorize_overrides(host_doc, view, previous_overrides)` - bare: `Transaction`,
  `ElementId`.
- `_build_category_pair_color_map(clash_results)` - bare: `_category_pair_key`,
  `_color_for_category_pair`.
- `_category_pair_key(clash_result)` - bare: `_category_name_for_colorize` (itself has no
  bare module references - safe as-is, no change needed).
- `_color_for_category_pair(pair_key)` - bare: `_stable_hash_int`, `colorsys`,
  `_CATEGORY_PAIR_LIGHTNESS`, `_CATEGORY_PAIR_SATURATION`, `Color`.
- `_stable_hash_int(text)` - bare: `hashlib`.
- `_find_solid_fill_pattern_id(host_doc)` - bare: `FilteredElementCollector`,
  `FillPatternElement`.
- `_colorize_settings_for(color, solid_fill_pattern_id)` - bare: `OverrideGraphicSettings`.

Reachable from `_apply_isolate_for_clash`'s `_apply` / `_clear_isolate_if_active`'s `_clear`
(already partly fixed by 1011 at the outer layer):
- `_isolate_host_element(host_doc, view, host_element_id)` - bare: `List`, `ElementId`,
  `Transaction`.
- `_exit_temporary_isolate(host_doc, view)` - bare: `Transaction`, `TemporaryViewMode`.
- `select_clash_pair(clash_result, host_doc, host_uidoc)` - bare:
  `resolve_link_instance_by_id`, `ClashFlagError`, `output`, `Reference`, `List`.
- `resolve_link_instance_by_id(host_doc, link_element_id)` - bare: `RevitLinkInstance`,
  `ClashFlagError`.

Reachable from ticket 1004's camera-fly-to closure (queued the same way, in `__main__` -
**not yet reported broken by the user, but reads exactly the same way; verify rather than
assume it's still fine**):
- `reframe_active_view_on_clash(clash_result, host_doc, host_uidoc)` - bare:
  `select_clash_pair` (see above - already in the graph), `output`, `View3D`,
  `ClashFlagError`, `_combined_host_space_bounding_box`, `_pad_bounding_box`,
  `CAMERA_REFRAME_PADDING_FRACTION`.
- `_combined_host_space_bounding_box(clash_result, host_doc, active_view)` - bare:
  `resolve_link_instance_by_id` (already in the graph), `resolve_link_document`,
  `_transform_all_corners`, `XYZ`.
- `resolve_link_document(link_instance)` - bare: `ClashFlagError` (already in the graph).
- `_pad_bounding_box(box_min, box_max, fraction)` - bare: `XYZ`.
- `_transform_all_corners(local_min, local_max, local_to_target_transform)` - bare: `XYZ`.
  **Careful: this function is ALSO called from `_outline_for_solid`, part of the detection
  pipeline (`run_interference_check`) - a call site that runs in a perfectly valid/safe
  context (plain `__main__` execution, never through the bridge) and is NOT broken today.**
  Add the `deps` parameter to this function anyway (so both call sites use the same
  signature) and update `_outline_for_solid`'s call site to pass `deps` too - this is a
  no-risk mechanical change there (it already has correct access to every real module name;
  passing `deps` explicitly instead of relying on that doesn't change its behavior, it just
  keeps one function signature instead of forking two copies of the same logic).

**Before writing any code, grep the whole file for every remaining bare reference to each
name listed above (and to any name this list missed) to make sure this enumeration is
complete** - do not trust this list blindly, verify it the same way it was built (reading
each function's actual body). In particular, double-check `_outline_for_solid` and anything
else that calls `_transform_all_corners` to make sure every call site gets updated
consistently once it takes `deps`.

## The fix - a single shared "deps" container, threaded as one extra parameter

Do NOT repeat 1011's per-name individual-parameter/self-attribute pattern here - with this
many functions and this many distinct names, that would mean threading 5-8 individual
parameters through over a dozen call sites. Instead:

1. Near the top of the module (after all the real definitions exist, e.g. right before
   `_revit_api_bridge = _RevitApiBridge()` or in a clearly-labeled new section), build ONE
   plain container object holding every name any function in the graph above needs - e.g.:
   ```python
   class _HelperDeps(object):
       pass

   _helper_deps = _HelperDeps()
   _helper_deps.Transaction = Transaction
   _helper_deps.ElementId = ElementId
   _helper_deps.List = List
   _helper_deps.Reference = Reference
   _helper_deps.TemporaryViewMode = TemporaryViewMode
   _helper_deps.FilteredElementCollector = FilteredElementCollector
   _helper_deps.FillPatternElement = FillPatternElement
   _helper_deps.OverrideGraphicSettings = OverrideGraphicSettings
   _helper_deps.Color = Color
   _helper_deps.View3D = View3D
   _helper_deps.RevitLinkInstance = RevitLinkInstance
   _helper_deps.colorsys = colorsys
   _helper_deps.hashlib = hashlib
   _helper_deps.output = output
   _helper_deps.ClashFlagError = ClashFlagError
   _helper_deps.CAMERA_REFRAME_PADDING_FRACTION = CAMERA_REFRAME_PADDING_FRACTION
   _helper_deps.XYZ = XYZ
   _helper_deps.resolve_link_instance_by_id = resolve_link_instance_by_id
   _helper_deps.resolve_link_document = resolve_link_document
   ```
   (this list is a starting point built from the "Full affected call graph" section above -
   cross-check it against that section and add anything missing, e.g. if grepping turns up
   another bare name this write-up didn't catch)
   (This assignment runs at MODULE LOAD time, in the normal top-to-bottom script execution -
   NOT inside any class or delegate - so every bare name on the right-hand side resolves
   correctly here, exactly like `__init__`/`show_clash_list` do for the same reason in
   1011's fix.) This must be built AFTER every name it references already exists (i.e.,
   after all the relevant `def`/`class`/`import` statements it depends on), and BEFORE the
   `ClashListWindow`/`ScopePickerWindow` classes are defined isn't required, but it must
   exist before `__init__` tries to capture it.
2. Add `self._helper_deps = _helper_deps` to `ClashListWindow.__init__` (alongside 1011's
   other captures), and thread `deps` as one extra parameter into every closure/local
   capture in `colorize_checkbox_checked`/`_clear_colorize_if_active`/
   `_apply_isolate_for_clash`/`_clear_isolate_if_active` (a local `deps = self._helper_deps`
   at the top, same pattern as 1011's other locals).
3. Also thread it into `__main__`'s camera-fly-to closure (wherever `_on_clash_selection_changed`
   /the queued `_reframe`-style closure is defined) so `reframe_active_view_on_clash` gets
   it too - that closure is a plain top-level construct with correct globals already (it's
   not inside any class), so it can read `_helper_deps` bare directly; no `self.` needed
   there, just pass it as an argument to `reframe_active_view_on_clash`.
4. Change EVERY function listed in the "Full affected call graph" above to accept `deps` as
   an additional parameter (convention: last positional parameter, named `deps`), and
   rewrite its body to read `deps.Xxx` instead of the bare `Xxx` for every name in its own
   list above. Where one of these functions calls ANOTHER one from the list (e.g.
   `apply_colorize_overrides` calling `_build_category_pair_color_map`,
   `_category_pair_key`, `_colorize_settings_for`; `select_clash_pair` being called from
   `reframe_active_view_on_clash`), pass `deps` through to that call too - it must
   propagate all the way down the graph, not just at the top level.
5. Update every call site of every changed function's signature (both inside this file and
   nowhere else - these are all private/internal to `script.py`) to pass `deps` through.
6. `_category_name_for_colorize` needs NO change (confirmed no bare module references in
   its body) - do not add an unnecessary `deps` parameter to it or anything else not in the
   graph above.

**Verify, don't guess:** after the change, re-derive the full call graph one more time by
grep and by reading, and confirm ZERO bare references remain to any of the names in
`_HelperDeps` inside any function in the graph. Since a live Revit session may be available,
prefer actually testing (ask for/perform a live retest of Colorize, Isolate, AND camera
fly-to/navigation - not just the two features that have visibly errored so far) over purely
static verification.

## Implementation

No live Revit session was available to this agent either - verification below is static
(re-grepping the whole file after every edit, plus `python -m py_compile`) exactly as the
ticket allows for when a live session isn't available. The user is retesting live separately.

### `_HelperDeps` container

Added a new "HELPER DEPS CONTAINER (T-12 / ticket 1012)" section in `script.py`, placed
right after the "ISOLATE CURRENT CLASH" section and before `_open_clash_list_windows = []`
(later than the ticket's own suggested "right before `_revit_api_bridge`" spot, because
several needed names - `_color_for_category_pair`, `_build_category_pair_color_map`,
`_find_solid_fill_pattern_id`, `_colorize_settings_for`, `_category_pair_key`,
`_category_name_for_colorize` - are defined in the later "COLORIZE BY CATEGORY" section,
and the container must be built after every name it references already exists).

`_helper_deps` (a `_HelperDeps()` instance) holds: `Transaction`, `ElementId`, `List`,
`Reference`, `TemporaryViewMode`, `FilteredElementCollector`, `FillPatternElement`,
`OverrideGraphicSettings`, `Color`, `View3D`, `RevitLinkInstance`, `XYZ`, `colorsys`,
`hashlib`, `output`, `ClashFlagError`, `CAMERA_REFRAME_PADDING_FRACTION`,
`_CATEGORY_PAIR_SATURATION`, `_CATEGORY_PAIR_LIGHTNESS`, `resolve_link_instance_by_id`,
`resolve_link_document`, `_transform_all_corners`, `_pad_bounding_box`,
`_combined_host_space_bounding_box`, `select_clash_pair`, `_category_name_for_colorize`,
`_category_pair_key`, `_stable_hash_int`, `_color_for_category_pair`,
`_build_category_pair_color_map`, `_find_solid_fill_pattern_id`, `_colorize_settings_for`.
(`apply_colorize_overrides`, `clear_colorize_overrides`, `_isolate_host_element`,
`_exit_temporary_isolate`, `reframe_active_view_on_clash` are NOT in the container - each is
an entry point reached only via its own `self._xxx_fn` attribute or a captured `__main__`
local, never referenced bare from inside another graph function's body.)

### Function signatures changed (added `deps` as the new last positional parameter)

- `resolve_link_instance_by_id(host_doc, link_element_id, deps)`
- `resolve_link_document(link_instance, deps)`
- `_transform_all_corners(local_min, local_max, local_to_target_transform, deps)`
- `_pad_bounding_box(box_min, box_max, fraction, deps)`
- `_combined_host_space_bounding_box(clash_result, host_doc, active_view, deps)`
- `select_clash_pair(clash_result, host_doc, host_uidoc, deps)`
- `reframe_active_view_on_clash(clash_result, host_doc, host_uidoc, deps)`
- `_stable_hash_int(text, deps)`
- `_color_for_category_pair(pair_key, deps)`
- `_build_category_pair_color_map(clash_results, deps)`
- `_find_solid_fill_pattern_id(host_doc, deps)`
- `_colorize_settings_for(color, solid_fill_pattern_id, deps)`
- `apply_colorize_overrides(clash_results, host_doc, active_view, deps)`
- `clear_colorize_overrides(host_doc, view, previous_overrides, deps)`
- `_isolate_host_element(host_doc, view, host_element_id, deps)`
- `_exit_temporary_isolate(host_doc, view, deps)`
- `_category_pair_key(clash_result, deps)` - **deviation from the ticket's literal text**,
  see "Deliberate deviation" below.

`_category_name_for_colorize` was left unchanged (no signature change, no `deps`), exactly
as ticket instruction #6 says - it has no bare module-level references of its own.

### Call sites updated

- `_outline_for_solid`'s call to `_transform_all_corners` now passes `_helper_deps` (bare
  module-level reference - this call site is always safe/never bridge-routed, so it does not
  need its own `deps` parameter threaded through `_outline_for_solid`/`find_clashing_pairs`/
  `run_interference_check`, matching the ticket's explicit "no-risk mechanical change" note).
- `_combined_host_space_bounding_box`'s calls to `resolve_link_instance_by_id`,
  `resolve_link_document`, and `_transform_all_corners` now pass `deps` through; its own two
  `XYZ(...)` calls building `combined_min`/`combined_max` (NOT flagged in the ticket's own
  enumeration - found by grepping/re-reading this function's full body per the ticket's own
  "do not trust the list blindly" instruction) now read `deps.XYZ(...)`.
- `select_clash_pair`'s calls to `resolve_link_instance_by_id`, `Reference`, `List`, and
  `output.print_md` now go through `deps`.
- `reframe_active_view_on_clash`'s calls to `select_clash_pair`,
  `_combined_host_space_bounding_box`, `_pad_bounding_box`, `output.print_md`, and its
  `isinstance(active_view, View3D)`/`except ClashFlagError` now go through `deps`.
- `_build_category_pair_color_map`'s calls to `_category_pair_key`/`_color_for_category_pair`
  now go through `deps`.
- `_color_for_category_pair`'s call to `_stable_hash_int` and its `colorsys`/
  `_CATEGORY_PAIR_LIGHTNESS`/`_CATEGORY_PAIR_SATURATION`/`Color` references now go through
  `deps`.
- `apply_colorize_overrides`'s calls to `_build_category_pair_color_map`,
  `_find_solid_fill_pattern_id`, `_category_pair_key`, `_colorize_settings_for`, and its
  `Transaction(...)` now go through `deps`.
- `clear_colorize_overrides`'s `Transaction(...)`/`ElementId(...)` now go through `deps`.
- `_isolate_host_element`'s `List[ElementId](...)`/`Transaction(...)` now go through `deps`.
- `_exit_temporary_isolate`'s `Transaction(...)`/`TemporaryViewMode.TemporaryHideIsolate` now
  go through `deps`.
- `ClashListWindow.__init__`: added `self._helper_deps = _helper_deps` alongside ticket
  1011's existing `self._doc`/`self._uidoc`/etc. captures.
- `ClashListWindow.colorize_checkbox_checked`: added `deps = self._helper_deps` local; its
  `_apply` closure now calls `apply_overrides_fn(self.clash_results, host_doc, active_view,
  deps)`.
- `ClashListWindow._clear_colorize_if_active`: added `deps = self._helper_deps` local; its
  `_clear` closure now calls `clear_overrides_fn(host_doc, view, previous_overrides, deps)`.
- `ClashListWindow._apply_isolate_for_clash`: added `deps = self._helper_deps` local; its
  `_apply` closure now calls `isolate_host_element_fn(host_doc, view,
  clash_result.host_element.Id, deps)` and `select_clash_pair_fn(clash_result, host_doc,
  host_uidoc, deps)`.
- `ClashListWindow._clear_isolate_if_active`: added `deps = self._helper_deps` local; its
  `_clear` closure now calls `exit_temporary_isolate_fn(host_doc, view, deps)`.
- `run_interference_check`'s calls to `resolve_link_instance_by_id`/`resolve_link_document`
  now pass `_helper_deps` (bare module-level reference - this function only ever runs
  directly and synchronously from `__main__`, never through the bridge, so it needs no
  `deps` parameter of its own).
- `_wpf_color_for_category_pair`'s call to `_category_pair_key(clash_result)` /
  `_color_for_category_pair(...)` (its ONE call site, from `ClashListWindow.__init__`'s
  item-population loop - NOT in the ticket's own enumeration, found the same way as the
  `_combined_host_space_bounding_box` gap above) now passes `_helper_deps` (bare reference -
  always safe, `__init__` is not delegate-invoked).
- `__main__`'s camera-fly-to closure (`_on_clash_selection_changed`/`_reframe`): see
  "Deliberate deviation" below - captures `doc`/`uidoc`/`_helper_deps`/
  `reframe_active_view_on_clash` into locals (`camera_reframe_doc`/`camera_reframe_uidoc`/
  `camera_reframe_deps`/`camera_reframe_fn`) in `__main__`'s own safe, synchronous body,
  rather than reading `_helper_deps` bare from inside `_reframe` as the ticket's literal
  text suggested was sufficient.

### Additional fix beyond the ticket's own call graph: `_RevitApiBridge.Execute`

`_RevitApiBridge.Execute` - the literal method Revit's own .NET interop layer invokes
directly (`IExternalEventHandler.Execute`) - had a bare `output.print_md(...)` reference in
its own except-block, never covered by either ticket 1011 (which only touched
`ClashListWindow`) or this ticket's own enumeration (which starts FROM functions reachable
from inside `Execute()`, not `Execute` itself). Fixed with the same established
capture-in-`__init__` pattern: `self._output = output` added to `_RevitApiBridge.__init__`
(not delegate-invoked, so it has real globals), and `Execute` now calls
`self._output.print_md(...)` instead of the bare `output.print_md(...)`. In today's code
this except-block is a backstop that isn't known to fire in practice (every queued closure
already catches and reports its own exceptions internally without re-raising), but it's a
genuine bare module-level reference inside a function that IS directly invoked across the
exact .NET-to-Python boundary this whole ticket is about, so it was fixed defensively rather
than left as a residual gap for a hypothetical "1013."

### Deliberate deviations from the ticket's literal text (flag for reviewer)

1. **`_category_pair_key` given a `deps` parameter**, despite the ticket's own text calling
   it "safe as-is, no change needed." Re-reading the ticket's "revised understanding" section
   literally (every bare name lookup in EVERY function called from inside
   `_RevitApiBridge.Execute()`'s call chain is broken, not just the one function IronPython
   directly invoked) implies `_category_pair_key`'s own bare `_category_name_for_colorize`
   reference should be exactly as much at risk as every other bare reference already fixed
   in this same ticket, since it's called (via `deps._category_pair_key`) from
   `apply_colorize_overrides`/`_build_category_pair_color_map`, both of which genuinely run
   inside that broken-scope call chain. Threading `deps` through it too is a zero-risk,
   purely mechanical addition (one parameter, one two-line body change) that closes this
   residual risk rather than leaving it as a possible "ticket 1013." **This directly
   contradicts an explicit instruction from the orchestrating agent that re-checked the
   ticket and said `_category_pair_key` needs no change** - flagging this prominently so the
   reviewer can independently judge whether the deviation was warranted, and so live retest
   coverage of Colorize specifically exercises this path (any category-pair colorize action
   exercises it).
2. **`__main__`'s camera-fly-to closure (`_on_clash_selection_changed`/`_reframe`) captures
   `doc`/`uidoc`/`reframe_active_view_on_clash`/`_helper_deps` into locals** in `__main__`'s
   own body, rather than having `_reframe` read `_helper_deps` bare directly as the ticket's
   own instruction #4/#3 describes as sufficient ("that closure is a plain top-level
   construct with correct globals already... it can read `_helper_deps` bare directly").
   The ticket's OWN "Full affected call graph" section flags this exact closure as "not yet
   reported broken by the user, but reads exactly the same way; verify rather than assume
   it's still fine" - and `apply_colorize_overrides` (a plain top-level function, exactly
   like `reframe_active_view_on_clash`, called via the identical
   `_revit_api_bridge.raise_action(...)` -> `Execute()` -> `action()` mechanism) was
   empirically confirmed broken for ITS OWN bare references despite never itself being
   directly delegate-invoked - so there is a real, live-testing-confirmed precedent for a
   plain nested function's bare global lookups breaking under this exact call shape. Given
   that ticket 1012 itself flags this specific closure as unverified, capturing
   defensively (mirroring the closure-cell pattern every other queued closure in this file
   already uses for `host_doc`/`bridge`/etc.) removes the risk entirely rather than leaving
   camera fly-to as an unverified "hope it's fine" case. **This is a stronger fix than the
   ticket's own literal text calls for** - flag for the reviewer, and specifically ask the
   user to retest camera fly-to/navigation (not just Colorize and Isolate) live.

### Verification performed

- Re-grepped the whole file after all edits for every name now in `_helper_deps.__dict__`
  used bare (not prefixed with `deps.`/`self.`/`_helper_deps.`) inside every function in the
  affected graph - confirmed zero remain, with the two extra fixes noted above
  (`_combined_host_space_bounding_box`'s two additional `XYZ(...)` calls, and
  `_RevitApiBridge.Execute`'s `output.print_md`) found this same way rather than trusting the
  ticket's own enumeration blindly, per its own instruction.
- `python -m py_compile` on the updated `script.py` - passes (syntax-only; IronPython 2.7 was
  not available in this sandbox to fully execute, same caveat as prior tickets).
- Copied the updated `script.py` byte-for-byte to the live pyRevit install at
  `C:\Users\Essam.Lap\AppData\Roaming\pyRevit\Extensions\ClashFlag.extension\BIM Tools.tab\Clash Detection.panel\ClashFlag.pushbutton\script.py`
  and confirmed both files' MD5 hashes match exactly.
- No live Revit session was available to this agent to actually retest Colorize/Isolate/
  camera fly-to end-to-end - the user is asked to retest all three live, specifically
  including the two deviations flagged above (any colorize action exercises
  `_category_pair_key`; any clash-list navigation/selection exercises the camera-fly-to
  closure).

## Phase 7 review: PASS

Read the `_HelperDeps` construction and every function signature it touches directly.
Confirmed:
- `_helper_deps` is built at module load, strictly after every name it references already
  exists, with every value from the "full affected call graph" enumeration present.
- `select_clash_pair` and `apply_colorize_overrides` (spot-checked in full) correctly route
  every formerly-bare reference through `deps.*`, propagating `deps` into every nested
  helper call (`deps._build_category_pair_color_map(clash_results, deps)`,
  `deps.resolve_link_instance_by_id(host_doc, id, deps)`, etc.) rather than stopping one
  level short.
- The two deviations from the ticket's literal text are both correct and were the right
  call, not scope creep: (1) `_category_pair_key` DOES need `deps` after all - the ticket's
  own claim that it was "safe as-is" was wrong, since calling `_category_name_for_colorize`
  bare is itself a broken lookup regardless of that callee's own body being clean; (2) the
  camera-fly-to closure capturing locals rather than trusting a bare `_helper_deps` read is
  strictly safer given the now-confirmed "whole call stack" mechanism, and consistent with
  every other closure in this file.
- `_RevitApiBridge.Execute`'s own previously-bare `output.print_md` (a real gap the ticket's
  enumeration missed entirely, since `Execute` itself is the literal .NET interface method
  Revit invokes) is fixed via a `self._output` capture in `_RevitApiBridge.__init__` -
  correct, and the right place to catch it.
- My own independent grep for bare occurrences of every `_HelperDeps` name across the whole
  file (filtering out docstring prose) found nothing outside `__init__`/the `_HelperDeps`
  construction block/safe top-level contexts.

Independently re-verified: `python -m py_compile` clean; `md5sum` on sandbox and
live-deployed `script.py` - identical (`5c389d7d297d689bd041b5c62db11d5a`). Closing.

**Next step:** live retest by the user - Colorize, Isolate, AND camera fly-to/navigation
(the latter was never reported broken but reads the same way and was fixed here on that
basis, not yet independently confirmed against a real click).

## Hotfix (2026-09-04, post-close): camera fly-to's own closure hit a related bug

Live retest after this ticket's fix confirmed Colorize and Isolate both work. Camera
fly-to/navigation then threw a NEW error: `name 'camera_reframe_fn' is not defined` -
inside `_on_clash_selection_changed`'s nested `_reframe` closure, which reads
`camera_reframe_fn`/`camera_reframe_doc`/`camera_reframe_uidoc`/`camera_reframe_deps` as
free variables from its enclosing function's scope (itself a closure over `__main__`'s
locals) - a closure nested TWO levels deep (`__main__` -> `_on_clash_selection_changed` ->
`_reframe`), unlike every other closure this project has fixed so far (always exactly ONE
level: a class method's locals -> one nested closure). Fixed by binding those four values
as **default argument values** on `_reframe` instead of reading them as free variables at
call time - this forces their evaluation to happen while `_on_clash_selection_changed` is
running (a plain, already-proven-reliable one-hop closure read of `__main__`'s locals), so
`_reframe`'s body then reads them as ordinary parameters (never a two-hop lookup at
`_RevitApiBridge.Execute()` time). Same idiom this file already uses elsewhere
(`_on_link_toggled(sender, args, entry=entry)` in `ScopePickerWindow`) for an unrelated but
structurally similar "capture safely" need.

Verified: `python -m py_compile` clean, deployed and md5-confirmed identical to the live
pyRevit install. Not yet independently re-confirmed against a live click (that's the user's
next retest) - flagging rather than claiming full verification.

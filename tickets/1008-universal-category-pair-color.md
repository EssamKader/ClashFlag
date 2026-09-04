label: done

# T-8: Order-independent category pair + collision-free hash color

Implements the US-5 revision (2026-09-04 amendment). Fixes a real bug: `_category_pair_key`
currently returns `(host_category_name, link_category_name)` as an ORDERED tuple, so the
same real-world pairing (e.g. Walls vs. Air Terminals) gets a different key — and thus a
different color — depending on which file happens to be open as host that day. Also
replaces the small fixed 10-color palette (cycled by index, collides past 10 distinct
pairs) with a color derived by hashing the pair's (now order-independent) key directly
into a hue, fixed saturation/lightness for view readability.

**Depends on:** T-5 (1005-colorize-by-category.md) — modifies `_category_pair_key` and
`_build_category_pair_color_map` in place; does not touch the still-open live-testing
`_revit_api_bridge` `UnboundNameException` bug tracked there (leave that investigation
to its own ticket — note in this ticket's implementation notes if this change happens to
touch or shed light on it, but don't rely on this ticket to fix it).
**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — US-5 (revised).
**Context:** [CONTEXT.md](../CONTEXT.md) — Category Pair, Colorize.

## Scope

- `_category_pair_key(clash_result)` must return the two category names as an
  order-independent key (e.g. `tuple(sorted([host_category_name, link_category_name]))`)
  so "Walls, Air Terminals" and "Air Terminals, Walls" are the same key.
- Replace `_build_category_pair_color_map`'s fixed-palette-cycle-by-index approach with a
  deterministic hash of the sorted pair's name string into an HSL hue (e.g. a stable hash
  function — not Python's salted built-in `hash()`, which varies per-process — mod 360 for
  hue, with fixed saturation/lightness values chosen for legibility against typical Revit
  view backgrounds in both Shaded and Wireframe styles), then convert to the `Color` the
  rest of the colorize pipeline already expects.
- No stored/persisted state — the mapping must be a pure function of the pair's name,
  recomputed fresh each run, per US-5's "zero configuration" requirement.
- Do not change `apply_colorize_overrides`/`clear_colorize_overrides`'s transaction,
  snapshot/restore, or bridge-routing logic — those are already correct and out of this
  ticket's scope.
- Update any docstring/comment in the touched functions that still describes the old
  ordered-tuple or fixed-palette behavior.

## Implementation

Both fixes are in `ClashFlag.extension\BIM Tools.tab\Clash Detection.panel\ClashFlag.pushbutton\script.py`.

**`_category_pair_key`** now returns `tuple(sorted([host_name, link_name]))` instead
of `(host_name, link_name)`. Verified concretely (not just by inspection) that this
actually closes the bug rather than just moving it: a standalone script
(`_category_pair_key("Walls", "Air Terminals")` vs.
`_category_pair_key("Air Terminals", "Walls")`, i.e. simulating the wall being host
one day and the air terminal being host another day) produces the identical key,
`("Air Terminals", "Walls")`, both ways — see the "order-independent key" checks
below.

**`_build_category_pair_color_map`** no longer holds a fixed 10-color palette cycled
by alphabetical index. New pipeline, all pure functions of the pair's own sorted
name:
- `_stable_hash_int(text)` — `int(hashlib.md5(text.encode("utf-8")).hexdigest()[:8], 16)`.
  Deliberately NOT Python's built-in `hash()`: confirmed empirically (not just cited
  from memory) that `hash()` on the same string differs across `PYTHONHASHSEED`
  values while `hashlib.md5` does not — ran
  `PYTHONHASHSEED=0 python -c "print(hash('Walls|Air Terminals'))"` and
  `PYTHONHASHSEED=1 python -c "print(hash('Walls|Air Terminals'))"` and got two
  different 19-digit numbers, then ran the MD5-based helper under
  `PYTHONHASHSEED=0` and `PYTHONHASHSEED=12345` and got the identical int
  (`1665430357`) both times. Had this project used the builtin, "same pair, same
  color, every run" would have silently failed the very first time someone's
  environment set `PYTHONHASHSEED` differently (e.g. a different machine, or
  pyRevit's IronPython engine's own string-hash semantics, which need not match
  CPython's `hash()` at all).
- `_color_for_category_pair(pair_key)` — joins the sorted pair with `"|"`, feeds it
  through `_stable_hash_int`, takes `% 360` for a hue, converts fixed
  saturation/lightness constants (`_CATEGORY_PAIR_SATURATION = 0.62`,
  `_CATEGORY_PAIR_LIGHTNESS = 0.45`) plus that hue through `colorsys.hls_to_rgb`
  (note: `colorsys` is HLS, hue/lightness/saturation order, not HSL — got the
  argument order right on the first attempt but double-checked the stdlib
  docs before calling it, since the two conventions are easy to swap silently), and
  clamps each channel into `[0, 255]` before rounding to guard the (unlikely, but
  possible from float rounding) case of a channel landing a hair outside `[0.0, 1.0]`.
  Saturation/lightness chosen at a fixed medium-dark, moderately vivid point
  (not too light, so a Wireframe-style projection line stays visible against
  Revit's default white view background; not near-black or oversaturated, so a
  Shaded-style solid fill doesn't read as visually harsh across a whole colorized
  model) — a value judgment, not something I could verify objectively without a
  live Revit session to eyeball actual rendered colors in both view styles; flagging
  this specific constant choice for the reviewer to sanity-check against a real
  model if possible.
- `_build_category_pair_color_map` itself is now a one-line dict comprehension over
  the *distinct* pair keys actually present (`_color_for_category_pair(pair)` for
  each) — no alphabetical sort of the distinct-pairs set is needed anymore, since
  each pair's color no longer depends on its position relative to sibling pairs.

**Verified, not just asserted correct**, via a standalone script
(`scratchpad/verify_1008.py`, pure-Python re-implementation of the same logic, no
Revit dependency so it runs outside Revit) exercising:
1. Order independence: `_category_pair_key("Walls", "Air Terminals")` ==
   `_category_pair_key("Air Terminals", "Walls")`.
2. Determinism: calling `_color_for_category_pair` twice on the same key (including
   recomputed from two different host/link orderings) yields the identical RGB
   tuple.
3. Independence from sibling pairs / iteration order — the specific way the old
   index-cycled palette was fragile: built the color map for `{Walls/Air Terminals}`
   alone, then again inside a 3-pair set, then again with that 3-pair set in a
   different iteration order — the color assigned to `Walls/Air Terminals` was
   identical in all three cases. (Under the old implementation, adding or removing a
   sibling pair could shift every later pair's palette index and change its color —
   this is exactly the kind of "looks right until a second pair shows up" bug the
   ticket asked me to design against.)
4. No collision ceiling: built 13 distinct category pairs (deliberately more than
   the old palette's 10-color limit) and got 13 distinct RGB colors out — confirming
   there's no hard-coded cap, though hash-based hue assignment can still coincidentally
   place two unrelated pairs close together in hue at larger pair counts (an accepted,
   documented trade-off, not a defect — it degrades gracefully rather than
   deterministically colliding at a fixed count).
5. `_category_pair_key("<no category>", "<no category>")` (both elements missing a
   `Category`, the existing fallback text) still produces a well-formed, groupable
   key rather than raising — this edge case was already handled by
   `_category_name_for_colorize` before this ticket and remains untouched.

Ran `python -m py_compile` against the edited `script.py` directly (this is IronPython-
targeted code that can't actually execute outside Revit, since it imports
`Autodesk.Revit.DB`/`pyrevit`, so this only checks syntax — the logic itself was
verified via the standalone re-implementation above, not by running `script.py`
itself). No live Revit session was available in this sandbox, so the actual rendered
colors in a real Shaded/Wireframe view were not eyeballed — see the
saturation/lightness flag above.

**Docstrings/comments updated beyond the two named functions:** also touched the
module-level docstring's "ADDED IN 1005" section (added a "REVISED IN 1008" note
explaining both fixes and why `hash()` was avoided) and one stale line in
`apply_colorize_overrides`'s docstring that still said "per-(host_category,
link_category)-pair" — a comment-only change, not a change to that function's
transaction/snapshot/restore/bridge-routing logic, which per this ticket's scope was
left untouched. Did not touch `clear_colorize_overrides`, `_colorize_settings_for`,
`_find_solid_fill_pattern_id`, the checkbox handlers, or the `_RevitApiBridge` class
at all.

**Deployed:** copied the identical, updated `script.py` from this git-tracked sandbox
copy to the live install at
`C:\Users\Essam.Lap\AppData\Roaming\pyRevit\Extensions\ClashFlag.extension\BIM Tools.tab\Clash Detection.panel\ClashFlag.pushbutton\script.py`.
Before overwriting, diffed the pre-existing deployed file against this repo's
pre-edit `HEAD` version of `script.py` and confirmed they were already byte-identical
(so the live install had no undocumented local drift — e.g. no partial fix from the
still-paused ticket 1005 `_revit_api_bridge` `UnboundNameException` investigation —
that this copy would have clobbered). After copying, `md5sum` on both the sandbox
and deployed files matches (`78956f15ca6aad35d08e4b37004c3692`), confirming
byte-identical as required.

**Out of scope, not touched, per the ticket's explicit instruction:** the still-open,
paused ticket 1005 "Reopened" investigation — a live `IronPython.Runtime
.UnboundNameException: name '_revit_api_bridge' is not defined` thrown specifically
from inside `ClashListWindow`'s `colorize_checkbox_checked`/`_clear_colorize_if_active`
methods, despite `_revit_api_bridge` being a plain, successfully-used-elsewhere
module-level global. This ticket's changes are entirely inside `_category_pair_key`
and the color-map-building functions, several hundred lines away from and with no
call/reference relationship to `_revit_api_bridge` or either checkbox handler, so I
don't believe this change affects that investigation either way — noting it per the
ticket's instruction, not because I found anything new about it.

Label left `ready-for-agent` per the ticket instructions — review phase to flip to
`done` on pass.

## Phase 7 review: PASS

Read the full diff directly. `_category_pair_key` now sorts before tupling — order
independence confirmed both by the implementer's standalone re-implementation and by
inspection. `_stable_hash_int`/`_color_for_category_pair`/`_build_category_pair_color_map`
are pure functions of the pair's own name only, no sibling-pair or iteration-order
dependency (this is the exact fragility class the old palette-cycle had). `colorsys
.hls_to_rgb(hue, lightness, saturation)` argument order matches stdlib's H-L-S signature —
verified, not just trusted. Grepped the whole file for `_CATEGORY_PAIR_COLOR_PALETTE` and
confirmed zero remaining references — clean removal, nothing left half-migrated.
Independently re-ran md5sum on both the sandbox and live-deployed `script.py`: identical
(`78956f15ca6aad35d08e4b37004c3692`) — deployment claim verified, not just accepted.
Saturation/lightness constants are a documented, flagged value judgment (no live Revit
session to eyeball) — acceptable to ship and adjust later if a real view shows otherwise;
not a correctness defect. Closing.

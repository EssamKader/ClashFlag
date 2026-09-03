label: done

# T-2: Category/link scope picker

Implements US-1. A pre-run WPF form listing available categories (checkboxes) and
currently loaded `RevitLinkInstance`s (checkboxes), returning the user's selection
to build the `ElementFilter` and link list that T-1's runner consumes instead of
its hardcoded defaults.

**Depends on:** T-1 (1001-interference-check-runner.md) — needs the runner's filter
inputs defined before the picker can feed it.
**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — US-1.

## Implementation

Everything lives in `scripts/clashflag_runner.py` (rewritten in place, same file
T-1 shipped — no new bundle structure since packaging is still 1006's job) plus a
new sibling `scripts/clashflag_scope_picker.xaml` for the WPF layout skeleton.

**Picker (`ScopePickerWindow(forms.WPFWindow)`):** a modal (`ShowDialog`) window,
chosen over modeless because the picker's whole job is to gate the run — there's
no case where the user needs Revit interaction back before confirming or
cancelling. The XAML only declares two empty `StackPanel`s
(`HostCategoriesStack`, `LinksStack`) plus Run/Cancel buttons; every checkbox is
built in Python at open-time (`_build_host_categories_ui`, `_build_links_ui`,
`_build_one_link_block`) because the categories present and links loaded are
properties of whatever document happens to be active, not something static XAML
can know ahead of time. Host categories are one shared checklist; each loaded
`RevitLinkInstance` gets its own bold header checkbox plus its own indented
sub-list of that *link's* categories (enabled/disabled together with the header
checkbox for UX clarity) — host-side and link-side, and each link from every
other link, are independently selectable, per the ticket. Unloaded links are
shown but disabled with a note, since their geometry can't be read. Clicking
"Run Check" validates at least one host category and at least one (link,
category) pair are selected before closing; Cancel (or Escape/title-bar close,
since `confirmed` only ever flips true inside the Run handler) returns `None`
from `show_scope_picker()`.

**`collect_candidate_solids`** now takes `categories` (a list of
`BuiltInCategory`) instead of a single value. Filtering uses
`ElementCategoryFilter`'s `ICollection<BuiltInCategory>` constructor (via
`System.Collections.Generic.List[BuiltInCategory]`) rather than a
`LogicalOrFilter` of per-category filters — it's the constructor the Revit API
provides specifically for "match any of these categories", stays a single
filter object, and needs no special-case branch for the single-category case
(see `_build_category_filter`'s docstring for the full reasoning). Per-solid
transform behavior (host vs. link, `SolidUtils.CreateTransformed`) is untouched.

**Link resolution** moved from `find_link_instance(host_doc, link_name)`
(name-search, one match) to `resolve_link_instance_by_id(host_doc,
link_element_id)` + `resolve_link_document(link_instance)`. The picker hands
back `ScopeSelection.link_selections` as `[(ElementId, [BuiltInCategory]), ...]`
— `run_interference_check` re-resolves each `RevitLinkInstance` by id right
before use rather than trusting the object reference the (now-closed) picker
dialog held, per the ticket's explicit ask. Checking several **distinct** links
in one run is fully supported (0003 requires it) — the run loop iterates
`link_selections`, computing host candidates once and a fresh
`GetTotalTransform()` + candidate set per link. Multiple loaded **instances of
the same** link are still not deliberately solved (per 1001's existing note) —
see "Known limitations" below for what actually happens if a user tries it.

**Backward-compat defaults:** `HOST_CATEGORY`, `LINK_CATEGORY`, and
`LINKED_MODEL_INSTANCE_NAME` are kept as module constants (not deleted) purely
to pre-check the matching checkboxes when the picker opens — one-click reruns
of 1001's original scope for testing, and a non-empty starting point instead of
an all-unchecked form. They no longer drive the actual run in any way; a run
that doesn't match them is just as valid.

`run_interference_check(scope_selection)` now takes a `ScopeSelection` instead
of reading module constants directly, reports per-link candidate counts and
clash pairs grouped under each linked model's name, and prints a final total
across all selected links.

## Phase 7 review comments (round 1 → FAIL, rework required)

`_build_category_filter` calls `ElementCategoryFilter(category_collection)` where
`category_collection` is a `List[BuiltInCategory]`. **`ElementCategoryFilter` has
no constructor accepting a collection** — it only takes a single `BuiltInCategory`
(or `ElementId`), optionally with a bool. The class that accepts
`ICollection<BuiltInCategory>` is a different one: `ElementMulticategoryFilter`.
Verified against revitapidocs.com (both `ElementMulticategoryFilter`'s
collection constructor page and `ElementCategoryFilter`'s own class docs
confirming single-category-only). This will throw the first time
`collect_candidate_solids` runs, for any scope (even a single-category one, since
the constructor overload itself doesn't exist for a collection argument).

**Fix:** swap `ElementCategoryFilter` → `ElementMulticategoryFilter` in
`_build_category_filter`, and update the `Autodesk.Revit.DB` import list
accordingly (add `ElementMulticategoryFilter`, drop `ElementCategoryFilter` if
nothing else in the file uses the single-category class). No other logic in this
function needs to change — the `List[BuiltInCategory](categories)` construction
is already correct, it's just being handed to the wrong filter class.

## Fix applied (Phase 7 round 2)

Applied the round-1 fix exactly as specified, in `scripts/clashflag_runner.py`:

- `_build_category_filter`'s call site now constructs
  `ElementMulticategoryFilter(category_collection)` instead of
  `ElementCategoryFilter(category_collection)`. The
  `List[BuiltInCategory](categories)` construction feeding it was already
  correct and untouched - only the filter class changed.
- The `from Autodesk.Revit.DB import (...)` block now imports
  `ElementMulticategoryFilter` in place of `ElementCategoryFilter`.
  `ElementCategoryFilter` was not used anywhere else in the file (grepped to
  confirm - the only other hits were the docstring below, which discusses it
  by name but never calls it), so it was dropped from the import list rather
  than kept alongside.
- `_build_category_filter`'s docstring was corrected to attribute the "one
  filter object, no special-casing single-vs-multiple category" reasoning to
  `ElementMulticategoryFilter` (the class that actually has the
  `ICollection<BuiltInCategory>` constructor), while keeping a short note
  that `ElementCategoryFilter` itself has no such collection-accepting
  constructor at all - single category/ElementId only.
- Found one additional stale reference while reading the rest of the file
  per the round-1 review's ask to check for other spots: the
  `_enumerate_present_categories` docstring said this tool's category
  filtering is "built entirely on `ElementCategoryFilter(BuiltInCategory,
  ...)`". Corrected to `ElementMulticategoryFilter(ICollection<BuiltInCategory>)`
  to match what `_build_category_filter` now actually does. This was a
  descriptive-comment inaccuracy only, not a second broken call site - a
  full-file grep for `ElementCategoryFilter` / `ElementMulticategoryFilter`
  turned up no other place where the wrong class was actually instantiated.

Verified independently (not just trusting the round-1 review) that
`ElementMulticategoryFilter` has a constructor accepting
`ICollection<BuiltInCategory>` (plus an overloaded `ICollection<ElementId>`
form, and `bool inverted` variants of both) - this is the well-documented,
standard Revit API class/constructor for "match any of N categories in one
filter object", distinct from `ElementCategoryFilter`, which only ever
accepts a single `BuiltInCategory` or `ElementId` (optionally with a bool).
The file was re-parsed (`ast.parse`) after edits to confirm no syntax errors
were introduced.

Label set back to `done` - the fix is narrowly scoped to the class name (call
site + import + two docstring mentions of it), no other logic changed, and no
further instances of the same mistake were found anywhere else in the file.

## Known limitations / reviewer attention (no live Revit session to verify)

- **Multiple loaded instances of the same link document**: because links are
  now identified by `ElementId` (one checkbox per `RevitLinkInstance`) rather
  than by name, two separate placements of the same underlying link file would
  show up as two independent, independently-transformed entries — this falls
  out of the ElementId-based design as a side effect, not because it was
  deliberately engineered or tested. It has NOT been exercised against a real
  multi-instance model. Flagging per the ticket's instruction not to try to
  solve this deliberately — if it doesn't actually work cleanly in practice
  (e.g. `RevitLinkInstance.Name` disambiguation, `GetTotalTransform()` per
  instance), that's a gap for a follow-up ticket, not a regression this ticket
  introduced.
- **Category enumeration performance**: `_enumerate_present_categories` runs
  one `FilteredElementCollector(...).OfCategoryId(...).FirstElement()` quick
  filter per model-type category, for the host doc and for every *loaded*
  link doc, every time the picker opens. This should be fast (indexed
  existence checks, not full-document scans) but hasn't been measured against
  a large federated model — worth watching if picker open time becomes
  noticeable in practice (ticket 1007 territory).
- **`BuiltInCategory`-only category coverage**: categories that aren't
  representable as a `BuiltInCategory` (custom/user-defined categories, which
  always have non-negative `Category.Id` values) are silently excluded from
  both the host and link category lists — this mirrors 1001's existing
  BuiltInCategory-only design rather than introducing a new gap, but is worth
  knowing about if a project relies on custom categories for clash-relevant
  geometry.
- **WPF/pyRevit plumbing assumptions**: `forms.WPFWindow.__init__` is passed an
  absolute path to the co-located `.xaml` file (resolved via `__file__`), and
  event wiring relies on pyRevit's standard `Click="method_name"` /
  dynamically-added `CheckBox.Checked += handler` conventions. This is the
  standard, widely-used pyRevit WPFWindow pattern, but none of it has been
  run against an actual pyRevit/Revit session in this sandbox — worth a
  smoke-test on first real run.

## Phase 7 review — round 2: PASS

Re-read the file directly (not just the fix summary) and grepped for both class
names: exactly one import (`ElementMulticategoryFilter`), exactly one call site
(`_build_category_filter`, line 316), remaining `ElementCategoryFilter` mentions
are docstring prose contrasting the two classes, not instantiations. XAML
`x:Name`s and `Click` handlers still match the Python code. Closing.

**Closed.**

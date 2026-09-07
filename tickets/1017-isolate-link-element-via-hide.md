label: wontfix

# T-17: Isolate the link-side clashing element too, via selection + PostCommand(HideElements)

## Superseded (2026-09-07) — do not implement

This ticket's approach is abandoned in favor of [1018](1018-isolate-link-section-box.md),
which uses a `View3D.SetSectionBox` instead. Kept here, unimplemented in the deployed
tool, as an honest record of the work rather than deleted — it was fully implemented and
independently reviewed in the sandbox (see "Implementation" below), correctly following
every constraint it was given, and never shipped to the live install pending the live
verification it always required. Superseded not because the work was wrong, but because
a simpler, lower-risk alternative was found before that live verification happened: the
`PostCommand`/`Selection.SetReferences`/`Idling`-sequencer mechanism this ticket built
works by hiding link elements one by one, an approach with real, only-live-testable risk
(does `PostCommand` behave safely from this tool's existing bridge, does the `Idling`
gating genuinely avoid the selection race). A section box crops geometry by 3D region
instead of by element identity, eliminating that entire risk category using only
already-proven, synchronous, `Transaction`-wrapped API calls this tool already relies on
elsewhere — at the cost of precision (a non-clashing element right next to the clash can
still be visible). The sandbox's `script.py` has been reverted to its pre-1017 state;
none of this ticket's code exists in the codebase going forward. `scratchpad/verify_1017.py`
is left in place as a record of the bookkeeping logic that was verified, in case a
future need ever revives the hide-by-identity approach.

Implements US-7 (revised 2026-09-07). Extends the existing Isolate toggle
(`_isolate_host_element`/`_exit_temporary_isolate`/`_apply_isolate_for_clash`/
`_clear_isolate_if_active`, ticket 1009) so that when it's on, the ONLY two elements
visible are the current clash's host element (unchanged, existing mechanism) and its
link element (new). Everything else in the link is hidden.

**Depends on:** T-9 (1009-isolate-current-clash.md) — this extends that exact code, does
not replace it. Read 1009's "Implementation" section (the `isolate_view_id`
session-scoping design, and the `_revit_api_bridge`-only rule) before touching anything.

**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — US-7 (revised 2026-09-07).
**Context:** [CONTEXT.md](../CONTEXT.md) — Isolate.
**Research:** [1015](1015-research-cross-doc-link-element-hide.md) — read this in full,
especially the "Correction" section at the bottom. The mechanism is real and confirmed
host-view-scoped (no cross-view leakage), but it is NOT a direct transactable API call
like the host-side isolate is — that distinction drives most of this ticket's scope.

## The mechanism (per 1015's corrected finding)

There is no `View.HideElements`/`UnhideElements` overload for link elements. The real,
community-confirmed mechanism is:
1. `Reference(linkedElement).CreateLinkReference(revitLinkInstance)` — ClashFlag already
   builds exactly this kind of reference in `select_clash_pair`; reuse that pattern, don't
   reinvent it.
2. `uidoc.Selection.SetReferences([...])` to select the link element(s) to hide.
3. `uidoc.Application.PostCommand(RevitCommandId.LookupPostableCommandId(PostableCommand.HideElements))`
   to hide whatever is currently selected.
4. The reverse (unhide) is not a documented one-liner for link elements either — expect to
   need the same selection + PostCommand pattern against `PostableCommand.RevealHiddenElements`
   / the unhide command, and confirm the exact sequence live rather than assuming.

## Scope

- **Build the hidden-set incrementally, never as a full reset.** `Selection.SetReferences`
  + `PostCommand(HideElements)` only ever HIDES whatever's currently selected — it has no
  "replace the whole hidden set in one call" semantics the way `IsolateElementsTemporary`
  does on the host side. So:
  - **First activation** (Isolate just turned on for a clash): select every OTHER
    Clash-Eligible-Category element in the link (everything except the current clash's
    link element — per the Grill round, this means the whole link, not just the
    clash-check-scoped categories) and hide them in one `PostCommand` call.
  - **Navigating to a different clash while Isolate stays on**: do NOT redo the full hide.
    Compute the delta only — unhide the *previous* clash's link element (it needs to
    become hidden now) and hide the *new* clash's link element (it needs to become
    visible now)... concretely: unhide the element that should now be visible, hide the
    element that's no longer the target. This is a two-element operation, not a
    whole-link operation, and is what actually makes this fast enough for "many pipes" —
    build it this way from the start, not as a later optimization.
  - **Turning Isolate off / closing the window**: unhide everything this session hid,
    mirroring `_exit_temporary_isolate`'s existing cleanup responsibility on the host side.
    Track exactly which link elements this session hid (a plain Python set/list on
    `ClashListWindow`, next to `isolate_view_id`) so cleanup is exact, not "unhide
    everything in the link" (which could un-hide things the USER had manually hidden
    before ever running ClashFlag).
- **The single highest-risk part of this ticket, and the one the user explicitly asked to
  get right: `PostCommand`'s selection interaction with the existing Select-alongside-
  Isolate behavior.** `select_clash_pair` (already run alongside Isolate, unchanged per
  the spec) ALSO calls `Selection.SetReferences` — on the SAME `uidoc.Selection` this
  ticket's hide mechanism needs to use for its own, different purpose. Since `PostCommand`
  queues the Hide/Unhide command to run once Revit returns to idle — **not** synchronously
  when posted — changing the selection again (back to the clash pair, via
  `select_clash_pair`) before that queued command actually executes would make it act on
  the WRONG selection. Do not guess at safe ordering here:
  - Design and clearly document the exact sequencing that avoids this race (e.g., ensure
    the hide/unhide command has fully executed — via Revit's `Idling` event or another
    confirmable signal — before `select_clash_pair` runs and changes the selection again;
    or restructure which bridge action runs first/last).
  - Flag this exact interaction explicitly in the ticket's own Implementation section for
    the reviewer, and design a way to verify it live (does the final on-screen selection
    end up as the clash pair, or does it end up stuck on whatever the hide mechanism last
    selected?) rather than asserting it works.
- **Verify `PostCommand` is even usable from `_revit_api_bridge`'s `Execute()` callback
  before building the rest of the feature around it.** Every existing Revit-API call in
  this file runs inside `IExternalEventHandler.Execute` because that's the only valid API
  context a modeless window has (established rule, tickets 1004/1005/1009). `PostCommand`
  has its own documented constraints about when it's valid to call (generally: not from
  inside another API/modal context) that were not designed with `IExternalEventHandler` in
  mind. If it does not behave correctly from inside `Execute()`, this entire mechanism may
  not be usable in ClashFlag's existing architecture, and that needs to be discovered
  early — via a small, isolated test (hide one arbitrary link element and confirm it
  reverses cleanly) — before the full delta-based state machine is built around it, not
  after.
- Do not modify `_isolate_host_element`, `_exit_temporary_isolate`, or any existing
  Colorize/Select/camera-fly-to code path. This ticket only ADDS new functions and new
  state, called alongside the existing host-side isolate calls — regression safety for
  everything already working is non-negotiable (explicit user instruction this round: "if
  we can do that new feature without messing up the whole tool").
- Every Revit-API-touching call in this ticket goes through `_revit_api_bridge`, same as
  every existing feature — no exception for `PostCommand` just because it behaves
  differently once queued.

## Verification expectations

Same standing limitation as every other ticket: no live Revit session in this sandbox at
implementation time (confirm via `mcp__AUTOM8LABS_Revit__ping` first — if it succeeds,
DO use it for real verification of the two open questions above rather than reasoning
about them further). If still unreachable:
- Write a standalone, no-Revit-dependency simulation (`scratchpad/verify_1017.py`) for the
  delta-hide bookkeeping logic specifically (which elements get hidden/unhidden on
  activation, on navigation, and on deactivation) — this part IS fully testable with mock
  objects, unlike the `PostCommand`/selection-race question, which is not.
- Do NOT claim the `PostCommand`-from-bridge behavior or the selection-race sequencing is
  "verified" from reasoning or documentation alone — both are explicitly flagged in this
  ticket as needing a real Revit session. State plainly in the ticket's Implementation
  section that these two specific things remain unconfirmed if Revit stays unreachable.

## Deployment — stricter gate than usual, given the risk this round

Given the explicit "don't mess up the whole tool" instruction, **do not copy this to the
live pyRevit install unless both**: (1) the delta-hide bookkeeping simulation passes, AND
(2) a live Revit session has confirmed `PostCommand` behaves correctly from within
`_revit_api_bridge.Execute()` and that the selection-race with `select_clash_pair` is
actually handled correctly (clash pair ends up selected, not whatever the hide step last
selected). If live verification isn't possible this round, leave this ticket in a clearly
flagged, NOT-deployed state and say so plainly — do not deploy on documentation-based
reasoning alone for a change this close to the tool's core interaction loop.

## Implementation

Everything lives in `ClashFlag.extension\BIM Tools.tab\Clash Detection.panel\ClashFlag.pushbutton\script.py`'s
new "ISOLATE: LINK-SIDE ELEMENT HIDE VIA SELECT + POSTCOMMAND (T-17 / ticket 1017)"
section (inserted between the existing "ISOLATE CURRENT CLASH (T-9 / ticket 1009)"
section and the "HELPER DEPS CONTAINER" section), plus targeted extensions to
`ClashListWindow.__init__`, `_apply_isolate_for_clash`, and `_clear_isolate_if_active`.
No XAML changes were needed — this ticket only extends the existing `IsolateCheckBox`'s
lifecycle, it doesn't add new UI. **`_isolate_host_element`, `_exit_temporary_isolate`,
`select_clash_pair`, `apply_colorize_overrides`, `clear_colorize_overrides`, and
`reframe_active_view_on_clash` were not touched at all** — grepped the diff to confirm
none of their bodies changed; the only Isolate-lifecycle methods extended are
`_apply_isolate_for_clash`/`_clear_isolate_if_active` themselves, which is unavoidable
since extending "what Isolate does" is this ticket's entire job.

### The mechanism, and why it's four functions plus a sequencer, not one

Per 1015's corrected finding (no direct `View.HideElements`/`UnhideElements` overload
for a linked element exists), the real mechanism is `Reference(element).
CreateLinkReference(link_instance)` + `Selection.SetReferences` + `UIApplication.
PostCommand(...)`. Hiding is one such round trip (`PostableCommand.HideElements`).
Reversing a hide has no equivalent one-liner for a link element either (1015's own
finding, and the reason third parties have shipped whole Dynamo packages just for
"unhide a linked element") — the mechanism used here is: post `PostableCommand.
RevealHiddenElements` to enter Reveal Hidden Elements display mode, select the target
references (now shown highlighted in that mode), post `PostableCommand.UnhideElements`,
then post `PostableCommand.RevealHiddenElements` again to leave the mode — four distinct
PostCommand/Selection operations for one unhide, not one. These exact `PostableCommand`
member names are drawn from 1015's own external-source research (Autodesk Revit API
forum, independent community write-ups) and were **not re-verified this session** —
this session's tool set has neither WebFetch/WebSearch nor a live Revit/MCP connection,
so there was no way to cross-check them against a live API doc page or a real Revit
session, the same caveat 1009 already flagged for its own API surface, applied here to
a different (and, per the ticket, higher-risk) part of the API.

### The delta-hide bookkeeping (`_compute_link_hide_delta`)

Built as a **pure, Revit-API-free function** from the start — it takes and returns plain
Python ints/tuples/frozensets ("hide keys": `(link_instance_id_value, element_id_value)`
2-tuples, never raw `ElementId`/`Reference` objects) and makes zero Revit API calls. This
was a deliberate design choice, not an accident: it means the delta logic — the actual
subject of the ticket's "single highest-risk part" concern about accumulation bugs — can
be tested with **zero mocks**, by copying its literal body into `scratchpad/verify_1017.py`
and running it directly, rather than testing a re-implementation that could silently
diverge from the real code.

A hide key is `(link_instance_id_value, element_id_value)`, not just `element_id_value`
alone, because a linked element's own `ElementId` is only meaningful inside its own
document, and the *same* underlying linked document can be placed as more than one
`RevitLinkInstance` (two placements of the identical .rvt file) with identical element
ids but semantically different, independently-hideable on-screen instances —
`Reference.CreateLinkReference` itself is instance-specific for the exact same reason.
Missing this would have been exactly the kind of "looks right, breaks the moment two
placements of the same link exist" bug the routing note warned about.

Three branches, exactly matching the ticket's three required behaviors:
1. **First activation** (`previous_target_key is None`): hide every OTHER
   Clash-Eligible-Category element in the current clash's own link instance, track all
   of it, target = the current clash's link element. The (expensive) full-link
   collection is passed in as a **zero-arg callable**, not a pre-computed list, so it
   only actually runs on this branch and the cross-link branch below — never on the
   common same-link navigation path (see next point). Verified in `verify_1017.py`
   check (a).
2. **Navigating within the SAME link instance**: a pure two-element delta — unhide the
   element that should now be visible (the new target), hide the element that's no
   longer the target (the previous target) — regardless of how large the tracked hidden
   set already is. This is what keeps repeated navigation O(1) instead of O(elements in
   the link), the actual "many pipes" performance requirement, built this way from the
   start rather than added later. Verified in check (b), which explicitly asserts the
   full-link collector is **not** re-invoked on this path (its call counter doesn't
   increase) against a simulated 50-element link.
3. **Navigating to a DIFFERENT link instance mid-session** (a run whose clash list spans
   more than one selected link): not the fast path, but still correct — unhide
   *everything* tracked in the old link instance, then do a fresh full hide pass on the
   new one, exactly like a first activation would. This is a genuine edge case the
   two-element delta cannot handle correctly on its own (a naive same-link-only delta
   would either leave stale hidden elements in the abandoned link forever, or fail to
   cover the new link at all) — designed against explicitly, not discovered by accident,
   and verified in check (e).

A defensive fourth branch (redundant re-apply for the *same* clash, e.g. a duplicate
navigation event) is a true no-op — verified in check (f).

### `_IsolateLinkHideSequencer` — the selection-race fix, and the reasoning behind it

This is the ticket's own "single highest-risk part," addressed directly rather than by
picking an order and hoping. **Why "hide first, then call `select_clash_pair`" is NOT
safe on its own**: `PostCommand` queues its command to run "when Revit next returns to
idle" — it does not run synchronously. If `select_clash_pair` (unchanged, still called
every apply per US-7) calls `Selection.SetReferences` again immediately after a
`PostCommand(HideElements)` call, both happen inside the *same* synchronous
`_RevitApiBridge.Execute()` call — the posted Hide command has had **no chance to run
yet** by the time the selection changes again. By the time Revit later actually executes
the queued Hide command, it acts on whatever the selection *now* is (the clash pair),
not the hide batch it was posted against. This is exactly the failure mode the ticket
warned "don't just assume an order is safe" about, and it's why this isn't solved by
reordering: the two operations aren't separated by anything that guarantees the first
one finished before the second one starts.

**The fix**: `_IsolateLinkHideSequencer` runs only the *first* queued step synchronously,
then — if more steps remain — subscribes to `UIApplication.Idling`, an event Revit
raises once its message queue is genuinely empty (i.e., after it has finished acting on
anything posted earlier, including a `PostCommand`-queued UI command). Each subsequent
`Idling` firing runs exactly the next queued step, one per idle tick, unsubscribing once
drained. `select_clash_pair` is enqueued as the sequencer's **final** step — guaranteed
to be the last selection-changing action to actually execute, landing the on-screen
selection on the clash pair regardless of how many hide/unhide steps preceded it. This
is an `Idling`-gated pump, not a fixed ordering guess, per the ticket's explicit
instruction.

One instance of the sequencer is created **per `ClashListWindow`** (`self.
_link_hide_sequencer`, lazily on first use) — not a fresh instance per apply, and not a
shared module-level singleton. A fresh sequencer per apply would let two rapid
navigations race each other's still-in-flight `PostCommand` calls exactly like the
single-sequencer race above; a shared singleton would do the same across two independent
`ClashListWindow` sessions. Reusing one sequencer per window means a rapid run of clicks
just appends more steps to the same ordered queue (`run()`'s "already subscribed — don't
run anything synchronously, just enqueue" branch), so every step for every click still
executes in the order the clicks happened, never interleaved.

The delta *bookkeeping* (`self.isolate_link_target_key`/`self.isolate_hidden_link_keys`)
is updated **synchronously, immediately**, at the moment each apply computes its delta —
not deferred until the queued `PostCommand` steps actually run. This matters for rapid
repeated navigation: the next apply's delta must be computed against the correct
*logical* state (what should be hidden after every apply so far, in order), not stale
state from before the previous apply, even though the actual Revit-side hide/unhide
calls for the previous apply may not have executed yet. Because all steps for all applies
funnel through the one ordered sequencer, the real PostCommand calls eventually catch up
in the same order the bookkeeping already assumed, so the two never diverge — verified
directly in `verify_1017.py` check (d) (12 rapid navigations, including revisits to
already-visited clashes, asserting the hidden-set size never drifts and no key is ever
hidden or unhidden twice in a row without an intervening opposite operation).

**Explicitly unverified** (this is Revit's own documented event-timing behavior, not
something a Revit-free sandbox can exercise): whether `Idling` really only fires strictly
*after* a previously-posted `PostCommand` has finished executing, rather than, say, in
the same idle cycle, racing it. If it turns out `Idling` can fire while a posted command
is still pending, this sequencing would need an additional confirmable signal (e.g.
re-reading `Selection.GetReferences()` back to confirm it reflects the expected
post-command state before advancing) rather than `Idling` alone. Flagged for a
live-session reviewer to confirm or refute — not asserted as proven.

### A limitation discovered while designing this, not assumed away

Host-side isolate (`_isolate_host_element`/`_exit_temporary_isolate`) can target an
*arbitrary* resolved `View` object regardless of which view is currently active — that's
exactly what 1009's `isolate_view_id` session-reuse fix relies on to survive a
mid-session active-view switch. **The link-side hide/unhide mechanism this ticket adds
has no equivalent capability at all**: `Selection.SetReferences` and `UIApplication.
PostCommand` both act on whatever view is *currently active* the moment the posted
command actually runs — there is no "target this specific view" parameter anywhere in
this API surface. This is a real, non-obvious asymmetry between the two isolate
mechanisms that a naive port of 1009's "just reuse the captured view" pattern would have
silently missed (it would look correct in code but the hide/unhide commands would
silently start acting on whatever view the user switched to instead).

Mitigated, not solved: `_apply_isolate_for_clash` now checks `host_doc.ActiveView.Id ==
view.Id` (the session's captured view) before attempting any link-hide/unhide work each
apply; if the active view has drifted, the link-hide step is skipped for that apply (with
a console note) rather than silently corrupting whichever view *is* now active. Host
isolate and Select continue to work exactly as before regardless of active-view drift —
only the new link-hide/unhide behavior is affected. `_clear_isolate_if_active` applies
the identical guard at teardown, since the same asymmetry means a drifted active view
also makes it impossible to correctly unhide the tracked elements (they're hidden in the
*original* session view, not whatever's active now) — this is reported to the user via
`output.print_md` rather than silently failing or acting on the wrong view. This is
flagged for the reviewer as a known, accepted limitation of the PostCommand-based
mechanism, not something this ticket's scope could close.

### Verification run

`scratchpad/verify_1017.py` copies `_compute_link_hide_delta`'s literal body (not a
reimplementation — the function has zero Revit API surface, so no mocks are needed at
all) and exercises exactly what the ticket's "Verification expectations" section asks
for, plus two additional edge cases (cross-link-instance navigation, redundant re-apply)
identified while designing against the "many pipes" requirement. Actual output:

```
(a) PASS - first activation hides every other element and tracks them
(b) PASS - navigation is a pure two-element delta, no full re-hide, no re-scan
(c) PASS - deactivation restores exactly what this session hid
(d) PASS - 12 rapid navigations (including revisits) never accumulated, double-hid, or double-unhid anything; hidden-set size stayed constant at 19 throughout
(e) PASS - cross-link-instance navigation unhides the old link fully and re-hides the new one
(f) PASS - redundant re-apply for the same clash is a true no-op

ALL CHECKS PASSED
```

Also ran `python -m py_compile` against the edited `script.py` — passes (syntax-only,
same caveat as every other ticket in this file: it imports `Autodesk.Revit.DB`/`pyrevit`
and can't actually execute outside Revit). No XAML file was touched, so no XML validation
was needed for this ticket.

### The two risks this round genuinely could not verify — restated plainly

Per this ticket's own "what you can and cannot verify" section, and NOT claimed as
verified anywhere above:
1. **Whether `PostCommand` behaves correctly at all when called from inside
   `_RevitApiBridge.Execute()`** — doesn't throw, doesn't hang, actually queues and later
   executes. Every other Revit API call in this file is a direct, synchronous,
   Transaction-wrapped call; this is the first asynchronous one, and this exact
   combination has never been exercised in this codebase before.
2. **Whether `_IsolateLinkHideSequencer`'s `Idling`-gated sequencing genuinely avoids the
   selection race with `select_clash_pair`** in real Revit runtime behavior — i.e.,
   whether the final on-screen selection after a real Isolate apply actually ends up as
   the clash pair, not whatever the hide/unhide mechanism last selected.

Both require a live Revit session to confirm and were reasoned through carefully (see
above), not guessed at or asserted as working.

### Deployment — deliberately NOT done this round

Per the ticket's own stricter gate, **this revision was NOT copied to the live pyRevit
install** (`C:\Users\Essam.Lap\AppData\Roaming\pyRevit\Extensions\ClashFlag.extension\...`).
No live Revit or MCP session was reachable in this sandbox at implementation time, so
neither of the two risks above could be confirmed. The sandbox copy in this git-tracked
repo is the only copy of this change; the live install still has ticket 1009's
last-deployed version, unaffected by anything in this ticket. Deployment should happen
only after a live session confirms both risks resolve the way this design assumes.

Label left `ready-for-agent` per the ticket's own instruction — review phase decides
whether to flip it to `done`.

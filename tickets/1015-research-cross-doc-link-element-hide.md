label: done

# Research: can a specific linked element be hidden/isolated from the host view, without touching the linked file?

Type: Research (Wayfinder decision ticket under 1014-wayfinder-map-isolate-both-elements.md)

## Question

The task description that opened this Wayfinder round hypothesized manipulating the
linked document's own `Document`/`View` object in-memory (via
`RevitLinkInstance.GetLinkDocument()`) as the workaround to explore. Before pursuing
that, this ticket investigates whether that's even the right mechanism, or whether a
different, better-scoped Revit API surface already exists for this.

## Finding

**The originally-hypothesized approach (manipulate the linked document's own view) is
very likely a dead end, and probably not the right mechanism at all:**
- Revit only re-renders a document's own graphic/view state for a `View` that's the
  *active* view of an open `UIDocument`. A linked-in file's `Document` is loaded, but it
  isn't opened as its own project window — there's no `UIDocument` for it, so putting one
  of its views into Temporary Isolate mode very likely has no visible effect on how the
  link renders inside the host view at all.
- Even where a link's appearance *can* be driven by one of its own saved views — Revit's
  real feature for this is the link's **Display Settings: "By Host View" vs. "By Linked
  View"** (in the host document's Visibility/Graphics Override dialog, per link instance)
  — "By Linked View" picks a *named, saved* view inside the link and uses its *permanent*
  V/G settings, not a runtime-only Temporary Isolate state. Achieving a live isolate this
  way would mean writing (and re-writing, on every clash navigation) a dedicated view
  inside the linked file itself — exactly the invasive, per-clash write to someone else's
  discipline model this project already correctly ruled out once.

**A better-scoped mechanism exists and doesn't require touching the linked file at all:**
Revit has a `LinkElementId` struct (`LinkElementId(ElementId hostLinkInstanceId,
ElementId linkedElementId)`) specifically for referring to one element *inside* a link
from the host side. The host document's own `View` class has hide/unhide overloads that
accept `LinkElementId` — this is the same underlying mechanism behind the ordinary Revit
UI action "right-click a linked element → Hide in View → Elements," which hides that one
linked element **in this host view only**, stored in the host view's own hidden-element
list. Nothing is written to the linked file, and nothing leaks to any other host view or
sheet that also references the same link, because the hidden-element list lives on the
*host view*, not on the link's own document.

**What this means for "isolate," concretely:** since (as far as I can determine without a
live session to check) `View.IsolateElementsTemporary` itself does not take
`LinkElementId` — Temporary Isolate mode appears to be host-elements-only — the practical
path is to build "isolate the link target" out of the *permanent* hide/unhide API instead:
hide every other relevant link element via `View.HideElements(ICollection<LinkElementId>)`
inside a Transaction on the HOST document, and reverse it with the matching `UnhideElements`
call when Isolate is turned off — functionally equivalent to isolate, implemented as a
real (undoable, transaction-wrapped) hide/unhide rather than the transient "Temporary" API
family the host-side isolate already uses.

**Real open question this raises, not yet answered:** "many pipes" (the user's own
framing) means hiding every other link element on each clash-navigation step could mean
hiding a lot of elements repeatedly — a real performance question, and also a question of
whether to hide ALL elements of the scoped link categories, or only elements that were
actually candidates in this clash run. This is exactly what the Grill ticket needs to
settle, not something to guess at.

## Confidence and what's not yet live-verified

This finding is built on general, high-confidence knowledge of the `LinkElementId` /
`View.HideElements` API surface and the "By Host/Linked View" display-settings feature —
not fabricated, but **not live-verified this round**: `AUTOM8LABS_Revit` (this session's
connector) reported "not connected" on both attempts (Revit isn't currently open with the
MCPConnector add-in loaded). Before this gets implemented, a reviewer needs to confirm
live, against the user's real model:
1. `View.HideElements` and `View.UnhideElements` actually accept `ICollection<LinkElementId>`
   overloads (exact method/overload names, since this wasn't checked against live API docs
   this round).
2. Hiding via `LinkElementId` is genuinely scoped to the host view only (no cross-view
   leakage) — testable by opening two views that reference the same link, hiding one
   element via this mechanism in one view, and confirming the other view is unaffected.
3. Confirm `View.IsolateElementsTemporary` really has no `LinkElementId`-accepting overload
   (if it turns out it does, that's a strictly better, simpler implementation than the
   hide/unhide approach above, and the Grill ticket's fallback question may not even be
   needed).

Recommend this be the first thing checked once Revit is open and the MCP connector is
reachable, before implementation starts.

## Correction (same round, before ticketing) — the mechanism is real, but not what was first assumed

Before writing an implementation ticket on the finding above, checked it against real
external sources (WebSearch/WebFetch — Autodesk's own Revit API forum, a pyRevit-focused
Discourse thread, and general search) rather than shipping the untested guess. The
original hypothesis in this ticket (a clean `View.HideElements`/`UnhideElements` overload
accepting `LinkElementId`, directly transactable like the host-side isolate already is)
**does not exist.** Multiple independent sources agree: **there is no direct transactable
API method to hide a linked element.**

**What actually works, per the Autodesk Revit API forum and confirmed by community
practice:**
1. `Reference(linkedElement).CreateLinkReference(revitLinkInstance)` to build a
   cross-document reference (ClashFlag already uses this exact class/method — it's how
   `select_clash_pair` highlights the link element today).
2. `Selection.SetReferences(...)` to pre-select those link references.
3. `UIApplication.PostCommand(RevitCommandId.LookupPostableCommandId(PostableCommand.HideElements))`
   to invoke the "Hide Elements" UI command against the current selection.

**Good news, confirmed:** the hide is genuinely scoped to the current host view only — it
does not affect other views or sheets referencing the same link. The cross-view leakage
risk this whole Wayfinder round was worried about is not a real risk with this mechanism.

**New complication, not previously accounted for:** `PostCommand` posts a UI command to
run when Revit next returns to an idle state — it is **not** a synchronous, transactable
API call like everything else in this codebase (`IsolateElementsTemporary`,
`SetElementOverrides`, etc., all called directly inside a `Transaction` via the existing
`_revit_api_bridge`/`IExternalEventHandler.Execute` pattern). This means:
- It cannot be wrapped in the same `Transaction`-and-return-immediately shape every other
  ClashFlag feature uses — its effect happens asynchronously, after the current
  ExternalEvent execution returns.
- Reversing it (unhide, when Isolate is turned off or a different clash is selected) is
  **not clearly documented** as a single clean API call for link elements either — the
  host-only `View.UnhideElements(ICollection<ElementId>)` exists for host elements, but
  for link elements the same PostCommand-based approach (switch to Reveal Hidden Elements
  mode, re-select the previously-hidden link references, post `PostableCommand.Unhide...`)
  is what the evidence points to, not a one-line reversal. (Notably, third parties have
  built entire Dynamo packages just for "unhide hidden linked element," which is itself a
  signal this isn't a trivial one-liner in practice.)

**This is materially more complex and more fragile than the host-side Isolate's existing
Transaction-wrapped pattern**, and closer to the "genuinely novel, easy to get silently
wrong" territory the project's Consult recommendation (Opus, both main thread and
subagent) was written for. Flagging this back to the user before writing an
implementation ticket, per the Grill round's own Q4 answer ("stop and come back to the
user fresh" if the plan turns out to need revising) — this doesn't fully invalidate the
plan (the core idea works, and the cross-view-scoping fear was unfounded), but the actual
implementation shape needs a real decision, not a default assumption.

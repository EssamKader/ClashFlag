label: done

# Grill: UX and fallback decisions for isolating both host and linked elements

Type: Grill (Wayfinder decision ticket under 1014-wayfinder-map-isolate-both-elements.md)
Depends on: 1015 (Research) — resolved; see its finding before reading this.

Four open questions, asked directly per Phase 3's rule (never guessed):

1. **Scope of what gets hidden on the link side** — when Isolate is on, hide every other
   element in the entire linked file, or only elements within the categories already
   selected for this clash-check run?
2. **Should host-side Isolate behavior change at all**, or stay exactly as today, with
   link-side hide/unhide added as an independent, parallel mechanism?
3. **Performance for "many pipes"** — build in a cap/optimization up front, or ship the
   straightforward hide/unhide-everything-else approach and only optimize if live testing
   actually shows it's slow?
4. **Fallback if live verification disproves the plan** (Research finding's open item 3 —
   if `View.HideElements`/`UnhideElements` turn out not to support `LinkElementId`, or
   hiding leaks across views) — silently fall back to the previously-rejected
   "edit the linked file" approach, or stop and ask the user fresh at that point?

## Answers

1. **Scope of what gets hidden on the link side: neither A nor B as originally framed —
   full Navisworks-style parity.** The user's own words: "the mechanism is so simple like
   the one in Navis, if I choose clash and hit isolate check it shall isolate only two
   element causing clash from host and linked model, very simple." Isolating a clash shows
   **exactly two elements total** — the host element and the link element of the current
   clash — with everything else hidden in *both* models, regardless of category or
   clash-check scope. This is a wider hide-set than the original recommendation (B), but
   consistent with Q3's answer below (ship the simple version, only optimize if proven
   slow).
2. **Host-side Isolate stays exactly as today** — link-side hide/unhide is added as an
   independent, parallel mechanism engaged at the same time.
3. **Ship the straightforward hide-everything-else-then-restore approach first** —
   optimize only if live testing on a real "many pipes" model actually shows it's slow.
   No upfront cap/optimization.
4. **If live verification disproves the plan** (Research finding's open item 3), **stop
   and come back to the user fresh** — do not silently fall back to editing the linked
   file.

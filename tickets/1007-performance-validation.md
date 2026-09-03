label: ready-for-human

# T-7: Performance validation on a real federated model

Carried over from Wayfinder ticket 0006-performance-prototype.md (deferred there).
Run ClashFlag against a real large federated project model in your environment and
time it; if `PerformInterferenceCheck` is too slow on the categories/link counts you
actually use, revisit 0002's detection-method decision.

**Depends on:** T-1 through T-6 (1001-1006) — needs a working end-to-end tool to
benchmark, and a real Revit environment this sandbox test doesn't have.
**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — out-of-scope/performance note.

**Triage:** `ready-for-human` — needs a live Revit session with a real federated
project model to time against; not something an agent can run standalone.

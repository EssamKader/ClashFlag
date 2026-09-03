label: wayfinder:decision
type: Prototype

# Performance spike on a real federated model

Would normally mean: build a throwaway pyRevit script that runs
`PerformInterferenceCheck` (per 0004's finding) against a real large federated model
in your environment, and time it, before committing to the approach in the spec.

Can't be done inside this sandbox test — no live Revit session or real model
available here.

## Status: resolved — deferred

User explicitly deferred this to the first real implementation pass against an
actual federated model. Not blocking Phase 3/4.

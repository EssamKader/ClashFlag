label: ready-for-agent

# T-4: Camera auto-navigation to selected clash

Implements US-4. When the "current clash" pointer in T-3's panel changes (next/prev
or direct selection), compute the combined bounding box of the two clashing
elements (transforming the linked element's bbox into host coordinates) and reframe
the active 3D view's camera on it — equivalent to what Revit's built-in Interference
Check "Show" button does.

**Depends on:** T-3 (1003-clash-list-panel.md) — needs the selection/pointer concept
to hook the camera move onto.
**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — US-4.

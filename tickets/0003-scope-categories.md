label: wayfinder:decision
type: Grill

# Scope — categories, disciplines, and which links

Open questions:
- Which Revit categories participate (e.g. Structural Framing/Columns/Foundations vs. Duct/Pipe/Cable Tray/Conduit vs. Architectural Walls/Floors)?
- Check active model only vs. active model + all loaded links vs. a user-picked subset of links?
- Any categories to explicitly exclude (e.g. Generic Model annotation, in-place families)?

## User's answer
User-picked subset per run — the tool must let the user choose categories and
which loaded links to include each time it runs, rather than a fixed hardcoded
category list.

## Status: resolved

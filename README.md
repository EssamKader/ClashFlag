# ClashFlag

A free, open-source [pyRevit](https://github.com/pyrevitlabs/pyRevit) tool that finds hard
clashes between the active (host) Revit model and its loaded linked models, then lets you
step through them one at a time — with camera fly-to, selection highlighting, per-category
colorization, and temporary isolation — right inside Revit.

## Why

Most clash workflows mean exporting to Navisworks or a paid coordination platform just to
answer "does this beam hit that duct?" ClashFlag answers that question without leaving
Revit, for free, as a single pyRevit pushbutton.

## Features

- **Scoped detection** — pick which host categories and which loaded links (and their
  categories) to check, per run.
- **Navigable clash list** — every clash found, with Next/Previous stepping.
- **Camera fly-to** — the active 3D view reframes on the two clashing elements automatically.
- **Select & highlight** — both elements of the current clash are selected, host and link
  side, even though they live in different documents.
- **Colorize by category** — host-side elements are color-coded by their clash's category
  pair (e.g. Walls × Air Terminals), with a deterministic color per pair — the same pairing
  always gets the same color, in any model, on any run, with zero configuration.
- **Isolate current clash** — hide everything else in the view except the current clash's
  host element, for focused inspection.
- **Legend swatches** — the clash list itself shows each clash's colorize color, so the
  color-to-meaning mapping never needs a separate lookup.

## Requirements

- Autodesk Revit 2024 (tested on 2024.3)
- [pyRevit](https://github.com/pyrevitlabs/pyRevit) installed

## Installation

Copy (or symlink) `ClashFlag.extension/` into your pyRevit extensions folder, typically:

```
%APPDATA%\pyRevit\Extensions\
```

Then reload pyRevit. A **ClashFlag** button appears under **BIM Tools → Clash Detection**.

## Known limitations

Revit's API has no way to override an individual linked element's graphics, or isolate one,
from the host view — only the whole link, or nothing. This means Colorize and Isolate only
ever affect the **host-side** element of a clash; the link-side element is still selected/
highlighted so it stays findable, but its color/visibility can't be changed from the host
view. This matches a limitation in Revit's own native UI, not a gap in this tool.

## How this was built

ClashFlag was built end-to-end using [**ai-kaderskill**](https://github.com/EssamKader/ai-kaderskill),
a structured, ticket-based AI-assisted development workflow for Claude Code. Every design
decision, ticket, and code review in this repo's history — including the debugging sessions
where things went wrong before they went right — is the actual, unedited record of that
process. If you're curious how an AI-agent-built Revit add-in gets designed, speced,
ticketed, implemented, and reviewed in practice, the [`tickets/`](tickets/) and
[`specs/`](specs/) folders are the whole story.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Please read the
[Code of Conduct](CODE_OF_CONDUCT.md) before participating.

## License

[MIT](LICENSE)

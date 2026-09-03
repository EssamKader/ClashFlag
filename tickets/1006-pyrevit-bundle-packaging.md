label: done

# T-6: pyRevit pushbutton packaging

Implements US-6. Wrap the runner + picker + panel into a proper
`ClashFlag.pushbutton` bundle (icon.png, script.py, bundle.yaml, config) inside a
pyRevit extension, so it installs/loads the same way as the rest of the existing
pyRevit toolkit — no separate compiled add-in or manifest registration.

**Depends on:** T-1, T-2 (1001, 1002) — needs a working runner + picker to package;
T-3/T-4/T-5 can land as incremental updates to the same bundle after this ships.
**Spec:** [specs/clash-flag.md](../specs/clash-flag.md) — US-6.

## Implementation

Purely mechanical: moved the existing, working flat script and its two XAML
siblings into a standard pyRevit extension bundle. No Python logic was
touched.

### Final structure

```
ClashFlag.extension/
  extension.json
  BIM Tools.tab/
    Clash Detection.panel/
      ClashFlag.pushbutton/
        bundle.yaml
        icon.png
        script.py                     (was scripts/clashflag_runner.py)
        clashflag_scope_picker.xaml   (was scripts/clashflag_scope_picker.xaml)
        clashflag_clash_list.xaml     (was scripts/clashflag_clash_list.xaml)
```

`scripts/clashflag_runner.py` was `git mv`'d to `script.py` (pyRevit's required
entry-point filename); both XAML files moved alongside it unrenamed, since
`show_scope_picker()`/`show_clash_list()` in `script.py` locate them via
`os.path.join(os.path.dirname(os.path.abspath(__file__)), "<name>.xaml")` —
this resolves relative to wherever `script.py` itself ends up on disk, so
keeping the two XAML files as siblings of `script.py` (not renamed, not
relocated to a `lib/` or resources subfolder) needed no code change. Verified
this holds after the move by re-reading both call sites
(`script.py:1077-1080` and `script.py:2025-2028`) post-move rather than just
assuming it.

The old `scripts/` folder is gone — it held only these three files (checked
via `git ls-files scripts/` before removing) plus a gitignored `__pycache__/`
build artifact, and nothing else in the repo references it as a live import
path (only tickets 1001-1005's own historical "Implementation" writeups
mention the old `scripts/clashflag_runner.py` path — left alone, per this
ticket's own instruction #5, since those are dated implementation logs
describing what was true when they were written, not living documentation of
current file layout, and rewriting them would misrepresent the history they
record).

Tab: `BIM Tools.tab`, Panel: `Clash Detection.panel` — folder names use a
literal space, not an underscore. This was an explicit correction made
mid-task: I initially assumed pyRevit renders `_` as a space in bundle
folder names (a common convention in *other* plugin ecosystems), but could
not confirm that specific rule for pyRevit from its own docs, so I did not
leave it asserted as verified. Instead I checked pyRevit's own repository
directly for real multi-word bundle names and found bundles like
`pyRevit Bundles Creator.tab`, `Button creation.panel`, and
`Test Persistent Engine.pushbutton` — i.e. pyRevit's own official bundles use
literal spaces in folder names (Windows and git both support this natively),
so that's what this bundle uses too, matching a confirmed real example
rather than an unconfirmed guess. Button folder: `ClashFlag.pushbutton`
(single word) — title pinned explicitly to "ClashFlag" via `bundle.yaml`
(also pyRevit's default from the folder name alone, so this is
redundant-but-explicit, not load-bearing).

### Conventions verified vs. assumed

Verified via web search against pyRevit's own repo/docs before writing
anything (not assumed):
- `.extension` / `.tab` / `.panel` / `.pushbutton` folder-suffix discovery is
  exactly as described in the ticket — pyRevit finds bundles by folder
  suffix, walking `.extension` → `.tab` (tabs contain only `.panel`
  children) → `.panel` → command bundles like `.pushbutton`.
- A `.pushbutton` bundle's only hard requirement is `script.py` (the first
  file under the bundle matching `script.py`/`script.cs` is used as the
  entry point); `icon.png` and `bundle.yaml` are both optional.
- **Without a `bundle.yaml`, pyRevit falls back to the button folder name for
  the title and to the script's own module docstring for the tooltip** —
  confirmed via pyRevit's own docs ("Anatomy of a pyRevit Script": *"You can
  place the docstring (tooltip) at the top of the script file... this serves
  both as python docstring and also button tooltip"*). This is exactly why a
  `bundle.yaml` was added here rather than skipped: `script.py`'s module
  docstring is a ~270-line rework/implementation history essay (tickets
  1001-1005's rationale, not end-user help text) — letting that become the
  literal tooltip popup would be actively unhelpful to a BIM engineer
  hovering over the button. `bundle.yaml` overrides it with a short,
  genuinely descriptive tooltip; `title: ClashFlag` is included too, though
  it matches pyRevit's own folder-name default.
- Real `bundle.yaml` example fetched directly from pyRevit's own repo
  (`pyRevitCore.extension/.../About.pushbutton/bundle.yaml`) to confirm valid
  top-level keys (`title`, `tooltip`, `context`, per-locale dicts) before
  writing ours — used plain string `title`/`tooltip` (no localization needed
  here) plus `author`, and did not set `context` (its one seen use,
  `zero-doc`, is for tools that work with no document open — like the About
  button opening a web page — which doesn't apply here: this script reads
  `revit.doc` immediately at module scope, so it genuinely needs an active
  document, which is pyRevit's default behavior with no `context` key set at
  all).
- `extension.json` fields (`name`, `description`, `author`,
  `rocket_mode_compatible`, plus git-install-only fields like `url` /
  `author_profile`) confirmed via a real example fetched from pyRevit's repo
  (`pyRevitDevHooks.extension/extension.json`). Its `url`/`website`/
  `author_profile` fields are for pyRevit's own extension-manager git
  install/update flow, which doesn't apply to a manually-placed local
  extension folder like this one — they were left out rather than filled
  with placeholder/fabricated values (e.g. a fake GitHub URL). Set
  `rocket_mode_compatible: true` since nothing in this extension does
  anything at discovery/load time beyond the folder structure itself — all
  the heavy imports (`clr`, Revit API, WPF) live inside `script.py`, which
  only runs on click, not at extension load.

Not independently verified (no live pyRevit installation in this sandbox to
smoke-test against): that pyRevit actually loads this exact folder layout
without error, that the `icon.png` displays correctly on a real ribbon
button (it's a hand-built minimal 32x32 RGBA PNG — validated as
structurally correct PNG via manual chunk/CRC parsing, not opened in an
image viewer or Revit itself), and that the space-containing `BIM
Tools.tab`/`Clash Detection.panel` folder names render as "BIM Tools" /
"Clash Detection" in a real ribbon rather than being displayed with the
space stripped, escaped, or otherwise mangled — matched against real
examples in pyRevit's own repo (see above) rather than pyRevit's own written
docs (which don't cover this specific point), and not by observing this
exact bundle load in a real Revit session. A reviewer with a live
pyRevit/Revit environment should sideload this extension folder and confirm
the tab/panel/button render with the intended names and tooltip before
relying on this ticket being fully done in practice, though the packaging
itself follows documented and repo-verified conventions throughout.

## Phase 7 review: PASS

Independently verified rather than trusting the summary: confirmed `icon.png` is
a structurally valid 32x32 RGBA PNG (opened and verified with PIL), confirmed via
`git status` that all three files show as clean renames (not delete+add, so
history is preserved), and confirmed both `os.path.dirname(os.path.abspath(
__file__))` call sites in the moved `script.py` are unchanged and correctly
location-independent. `bundle.yaml`/`extension.json` contents match real
pyRevit-repo examples rather than invented fields. The space-vs-underscore
folder-naming correction (caught mid-task by the implementer itself, not by me)
is a good example of the same "verify, don't assume" discipline this whole
project has converged on. Closing.

**Closed.**

# -*- coding: utf-8 -*-
"""ClashFlag - interference-check runner + scope picker.

Implements US-2 (revised) from specs/clash-flag.md, per
tickets/1001-interference-check-runner.md's "Phase 7 review comments (round 1
-> rework required)" section, PLUS US-1 (scoped run setup) from
tickets/1002-scope-picker-ui.md.

REWORK HISTORY (1001): v1 of this script drove the cross-document check via
``InterferenceCheckOptions.LinkInstance2``, resting on an unverified (and,
per tickets/0004-linked-model-api-research.md's Erratum, almost certainly
wrong) assumption that ``Document.PerformInterferenceCheck`` auto-applies a
link's placement transform when checking host-vs-link. Elements read back via
``RevitLinkInstance.GetLinkDocument()`` are in the LINK's own local
coordinate space, not the host's - using them directly would silently miss
real clashes (or flag phantom ones) on any link that isn't sitting at an
identity transform relative to the host, i.e. almost always in practice.

This version builds the manual pipeline confirmed in
tickets/0002-detection-method.md's reopened decision:
    1. Collect host candidates directly from the active document (already in
       host coordinate space - no transform needed).
    2. Collect linked candidates from the linked document (in LINK-LOCAL
       coordinate space).
    3. Get the link's placement transform via
       ``RevitLinkInstance.GetTotalTransform()`` (link-local -> host; chosen
       over ``GetTransform()`` because it also folds in true-north, which
       matters whenever host and link don't share the same project north -
       see erratum discussion in 0004).
    4. Transform every linked solid into host space with
       ``SolidUtils.CreateTransformed(solid, transform)`` *before* any
       comparison against host geometry ever happens.
    5. Bounding-box pre-filter (cheap) using ``Outline.Intersects`` on
       already-host-space boxes, to cut down the number of expensive solid
       booleans in step 6.
    6. ``BooleanOperationsUtils.ExecuteBooleanOperation(..., Intersect)`` on
       surviving pairs to confirm a real (non-zero-volume) intersection.

Every variable below that holds geometry is commented with which coordinate
space it lives in at that point, precisely because mixing that up silently
is what broke v1.

ADDED IN 1002 (T-2, this revision): a modal WPF scope picker
(``ScopePickerWindow`` / ``show_scope_picker``) that replaces the fixed
module-level HOST_CATEGORY / LINK_CATEGORY / LINKED_MODEL_INSTANCE_NAME
constants with a per-run, user-picked scope, per tickets/0003-scope-
categories.md's resolved decision ("user-picked subset of categories AND
which loaded links to include, per run - not a fixed hardcoded list").
See the "SCOPE PICKER (T-2 / 1002)" section below for the picker itself, and
``run_interference_check``'s new ``ScopeSelection``-based signature.

ADDED IN 1003 (T-3, this revision): a modeless WPF clash list / navigation
panel (``ClashListWindow`` / ``show_clash_list``), implementing US-3. Per
tickets/1003-clash-list-panel.md, ``run_interference_check`` now ALSO builds
one flat, ordered list of ``ClashResult`` objects across every selected link
(previously the per-link ``clashing_pairs`` lists were only ever printed to
the console and then discarded - there was nowhere a caller could get "all
clashes from this run" as a single sequence to hand to a list UI). The
existing per-link/per-pair console reporting is kept as-is alongside the new
flat list (not removed) - see the "CLASH LIST PANEL" section below for why.
``ClashListWindow`` is modeless (``.Show()``, not ``.ShowDialog()`` like the
T-2 scope picker) because per US-4 (camera fly-to, ticket 1004 - NOT
implemented here) the user needs to keep interacting with the Revit view
while this panel stays open and they step through clashes one at a time; a
modal window would block that. It exposes a documented extension hook
(``on_selection_changed`` / ``selection_changed_callback``) for tickets 1004
and 1005 to attach camera-navigation and colorize-by-category behavior to,
respectively - neither is implemented in this file.

ADDED IN 1004 (T-4, this revision): camera auto-navigation (US-4).
``ClashResult`` now also carries ``link_instance_id`` (the ``ElementId`` of
the ``RevitLinkInstance`` a pair was found against, captured once inside
``run_interference_check`` right where ``link_instance`` is already in
scope) rather than only the display-name string it carried before - re-
deriving "which RevitLinkInstance produced this element" later by re-
searching loaded links and matching on ``link_name`` would be fragile (names
aren't guaranteed unique - Revit only disambiguates same-document instances
with a " : 2" suffix, and a user could rename one) and wasteful (the exact
instance was already known at the moment the ``ClashResult`` was built).
``_combined_host_space_bounding_box`` uses it, via
``resolve_link_instance_by_id``/``resolve_link_document`` (ticket 1002), to
re-resolve the exact ``RevitLinkInstance`` and read its
``GetTotalTransform()`` on demand - never by name-search. That function
computes one combined bounding box, in HOST space, covering both elements of
a ``ClashResult`` - the host element's box is already host-space
(``Element.get_BoundingBox(view)``, per 1001's established "Element boxes
are already world-aligned, unlike Solid.GetBoundingBox()" knowledge); the
link element's box is read in LINK-LOCAL space the same way and then
transformed into host space by running all 8 corners of that local box
through the link's transform - the exact technique ``_outline_for_solid``
below already uses for solids, factored out into a shared
``_transform_all_corners`` helper and reused rather than reimplemented, for
the identical reason: a rotated/mirrored link placement can under-cover the
true extents if only the two extreme corners are transformed.
``reframe_active_view_on_clash`` then reframes the ACTIVE VIEW's camera onto
that combined box via ``UIView.ZoomAndCenterRectangle`` (researched via web
search - see that function's docstring for what was verified vs. what
remains an educated guess) - skipping (with a console note, not a modal
popup, since this fires on every list navigation step) whenever the active
view isn't a ``View3D`` or a bounding box can't be read. Wired to
``ClashListWindow`` via its existing ``selection_changed_callback`` /
``on_selection_changed`` extension hook from ticket 1003 - this file's
navigation logic itself (``_on_list_selection_changed``, ``_set_current_
index``, Next/Previous handlers) is untouched. ``ClashListWindow.__init__``
and ``show_clash_list`` gained one new optional trailing parameter
(``selection_changed_callback``) so the callback can be attached BEFORE the
initial clash (index 0) is auto-selected at window-open time - without this,
the very first clash shown would not trigger a camera move, only subsequent
Next/Previous/click navigation would, which would contradict US-4 for the
common case of a run that finds exactly one clash.

PHASE 7 ROUND 3 FIX (1004, reopened during 1005's review): the wiring
described above originally called ``reframe_active_view_on_clash`` DIRECTLY
from ``__main__``'s ``selection_changed_callback`` closure. That closure is a
WPF event handler on a modeless window and, per the "RESEARCHED-NOT-GUESSED
SUBTLETY" section below (originally written for 1005's colorize checkbox,
but the exact same constraint), only runs inside a valid Revit API execution
context for the very first, synchronously-fired auto-selection - every
subsequent Next/Previous/list-click handler call happens after ``__main__``
has already returned and would throw
``Autodesk.Revit.Exceptions.InvalidOperationException`` the moment it
touched the Revit API. The fix is the same ``ExternalEvent`` bridge 1005
already built for this - see ``_RevitApiBridge`` below (renamed from
``_ColorizeApiBridge`` since it is no longer colorize-specific once 1004
also needs it) - with the camera-reframe call now queued through
``_revit_api_bridge.raise_action(...)`` UNCONDITIONALLY, including what
would have been the still-valid first auto-selected clash, rather than
special-casing "first call is fine, later ones need the bridge."

LIVE-TESTING FIX (reopened again, after Phase 7 round 4 closed this ticket -
see tickets/1004-camera-fly-to-clash.md's "Reopened again - live-testing
gap" section): the tool's actual user, stepping through a real clash list in
Revit 2024.3, reported that the camera reframe alone doesn't tell you WHICH
two elements (out of potentially several visible after the view moves) are
the ones actually clashing - Revit's own Interference Check "Show" button,
which this ticket was built to be "equivalent to," both reframes the camera
AND selects/highlights the clashing pair. The selection half was never
implemented, and three prior review rounds on this ticket never caught the
gap - there was no live Revit session available in this sandbox to actually
look at a reframed view and notice nothing was highlighted in it. Fixed by
adding ``select_clash_pair`` (see the "CAMERA FLY-TO-CLASH" section below),
which builds a host ``Reference`` plus a link-scoped ``Reference`` (via
``Reference(link_element).CreateLinkReference(link_instance)``) and calls
``host_uidoc.Selection.SetReferences([host_reference, link_reference])`` -
the only Revit API surface that can select an element living inside a
linked document (``Selection.SetElementIds`` cannot, since it only accepts
``ElementId`` values meaningful in the host document - the same cross-
document-id limitation ``apply_colorize_overrides`` already had to work
around for graphic overrides, see "ADDED IN 1005" below). Called from
``reframe_active_view_on_clash`` itself, unconditionally, before the
3D-view check - so it runs through the exact same ``_revit_api_bridge``-
queued closure as the camera reframe, satisfying the same valid-API-context
requirement, without needing a second call site or a second bridge queue
entry. Like the camera zoom, this does not need a ``Transaction`` - Revit's
active Selection is transient UI state, not persisted model/view data -
though this was verified on its own rather than assumed purely by analogy,
since ``Selection``/``Reference`` is a different part of the API surface
than ``UIView.ZoomAndCenterRectangle``. See ``select_clash_pair``'s own
docstring for the full source trail.

ADDED IN 1005 (T-5, this revision): colorize-by-category (US-5), via a new
"Colorize clashes by category" checkbox in ``ClashListWindow`` (see
``clashflag_clash_list.xaml``'s ``ColorizeCheckBox``) and its
``colorize_checkbox_checked`` / ``colorize_checkbox_unchecked`` handlers,
NOT the existing per-selection ``on_selection_changed`` hook - per the
ticket, colorizing is a toggle that applies to every clash in the CURRENT
``clash_results`` set at once, not a per-selection-change action, so it
needed its own control rather than piggy-backing on 1004's hook. See the
"COLORIZE BY CATEGORY (T-5 / ticket 1005)" section below for
``apply_colorize_overrides`` / ``clear_colorize_overrides`` and the
category-pair-to-color mapping.

REVISED IN 1008 (T-8): live testing found the category-pair key was
accidentally ORDER-DEPENDENT - ``_category_pair_key`` returned
``(host_category_name, link_category_name)`` as an ordered tuple, so the
same real-world pairing (e.g. Walls + Air Terminals) got a different dict
key, and therefore a different color, depending on which file happened to
be open as host that day. Fixed by sorting the two names before tupling
them (see ``_category_pair_key``'s own docstring). Same ticket also replaced
``_build_category_pair_color_map``'s fixed 10-color palette (cycled by index
over the alphabetically-sorted distinct pairs present - collided once a
model had more than 10 simultaneous distinct pairs, and a pair's color could
shift when a sibling pair started/stopped appearing) with a deterministic
hash of the pair's (now order-independent) key into an HSL hue, fixed
saturation/lightness for legibility - see ``_color_for_category_pair`` and
``_stable_hash_int``'s docstrings for the full reasoning, including why
Python's built-in ``hash()`` was deliberately NOT used (it is salted per-
process via ``PYTHONHASHSEED`` since Python 3.3, which would have silently
broken the "same pair, same color, every run" requirement).

ADDED IN 1009 (T-9): an "Isolate current clash" toggle (US-7), via a new
``IsolateCheckBox`` in ``ClashListWindow`` (see
``clashflag_clash_list.xaml``) and its ``isolate_checkbox_checked`` /
``isolate_checkbox_unchecked`` handlers - see the "ISOLATE CURRENT CLASH"
section below for ``_isolate_host_element`` / ``_exit_temporary_isolate``
(the two ``View.IsolateElementsTemporary`` / ``View.
DisableTemporaryViewMode`` Transaction-wrapped helpers) and
``ClashListWindow._apply_isolate_for_clash`` / ``_clear_isolate_if_active``
(the checkbox lifecycle itself, mirroring 1005's colorize checkbox
lifecycle shape exactly, per the ticket). Unlike colorize (a one-shot
apply-to-the-whole-result-set toggle), Isolate applies to only the CURRENT
clash and must be RE-applied every time the current clash changes while the
toggle stays on - so, per the ticket's explicit instruction, this reuses
ticket 1003/1004's existing ``on_selection_changed`` extension hook
(extended, not duplicated with a second navigation hook) to replace the
isolation on Next/Previous/list-click navigation. Because the link-side
element still can't be isolated (the exact same cross-document API ceiling
1005 already researched for graphic overrides - see "RESEARCHED, NOT
GUESSED - IMPORTANT LIMITATION" just below), turning Isolate on always also
calls ``select_clash_pair`` (T-4/1004) so the link-side element stays
findable inside the still-fully-visible link model. Fully independent of
Colorize (US-5) - neither feature's code reads or writes the other's state.
Every Revit-API-touching call this ticket adds is routed through the
existing ``_revit_api_bridge`` for the same "SECOND RESEARCHED-NOT-GUESSED
SUBTLETY" reason as camera fly-to and colorize - see that section further
below. This session's tool set did not include a web-fetch capability
(unlike 1004/1005/1008), so the exact ``IsolateElementsTemporary``/
``DisableTemporaryViewMode``/``IsInTemporaryViewMode``/``TemporaryViewMode``
API surface used here is drawn from established, previously-verified-in-
production Revit API knowledge rather than a live doc re-fetch this
session - flagged explicitly in the "ISOLATE CURRENT CLASH" section's own
header comment as not independently re-verified THIS session, the same
spirit as this file's other "no live Revit session available" flags, but
for the API-shape question specifically rather than live runtime behavior.

ADDED IN 1010 (T-10): a per-row color swatch in the clash list itself (US-8,
"Legend"), via ``ClashListWindow.__init__``'s item-population loop now adding
``_build_clash_list_row(clash_result)`` (a small ``Border`` swatch + the
existing ``describe()`` label ``TextBlock``, in a horizontal ``StackPanel``)
to ``ClashListBox.Items`` instead of the bare ``clash_result.describe()``
string it used to add - see the "LEGEND SWATCHES" section below (right above
``ClashListWindow``) for ``_wpf_color_for_category_pair``/
``_build_clash_list_row`` themselves. The swatch color is produced by
calling T-8's ``_color_for_category_pair(_category_pair_key(clash_result))``
DIRECTLY (never a re-derived/approximated hash), so the legend can never
show a color that disagrees with what Colorize (T-5) would actually apply -
and it shows what a clash's category pair WOULD colorize to regardless of
whether the Colorize checkbox is currently on, since it's a legend for the
mapping itself, not a live indicator of applied overrides. Purely a
WPF-construction + read-only color lookup addition: no Revit API call, no
``_revit_api_bridge`` involvement, and no ``Transaction`` was needed or
added, and neither the Isolate (1009) nor Colorize (1005) checkbox handlers
were touched. ``ClashListBox.Items`` now holds ``StackPanel`` (a
``UIElement``) entries rather than plain strings, but every piece of
navigation logic that reads from it - ``_on_list_selection_changed``,
``_set_current_index``, ``_current_clash_result`` - keys exclusively off
``ClashListBox.SelectedIndex``, an integer position, and never off the
item's own type or content, so this required no change to any of that
existing logic; see tickets/1010-clash-list-legend-swatches.md's
"Implementation" section for how this was verified.

RESEARCHED, NOT GUESSED - IMPORTANT LIMITATION: this ticket's obvious literal
ask ("apply OverrideGraphicSettings to every host_element AND every
link_element") turns out to be impossible for the link_element half via any
supported Revit API, and this was verified rather than assumed before
writing any of the code below:
    - ``View.SetElementOverrides(ElementId, OverrideGraphicSettings)`` has
      exactly one overload (confirmed against revitapidocs.com for both the
      2022 and 2024 API) - there is no overload accepting a ``LinkElementId``
      or any other cross-document identifier. Its ``elementId`` parameter
      must be "a valid Element identifier" IN THE DOCUMENT THE VIEW BELONGS
      TO (host doc, for the host view this tool uses) - a linked element's
      own ``ElementId`` is only meaningful inside its own (linked) document,
      so passing it here would either throw, or - worse - silently apply the
      override to an unrelated HOST element that happens to reuse the same
      integer id.
    - ``LinkElementId`` IS a real Revit API class/struct (pairs a host-side
      link-instance id with a linked element's id), but it is used for
      selection/reference/tagging APIs (e.g. picking or tagging an element
      inside a link) - NOT for graphic overrides. No override-related method
      anywhere in the API accepts one.
    - The only link-scoped graphic-override API is
      ``View.SetLinkOverrides(ElementId linkId, RevitLinkGraphicsSettings)``
      (new in Revit 2024, confirmed via revitapidocs.com's
      ``RevitLinkGraphicsSettings`` member list) - but that overrides the
      ENTIRE link's display (halftone/by-linked-view/etc, via
      ``LinkVisibilityType`` + ``LinkedViewId``), with no per-element or
      even per-category override surface exposed on the class itself.
    - Confirmed independently by a detailed, specific answer from an
      experienced Autodesk Community "Mentor" (RPTHOMAS108) to the exact
      question "can you override linked element graphics by element from
      the host view, via API": *"Override linked element graphics by
      element in view: No ... The API methods that override colour by
      element take an ElementId that must be contained in the document
      where the view exists ... I believe none of these things are
      currently possible in API."* - matching the UI limitation too (Revit's
      own Visibility/Graphics dialog can't do per-element overrides of
      linked elements either, only per-category or hide-entirely).
    - The only way to make an individual linked element's own graphics
      differ in the host view at all is to open/reuse a VIEW OF THE LINKED
      DOCUMENT ITSELF, call ``SetElementOverrides`` there (valid, since that
      view and that element share a document), and then point the host's
      ``RevitLinkGraphicsSettings`` at that view via
      ``LinkVisibilityType.ByLinkView`` - i.e. write to and depend on a
      persisted view inside a SEPARATE (possibly shared/worked-shared) .rvt
      file, and change the host view's link display mode away from its
      default "by host view" for that whole link (affecting everything about
      how that link displays in this view, not just the clash elements).
      That's a materially more invasive, longer-lived, foreign-document-
      mutating design than a lightweight visualization toggle should be
      doing, and is NOT what this ticket's "toggle on/off, clears on close"
      framing describes - so it was not implemented. See
      ``apply_colorize_overrides``'s docstring and
      tickets/1005-colorize-by-category.md's Implementation section for the
      full writeup and the open design question this leaves for a reviewer/
      spec-owner to weigh in on.

Given the above, this revision colorizes ONLY the HOST-SIDE element of each
clash by its ORDER-INDEPENDENT category pair (see the "REVISED IN 1008" note
above and ``_category_pair_key``) - genuinely correct, transacted, and
toggle-safe - and does NOT attempt any link-side element override. A console
note (`output.print_md`) says so every time colorize is turned on, and the
checkbox's XAML tooltip says so up front, so this isn't a silent gap from the
user's point of view.

SECOND RESEARCHED-NOT-GUESSED SUBTLETY (originally found via 1005's colorize
checkbox, later confirmed to equally affect 1004's camera fly-to - see the
"PHASE 7 ROUND 3 FIX" note above): a modeless ``forms.WPFWindow`` (which
``ClashListWindow`` is, per 1003 - see its class docstring) does NOT run its
later button/checkbox/selection-changed event handlers inside a valid Revit
API "execution context" - the script's own valid context ends when its
``__main__`` block returns, but the window (and its event handlers) keep
firing long after that. Calling a Revit API method that needs a valid
context from one of those handlers - most importantly
``Transaction.Start()/Commit()``, but equally anything else that touches the
Revit API at all (e.g. reading ``Document.ActiveView`` or calling
``UIView.ZoomAndCenterRectangle`` for camera fly-to) - throws
``Autodesk.Revit.Exceptions.InvalidOperationException`` ("Starting a
transaction from an external application running outside of API context is
not allowed"). This was verified via multiple independent sources (a
pyRevit-specific worked example hitting exactly this exception from a
modeless WPFWindow button handler; the general Revit API "External Events"
developer-guide pattern; and pyRevit's own more recent release notes
explicitly adding an "external event helper and modeless" example to
address it) - NOT assumed, because getting this wrong would mean the
colorize checkbox (and, per the round-3 fix, camera fly-to) throws instead
of doing anything the very first time it's used in a real Revit session
(colorize) or on the second and later clash navigations (camera fly-to). The
fix is the standard ``ExternalEvent``/``IExternalEventHandler`` bridge:
``_RevitApiBridge`` (below; named ``_ColorizeApiBridge`` until the round-3
fix made it shared infrastructure for 1004 too) is registered once, at
module-load time (itself inside a valid API context, since that's while
this script's command is actively executing - required by
``ExternalEvent.Create``'s own contract), and every colorize apply/clear
operation AND every camera-reframe call is queued through it
(``raise_action``) instead of being called directly from a
Checked/Unchecked/Closed/selection-changed handler. Revit invokes the
queued action back on the main thread, in a valid context, the next time
it's idle - which in practice (WPF and Revit's own message pump sharing the
same UI thread here) is effectively immediate from the user's perspective.

Deliberately still out of scope (see specs/clash-flag.md "out of scope"):
    - No tolerance / near-miss ("soft clash") logic - hard (real, non-zero-
      volume intersection) clashes only. The small epsilons used below exist
      ONLY to absorb floating-point noise (e.g. two solids that share a face
      exactly) - they are not a clearance/tolerance feature and are not
      user-configurable.
    - pyRevit pushbutton/bundle packaging (ticket 1006) - this is still a
      flat, directly-run script.

Detection and navigation (everything above the "COLORIZE BY CATEGORY"
section) remain READ-ONLY against the model: they only *read* geometry
(FilteredElementCollector, Element.get_Geometry) or compute transient,
in-memory results (SolidUtils.CreateTransformed,
BooleanOperationsUtils.ExecuteBooleanOperation) or transient view pan/zoom
state (``UIView.ZoomAndCenterRectangle`` - not a persisted view property, see
``reframe_active_view_on_clash``'s own docstring) - none of that creates,
deletes, or modifies any element, parameter, or persisted view property, and
the scope picker only reads UI state, so no Transaction is needed for any of
it.

1005's colorize-by-category feature is the FIRST thing in this file that
actually mutates persisted state: ``View.SetElementOverrides`` writes a
persisted, transacted graphic-override property of the view. Per project
ground rules ("Revit API code always wraps mutating operations in a
Transaction, always handles exceptions"), ``apply_colorize_overrides`` and
``clear_colorize_overrides`` (see the "COLORIZE BY CATEGORY" section) each
open their own single, descriptively-named ``Transaction`` around exactly
their batch of ``SetElementOverrides`` calls, with a try/except around the
whole batch that rolls back on failure rather than leaving a half-applied
transaction open.

1009's Isolate toggle is the SECOND: ``View.IsolateElementsTemporary`` /
``View.DisableTemporaryViewMode`` also write persisted (if normally
short-lived) view state - Temporary Isolate mode - and both are documented
as requiring an open, modifiable Transaction, same as colorize's overrides.
See the "ISOLATE CURRENT CLASH" section below for the full reasoning and
its own two Transaction-wrapped helpers.
"""

import colorsys
import hashlib
import os

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

from Autodesk.Revit.DB import (
    BooleanOperationsUtils,
    BooleanOperationsType,
    BuiltInCategory,
    CategoryType,
    Color,
    ElementId,
    ElementMulticategoryFilter,
    FillPatternElement,
    FilteredElementCollector,
    GeometryInstance,
    Options,
    Outline,
    OverrideGraphicSettings,
    Reference,
    RevitLinkInstance,
    Solid,
    SolidUtils,
    TemporaryViewMode,
    Transaction,
    View3D,
    ViewDetailLevel,
    XYZ,
)
from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler
from System.Collections.Generic import List
from System.Windows import (
    FontStyles,
    FontWeights,
    TextWrapping,
    Thickness,
    VerticalAlignment,
)
from System.Windows.Controls import Border, CheckBox, Orientation, StackPanel, TextBlock
# T-10 (ticket 1010): System.Windows.Media.Color/SolidColorBrush for the
# per-row legend swatch. Aliased to `MediaColor` because
# `Autodesk.Revit.DB.Color` (already imported above, plain `Color`) and
# `System.Windows.Media.Color` are two entirely unrelated types that happen
# to share a name - a Revit Color is a 0-255-int-channel struct with no WPF
# meaning at all, and a WPF Color has its own separate 0-255-byte-channel
# representation understood by SolidColorBrush - see
# `_wpf_color_for_category_pair` below for the explicit, byte-by-byte
# conversion between the two (never an implicit cast, since none exists).
from System.Windows.Media import Brushes, Color as MediaColor, SolidColorBrush

from pyrevit import revit, script, forms

output = script.get_output()
doc = revit.doc
# ``revit.uidoc`` is a standard pyrevit.revit module attribute (returns
# __revit__.ActiveUIDocument) - used below (1004) to reach
# UIDocument.GetOpenUIViews() for camera reframing. Resolved once here, same
# as `doc`, rather than re-fetched per call.
uidoc = revit.uidoc


# ---------------------------------------------------------------------------
# Ticket-1001 tracer-bullet scope, KEPT as picker pre-check defaults (per
# ticket 1002 instruction #4: "keep the hardcoded constants as defaults
# pre-checked in the picker UI ... rather than deleting them outright").
#
# Why keep them at all now that the picker makes everything user-driven:
#   - Faster manual testing/dev iteration - one click reproduces the exact
#     scope 1001 was built and reviewed against, instead of re-picking it by
#     hand every time.
#   - A sane "it just works" fallback the first time a user opens the picker
#     on a new model, rather than presenting an all-unchecked form with no
#     guidance on where to start.
# These are no longer used to build the actual run scope directly (that's
# entirely ScopeSelection, produced by the picker) - they're only read by
# ScopePickerWindow to decide which checkboxes start pre-checked.
# ---------------------------------------------------------------------------
HOST_CATEGORY = BuiltInCategory.OST_StructuralFraming
LINK_CATEGORY = BuiltInCategory.OST_DuctCurves

# Default link to pre-check by name, IF a loaded link's name matches. There is
# no live Revit session in this sandbox to read a real link name from, so
# this is a stand-in value - update it to match a RevitLinkInstance name (as
# it appears in the Project Browser / Manage Links) in whatever model this is
# first run against. If no loaded link matches, the picker simply opens with
# no link pre-checked - it's a convenience default, not a requirement.
LINKED_MODEL_INSTANCE_NAME = "NUPCO-STRUCT-LINK.rvt"

# Floating-point noise guards ONLY - NOT a clash tolerance / near-miss feature
# (explicitly out of scope for v1, see specs/clash-flag.md). Both values are
# far smaller than any real-world clash geometry, and exist purely so that
# two solids sharing an exact coincident face (volume/overlap should be
# ~0 but float math may give a hair above or below zero) don't randomly flip
# between "clash" and "no clash" between runs.
BBOX_OVERLAP_TOLERANCE_FEET = 1.0e-6
MIN_CLASH_VOLUME_FEET3 = 1.0e-9

# 1004 (camera fly-to): fraction of each axis's extent to pad the combined
# clash bounding box by, on both sides, before reframing the camera on it -
# NOT a tolerance/clash-detection value (unrelated to the two guards above),
# purely a "don't leave the clash geometry flush against the view edge" UX
# nicety, matching how Revit's own "zoom to fit" style behaviors always
# leave some margin. See _pad_bounding_box().
CAMERA_REFRAME_PADDING_FRACTION = 0.15


class ClashFlagError(Exception):
    """Raised for ClashFlag-specific setup failures (as opposed to letting a
    raw Revit API exception surface uncaught)."""
    pass


def _link_display_name(link_instance):
    """Best-effort human-readable name for a RevitLinkInstance, used both by
    the picker (checkbox labels) and by error messages after the picker has
    closed. Revit disambiguates multiple loaded instances of the same link
    document with a " : 2", " : 3", ... suffix on Name, so this also happens
    to make distinct instances of the same underlying link tellable apart in
    the UI - see the multi-instance note on ScopeSelection below.
    """
    try:
        name = link_instance.Name
    except Exception:
        name = None
    if name:
        return name
    try:
        return "<unnamed linked model, id {0}>".format(link_instance.Id.IntegerValue)
    except Exception:
        return "<unnamed linked model>"


def resolve_link_instance_by_id(host_doc, link_element_id):
    """Re-resolve a RevitLinkInstance from its ElementId at run time.

    Replaces the old name-based find_link_instance() lookup: the picker
    (ScopePickerWindow, below) already has live RevitLinkInstance objects in
    hand while it's open - it builds its own list straight from a
    FilteredElementCollector - but the ScopeSelection it hands back carries
    ElementIds, not the .NET objects themselves, and this function re-fetches
    the actual element from `host_doc` right before it's used. Re-resolving
    by id here (rather than just holding onto the object reference the
    picker already had) means run_interference_check() never depends on a
    closed WPF dialog's fields still holding valid Revit API references, and
    it matches what ticket 1002 explicitly asks for ("by ElementId, not just
    name, since the picker will have concrete instances in hand").
    """
    element = host_doc.GetElement(link_element_id)
    if not isinstance(element, RevitLinkInstance):
        raise ClashFlagError(
            "Selected link (id {0}) is no longer a valid RevitLinkInstance in "
            "the active document - it may have been deleted since the scope "
            "picker was shown. Re-run ClashFlag.".format(
                link_element_id.IntegerValue
            )
        )
    return element


def resolve_link_document(link_instance):
    """Return the loaded Document for `link_instance`, raising
    ClashFlagError if it isn't currently loaded (we need the linked document
    actually loaded/resolvable to read its geometry). The picker only offers
    checkboxes for links that were loaded when it opened, but a link can in
    principle be unloaded between then and now, so this is still checked
    here rather than assumed.
    """
    link_doc = link_instance.GetLinkDocument()
    if link_doc is None:
        raise ClashFlagError(
            "Linked model '{0}' is not currently loaded (unloaded/unresolved "
            "link) - it may have been unloaded since the scope picker was "
            "shown. Load the link and re-run.".format(
                _link_display_name(link_instance)
            )
        )
    return link_doc


def describe_element(element):
    """Short human-readable description: category - family/type or name."""
    category_name = "<no category>"
    if element.Category is not None:
        category_name = element.Category.Name

    type_name = None
    try:
        elem_type = element.Document.GetElement(element.GetTypeId())
        if elem_type is not None:
            type_name = elem_type.Name
    except Exception:
        type_name = None

    if not type_name:
        try:
            type_name = element.Name
        except Exception:
            type_name = "<unnamed>"

    return "{0} - {1}".format(category_name, type_name)


def _iter_solids(geometry_element):
    """Recursively yield every non-degenerate ``Solid`` inside a
    ``GeometryElement`` (or nested ``GeometryInstance``), in whatever
    coordinate space that geometry object itself is already expressed in -
    this function does NOT transform anything, it only walks/flattens.

    Why recursion is required: a family-based element (many structural
    framing families, duct fittings/accessories, curtain wall panels/mullions,
    etc.) commonly nests its real solids one or more levels deep inside
    ``GeometryInstance`` objects representing the placed family symbol, rather
    than exposing ``Solid`` objects directly at the top level. Only reading
    the top-level GeometryElement would silently return zero solids - and
    therefore zero clashes - for those elements. ``GeometryInstance.
    GetInstanceGeometry()`` returns that nested geometry already placed into
    the SAME space as its parent (no extra transform bookkeeping needed here).

    Zero-volume solids (annotation-only geometry, curves/points-only
    representations, or degenerate leftovers from a failed void cut) are
    skipped here so callers never have to special-case them - a solid with
    (near-)zero volume cannot participate in a real geometric clash.
    """
    for geo_obj in geometry_element:
        if isinstance(geo_obj, Solid):
            try:
                has_volume = geo_obj.Volume > MIN_CLASH_VOLUME_FEET3
            except Exception:
                has_volume = False
            if has_volume and geo_obj.Faces.Size > 0:
                yield geo_obj
        elif isinstance(geo_obj, GeometryInstance):
            try:
                nested_geometry = geo_obj.GetInstanceGeometry()
            except Exception:
                nested_geometry = None
            if nested_geometry is not None:
                for nested_solid in _iter_solids(nested_geometry):
                    yield nested_solid
        # Other GeometryObject subtypes (Curve, Mesh, PolyLine, Profile, ...)
        # can't participate in a solid boolean intersection - ignored.


def _build_category_filter(categories):
    """Build a single ElementFilter matching ANY category in `categories`
    (a non-empty list of BuiltInCategory).

    Uses ``ElementMulticategoryFilter``'s ``ICollection<BuiltInCategory>``
    constructor (a single "multi-category" filter) rather than building one
    single-category ``ElementCategoryFilter`` per category and OR-ing them
    together with a ``LogicalOrFilter``. Both give the same "match any of
    these categories" result; ``ElementMulticategoryFilter`` is preferred
    here because:
      - It's the class the Revit API provides specifically for this exact
        "match any of N categories" case - no need to hand-roll OR logic
        Revit already implements natively for it. (``ElementCategoryFilter``
        itself only ever matches a single category/ElementId - it has no
        collection-accepting constructor at all.)
      - It stays one ElementMulticategoryFilter object all the way through,
        rather than a LogicalOrFilter wrapping N sub-filters - simpler to
        construct and pass around, with no behavioral difference for our
        purposes.
    The constructor doesn't require more than one entry, so this same code
    path handles both a single selected category and many - no special-case
    branch needed for "exactly one category".
    """
    if not categories:
        raise ClashFlagError(
            "collect_candidate_solids() was called with an empty category "
            "list - nothing to filter for."
        )
    category_collection = List[BuiltInCategory](categories)
    return ElementMulticategoryFilter(category_collection)


def collect_candidate_solids(source_doc, categories, link_transform=None):
    """Collect (element, [solids...]) pairs for every element whose category
    is IN `categories` (a non-empty list of BuiltInCategory - see
    _build_category_filter) in `source_doc`, with each solid ALREADY in host
    coordinate space.

    - When `link_transform` is None (host-side call): elements come straight
      from the active document, so their geometry is already in host space -
      no transform is applied.
    - When `link_transform` is given (link-side call): `source_doc` is the
      linked document, so every Solid pulled from it is still in LINK-LOCAL
      coordinate space at the point `_iter_solids` returns it. Each such
      solid is converted to host space here, in this function, via
      ``SolidUtils.CreateTransformed(solid, link_transform)`` -
      `link_transform` is `RevitLinkInstance.GetTotalTransform()`, which maps
      link-local -> host. After this call returns, every solid in the result
      (host or link candidates alike) is in host coordinate space, so all
      downstream code (bbox pre-filter, boolean ops) can treat them
      uniformly and never needs to know which side an element came from.

    Elements that end up with zero usable solids (annotation-only, geometry-
    less, or every solid on them failed to transform) are omitted entirely -
    they cannot clash with anything and would just be dead weight in the
    O(n*m) pairing loop below.
    """
    candidates = []
    skipped_elements = 0

    options = Options()
    options.ComputeReferences = False
    options.IncludeNonVisibleObjects = False
    # Some families only generate full solid geometry at finer detail levels
    # (a coarse-detail symbol can be a simplified/empty representation) -
    # force Fine so we don't silently under-detect geometry that's really
    # there at the level Revit would render/check natively.
    options.DetailLevel = ViewDetailLevel.Fine

    collector = FilteredElementCollector(source_doc).WherePasses(
        _build_category_filter(categories)
    ).WhereElementIsNotElementType()

    for element in collector:
        try:
            geometry = element.get_Geometry(options)
        except Exception:
            geometry = None

        if geometry is None:
            skipped_elements += 1
            continue

        try:
            raw_solids = list(_iter_solids(geometry))
        except Exception:
            skipped_elements += 1
            continue

        if not raw_solids:
            skipped_elements += 1
            continue

        if link_transform is None:
            # Host side: raw_solids are already host-space. Nothing to do.
            host_space_solids = raw_solids
        else:
            # Link side: raw_solids are LINK-LOCAL at this point. Transform
            # each one into host space individually (per-solid, per ticket
            # instructions) rather than transforming the whole element's
            # bounding box, so multi-solid elements (curtain walls, families
            # with several geometry objects) are each handled correctly even
            # under rotation/mirroring, where naive corner-only bbox
            # transforms can under- or over-estimate extents.
            host_space_solids = []
            for link_local_solid in raw_solids:
                try:
                    host_space_solid = SolidUtils.CreateTransformed(
                        link_local_solid, link_transform
                    )
                except Exception:
                    # A single malformed/non-transformable solid shouldn't
                    # sink the whole element - skip just that solid.
                    continue
                if host_space_solid is not None and host_space_solid.Volume > MIN_CLASH_VOLUME_FEET3:
                    host_space_solids.append(host_space_solid)

        if not host_space_solids:
            skipped_elements += 1
            continue

        candidates.append((element, host_space_solids))

    return candidates, skipped_elements


def _transform_all_corners(local_min, local_max, local_to_target_transform):
    """Return (target_min, target_max) - two ``XYZ`` points describing the
    smallest axis-aligned box, in the TARGET space, that fully contains the
    axis-aligned box [local_min, local_max] from some LOCAL space, given the
    ``Transform`` that maps local -> target.

    Transforms all 8 corners of the local box (not just the two extreme
    corners `local_min`/`local_max` themselves) before re-deriving min/max.
    This matters whenever `local_to_target_transform` can carry rotation or
    mirroring (a rotated/mirrored link placement, or a Solid's own local bbox
    frame - see both call sites of this function below): running only the
    two extreme corners through such a transform does NOT produce a valid
    axis-aligned box around the transformed content - it can under-cover it.
    Originally written inline in ``_outline_for_solid`` (below) for the
    per-solid pre-filter pipeline; factored out here (1004) so
    ``_combined_host_space_bounding_box`` can reuse the exact same,
    already-reviewed technique for link-element bounding boxes instead of
    re-deriving a parallel (and possibly subtly different/wrong) version of
    it.
    """
    xs, ys, zs = [], [], []
    for x in (local_min.X, local_max.X):
        for y in (local_min.Y, local_max.Y):
            for z in (local_min.Z, local_max.Z):
                corner = local_to_target_transform.OfPoint(XYZ(x, y, z))
                xs.append(corner.X)
                ys.append(corner.Y)
                zs.append(corner.Z)

    target_min = XYZ(min(xs), min(ys), min(zs))
    target_max = XYZ(max(xs), max(ys), max(zs))
    return target_min, target_max


def _outline_for_solid(solid):
    """Return an ``Outline`` (axis-aligned box) for `solid`, expressed in
    whatever space `solid`'s own geometry is already in (by the time this is
    called, that's always host space - see collect_candidate_solids).

    Gotcha this guards against: ``Solid.GetBoundingBox()`` does NOT return a
    box already in the solid's space. Per the Revit API docs, it returns a
    ``BoundingBoxXYZ`` whose Min/Max corners are in the box's OWN local
    frame, plus a separate ``.Transform`` that maps that local frame into the
    solid's actual space - this is explicitly different from
    ``Element.BoundingBox``, which IS already identity/world-aligned. Using
    `bbox.Min` / `bbox.Max` directly (skipping `bbox.Transform`) would
    silently produce a box in the wrong space.

    A second, subtler trap: `bbox.Transform` can include rotation (this
    happens routinely for linked solids we've just rotated into host space).
    Transforming only the Min and Max corners through a rotated transform
    does NOT give a valid axis-aligned box around the rotated solid - it can
    under-cover it, causing the pre-filter to wrongly discard a real
    clash. The fix (delegated to ``_transform_all_corners``) is to transform
    all 8 corners of the local box and take the min/max of the transformed
    set.
    """
    try:
        bbox = solid.GetBoundingBox()
    except Exception:
        return None

    if bbox is None:
        return None

    world_min, world_max = _transform_all_corners(bbox.Min, bbox.Max, bbox.Transform)

    try:
        return Outline(world_min, world_max)
    except Exception:
        return None


def solids_clash(solid_a, solid_b):
    """Confirm a REAL (non-zero-volume) intersection between two solids that
    are both already known to be in the same coordinate space (host space).

    Boolean operations can throw on some legitimate-looking solid inputs
    (coincident/self-intersecting faces, short-curve-tolerance edge cases,
    etc.) - per the ticket, this is wrapped defensively so one bad geometry
    pair doesn't abort the whole run; it's treated as "not a confirmed clash"
    rather than a hard failure, since we can't tell from here whether it
    would have clashed.
    """
    try:
        result_solid = BooleanOperationsUtils.ExecuteBooleanOperation(
            solid_a, solid_b, BooleanOperationsType.Intersect
        )
    except Exception:
        return False

    if result_solid is None:
        return False

    try:
        return result_solid.Volume > MIN_CLASH_VOLUME_FEET3
    except Exception:
        return False


def find_clashing_pairs(host_candidates, link_candidates):
    """Given (element, [host-space solids]) lists for both sides, return the
    list of (host_element, link_element) pairs with at least one confirmed
    solid-solid clash.

    Every solid handled from this point on - host or link-derived - is
    already in host coordinate space (guaranteed by collect_candidate_solids),
    so this function never needs to think about link transforms again; it
    only needs to keep host-space boxes/solids straight from each other,
    which they already are.

    Pre-filter: for every (host solid, link solid) pair, first check
    axis-aligned Outline overlap (cheap) before ever calling into the
    boolean-operation engine (comparatively expensive) - this is the
    bbox-overlap pre-filter the ticket calls for, done at the SOLID level
    (not the whole-element level) so a multi-solid element like a curtain
    wall doesn't get pulled into an expensive check against every other
    candidate just because ONE of its many mullion/panel solids happens to
    sit near something.

    A given element pair is only reported once even if several of their
    respective solids clash (matches the previous version's one-line-per-
    element-pair output).
    """
    clashing_pairs = []
    reported_pair_ids = set()

    for host_element, host_solids in host_candidates:
        host_outlines = []
        for host_solid in host_solids:
            outline = _outline_for_solid(host_solid)
            if outline is not None:
                host_outlines.append((host_solid, outline))

        if not host_outlines:
            continue

        for link_element, link_solids in link_candidates:
            pair_key = (host_element.Id.IntegerValue, link_element.Id.IntegerValue)
            if pair_key in reported_pair_ids:
                continue

            found_clash_for_pair = False

            for link_solid in link_solids:
                link_outline = _outline_for_solid(link_solid)
                if link_outline is None:
                    continue

                for host_solid, host_outline in host_outlines:
                    if not host_outline.Intersects(link_outline, BBOX_OVERLAP_TOLERANCE_FEET):
                        continue

                    if solids_clash(host_solid, link_solid):
                        found_clash_for_pair = True
                        break

                if found_clash_for_pair:
                    break

            if found_clash_for_pair:
                reported_pair_ids.add(pair_key)
                clashing_pairs.append((host_element, link_element))

    return clashing_pairs


# ---------------------------------------------------------------------------
# SCOPE PICKER (T-2 / ticket 1002)
# ---------------------------------------------------------------------------

def _enumerate_present_categories(target_doc):
    """Yield (BuiltInCategory, display_name) pairs for every Model-type
    category that actually has at least one placed (non-type) element in
    `target_doc`.

    Restricted to ``CategoryType.Model`` categories (walls, structural
    framing, ducts, pipes, etc.) - deliberately excludes annotation/
    analytical/internal categories, which can't meaningfully participate in
    a solid-geometry clash check.

    Categories that don't correspond to a real ``BuiltInCategory`` enum
    member (custom/user-defined categories - these always have a
    non-negative ElementId, unlike every built-in category, which is
    negative by construction) are skipped: this tool's category filtering is
    built entirely on ``ElementMulticategoryFilter(ICollection<BuiltInCategory>)``
    (see ``_build_category_filter``), so a category we can't express that
    way can't be offered as a checkbox option here either. This mirrors an
    existing limitation from ticket 1001 (which also only ever dealt in
    BuiltInCategory) rather than introducing a new one - full custom-category
    support would need ElementId-based filtering throughout and is tracked
    as a possible future ticket, not solved here.

    Existence is checked with
    ``FilteredElementCollector(...).OfCategoryId(...).WhereElementIsNotElementType()
    .FirstElement()`` - a fast, indexed quick-filter per candidate category -
    rather than walking every element in the document once and reading its
    `.Category` property, which would mean one full linear pass over
    potentially the entire (federated) model just to populate a picker list.
    """
    seen_built_in_categories = set()

    for category in target_doc.Settings.Categories:
        if category.CategoryType != CategoryType.Model:
            continue

        category_id_value = category.Id.IntegerValue
        if category_id_value >= 0:
            # Non-negative ids are custom/user categories, not BuiltInCategory
            # members - every real BuiltInCategory has a negative underlying
            # value. Skip before even attempting the enum cast below.
            continue

        try:
            built_in_category = BuiltInCategory(category_id_value)
        except Exception:
            continue

        if built_in_category in seen_built_in_categories:
            continue

        has_instance = FilteredElementCollector(target_doc) \
            .OfCategoryId(category.Id) \
            .WhereElementIsNotElementType() \
            .FirstElement() is not None
        if not has_instance:
            continue

        seen_built_in_categories.add(built_in_category)
        yield built_in_category, category.Name


class ScopeSelection(object):
    """Everything run_interference_check() needs, produced by the scope
    picker instead of the old fixed module-level constants.

    - host_categories: list[BuiltInCategory] - checked once, applies to the
      active (host) document only.
    - link_selections: list[(ElementId, list[BuiltInCategory])] - one entry
      per checked, loaded RevitLinkInstance the user selected, each carrying
      its OWN independently-checked category list. Host-side and link-side
      category selections are kept logically separate on purpose (per ticket
      1002): a user might check "Ducts" on a link without wanting "Ducts"
      checked on the host side too, and if more than one DISTINCT link is
      checked (in scope - 0003 requires supporting several loaded links per
      run), each one can have its own different category subset.

    Multi-instance note: because links are identified by ElementId (one
    checkbox per RevitLinkInstance) rather than by name, two separately
    loaded INSTANCES of the very same underlying link document naturally show
    up here as two independent entries, each free to be checked/categorized
    on its own and each given its own transform in run_interference_check().
    This falls out of the ElementId-based design rather than being
    deliberately engineered for it - ticket 1001 explicitly called
    multi-instance-of-the-same-link out of scope, and this hasn't been
    exercised against a real multi-instance model (no live Revit session in
    this sandbox), so treat it as unverified, not as a supported feature.
    """

    def __init__(self, host_categories, link_selections):
        self.host_categories = host_categories
        self.link_selections = link_selections


class _LinkPickerEntry(object):
    """Bookkeeping for one link's block of UI controls. Built and torn down
    entirely in Python (not static XAML) because the number of loaded links,
    and the number of categories available in each, isn't known until the
    active document is actually inspected at picker-open time."""

    def __init__(self, link_instance, link_checkbox, category_checkboxes, categories_panel):
        self.link_instance = link_instance
        self.link_checkbox = link_checkbox
        self.category_checkboxes = category_checkboxes  # list[(CheckBox, BuiltInCategory)]
        self.categories_panel = categories_panel  # StackPanel, enabled/disabled with link_checkbox


class ScopePickerWindow(forms.WPFWindow):
    """Modal pre-run scope picker (US-1 / ticket 1002).

    Modal (``ShowDialog``, WPFWindow's normal behavior) rather than modeless:
    this window's entire job is to gate what run_interference_check() does,
    so the check genuinely cannot start until the user has confirmed a scope
    (or cancelled) - there's no case here where the user needs to keep
    interacting with the Revit model while this stays open, which is the
    usual reason to reach for modeless instead.

    Every checkbox is built here in code, not in the (deliberately empty)
    XAML panels, because the categories present and the links loaded are
    both a property of whatever document is active when the picker opens -
    they can't be known ahead of time.
    """

    def __init__(self, xaml_file_path, host_doc):
        forms.WPFWindow.__init__(self, xaml_file_path)
        self.host_doc = host_doc

        self.host_category_checkboxes = []  # list[(CheckBox, BuiltInCategory)]
        self.link_entries = []  # list[_LinkPickerEntry]

        self.confirmed = False
        self.result = None  # ScopeSelection, set only when confirmed

        # T-11 (ticket 1011) fix: `run_button_click` is wired to the XAML
        # `Click=` event, so (per tickets/1011-fix-event-handler-globals-
        # crash.md's root-cause writeup) its `func_globals` is broken and a
        # bare `forms` reference there would raise
        # IronPython.Runtime.UnboundNameException - captured here, in
        # __init__ (not delegate-wired, so it has this module's real
        # globals), and read back via `self._forms` there instead.
        self._forms = forms

        self._build_host_categories_ui()
        self._build_links_ui()

    def _build_host_categories_ui(self):
        for built_in_category, display_name in _enumerate_present_categories(self.host_doc):
            checkbox = CheckBox()
            checkbox.Content = display_name
            checkbox.Margin = Thickness(2, 2, 2, 2)
            # Pre-check the ticket-1001 hardcoded default so the picker still
            # runs "out of the box" with one click - see the HOST_CATEGORY
            # comment near the top of this file for why the old constants
            # are kept at all.
            checkbox.IsChecked = (built_in_category == HOST_CATEGORY)
            checkbox.Tag = built_in_category
            self.HostCategoriesStack.Children.Add(checkbox)
            self.host_category_checkboxes.append((checkbox, built_in_category))

    def _build_links_ui(self):
        link_instances = list(
            FilteredElementCollector(self.host_doc).OfClass(RevitLinkInstance)
        )

        if not link_instances:
            note = TextBlock()
            note.Text = "No linked models are loaded in the active document."
            note.TextWrapping = TextWrapping.Wrap
            note.Margin = Thickness(4)
            self.LinksStack.Children.Add(note)
            return

        for link_instance in link_instances:
            self._build_one_link_block(link_instance)

    def _build_one_link_block(self, link_instance):
        display_name = _link_display_name(link_instance)
        link_doc = link_instance.GetLinkDocument()
        is_loaded = link_doc is not None

        container = StackPanel()
        container.Margin = Thickness(2, 4, 2, 10)

        link_checkbox = CheckBox()
        link_checkbox.FontWeight = FontWeights.Bold
        link_checkbox.IsEnabled = is_loaded
        # Pre-check the ticket-1001 default link, matched by name - same
        # "faster testing / sane fallback" reasoning as the host category
        # default above. Only ever pre-checks if a currently-loaded link's
        # name actually matches; otherwise the picker opens with no link
        # pre-checked, which is fine (still requires an explicit user choice).
        default_checked = is_loaded and (LINKED_MODEL_INSTANCE_NAME in display_name)
        link_checkbox.IsChecked = default_checked
        link_checkbox.Content = (
            display_name if is_loaded
            else "{0}  (not loaded - cannot select categories)".format(display_name)
        )
        container.Children.Add(link_checkbox)

        categories_panel = StackPanel()
        categories_panel.Margin = Thickness(20, 2, 0, 0)
        categories_panel.IsEnabled = default_checked
        container.Children.Add(categories_panel)

        category_checkboxes = []
        if is_loaded:
            for built_in_category, cat_display_name in _enumerate_present_categories(link_doc):
                checkbox = CheckBox()
                checkbox.Content = cat_display_name
                checkbox.Margin = Thickness(2, 1, 2, 1)
                checkbox.IsChecked = default_checked and (built_in_category == LINK_CATEGORY)
                checkbox.Tag = built_in_category
                categories_panel.Children.Add(checkbox)
                category_checkboxes.append((checkbox, built_in_category))
        else:
            note = TextBlock()
            note.Text = "Link not loaded - load it to pick categories."
            note.FontStyle = FontStyles.Italic
            note.Margin = Thickness(2)
            categories_panel.Children.Add(note)

        entry = _LinkPickerEntry(link_instance, link_checkbox, category_checkboxes, categories_panel)
        self.link_entries.append(entry)

        # Toggle the category sub-panel's enabled state together with the
        # link checkbox, purely for UX clarity (an unchecked link's
        # categories are ignored at collection time in run_button_click
        # regardless of this visual state). `entry=entry` is the standard
        # default-argument trick to bind the CURRENT loop value into the
        # closure, dodging Python's usual late-binding-in-loops gotcha.
        def _on_link_toggled(sender, args, entry=entry):
            entry.categories_panel.IsEnabled = bool(entry.link_checkbox.IsChecked)

        link_checkbox.Checked += _on_link_toggled
        link_checkbox.Unchecked += _on_link_toggled

        self.LinksStack.Children.Add(container)

    def run_button_click(self, sender, args):
        # T-11 (ticket 1011) fix: this method is wired to the XAML `Click=`
        # event, so its `func_globals` is broken (see tickets/1011-fix-
        # event-handler-globals-crash.md) - `forms` is read from `self.
        # _forms` (captured in __init__, which is unaffected) via this
        # local, instead of referenced bare.
        show_forms = self._forms

        host_categories = [
            built_in_category
            for checkbox, built_in_category in self.host_category_checkboxes
            if checkbox.IsChecked
        ]

        link_selections = []
        for entry in self.link_entries:
            if not entry.link_checkbox.IsChecked:
                continue
            selected_categories = [
                built_in_category
                for checkbox, built_in_category in entry.category_checkboxes
                if checkbox.IsChecked
            ]
            if selected_categories:
                link_selections.append((entry.link_instance.Id, selected_categories))

        if not host_categories:
            show_forms.alert(
                "Pick at least one host category before running.",
                title="ClashFlag - scope picker",
            )
            return

        if not link_selections:
            show_forms.alert(
                "Pick at least one loaded link, and at least one category on "
                "it, before running.",
                title="ClashFlag - scope picker",
            )
            return

        self.result = ScopeSelection(host_categories, link_selections)
        self.confirmed = True
        self.Close()

    def cancel_button_click(self, sender, args):
        self.confirmed = False
        self.result = None
        self.Close()


def show_scope_picker(host_doc):
    """Show the modal T-2 scope picker and return a ScopeSelection, or None
    if the user cancelled (including closing the window itself, e.g. via
    Escape or the title-bar close button - `confirmed` only ever flips to
    True from inside run_button_click)."""
    xaml_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "clashflag_scope_picker.xaml"
    )
    picker = ScopePickerWindow(xaml_path, host_doc)
    picker.ShowDialog()
    return picker.result if picker.confirmed else None


# ---------------------------------------------------------------------------
# CLASH LIST PANEL (T-3 / ticket 1003)
# ---------------------------------------------------------------------------

class ClashResult(object):
    """One confirmed clash pair, flattened for the T-3 list panel.

    A single ClashFlag run can check the host against several distinct
    selected links (``ScopeSelection.link_selections``), and until this
    ticket each link's ``clashing_pairs`` only ever existed as a local list
    inside ``run_interference_check``'s loop body, printed to the console and
    then discarded - there was nowhere a single ordered sequence of "every
    clash from this run" lived for a UI to display/navigate. ``ClashResult``
    plus the flat list built in ``run_interference_check`` fills that gap.

    Fields:
    - host_element: the clashing ``Element`` from the active (host) document.
    - link_element: the clashing ``Element`` from the LINKED document, in
      whatever state ``find_clashing_pairs`` returned it in - this class only
      carries it for display/navigation (``describe_element``), it does not
      re-derive or store any transformed geometry.
    - link_name: display name (``_link_display_name``) of the
      ``RevitLinkInstance`` this pair was found against. Carried alongside
      the pair (rather than assumed) because a single run can check multiple
      distinct links, so the panel needs to say which link each row came
      from - the pair alone (two Elements) doesn't disambiguate that once
      flattened across links.
    - link_instance_id (added 1004): the ``ElementId`` of that SAME
      ``RevitLinkInstance`` - the object itself is already in scope right
      where ``run_interference_check`` builds each ``ClashResult`` (as
      ``link_instance``, resolved once per selected link via
      ``resolve_link_instance_by_id``), so it's captured here rather than
      left for a later consumer (ticket 1004's camera fly-to) to re-derive by
      searching loaded links and matching on `link_name`. Matching on a
      display name would be fragile - names aren't guaranteed unique (only
      same-document repeat instances get a " : 2"-style Revit-assigned
      suffix; a user can still rename links to collide) - and wasteful,
      re-doing a lookup whose answer was already known at creation time.
      Re-resolving the live ``RevitLinkInstance`` from this id (rather than
      holding onto the object reference itself) is intentional and mirrors
      ticket 1002's existing ``link_element_id`` -> ``resolve_link_instance_
      by_id`` pattern: it keeps ``ClashResult`` from depending on a specific
      .NET object reference staying valid/meaningful for as long as the
      modeless clash list window stays open, across whatever else happens in
      the Revit session meanwhile.
    """

    def __init__(self, host_element, link_element, link_name, link_instance_id):
        self.host_element = host_element
        self.link_element = link_element
        self.link_name = link_name
        self.link_instance_id = link_instance_id

    def describe(self):
        """One-line display string for this clash, used as a ListBox row in
        ClashListWindow. Reuses describe_element() for both sides, same as
        the existing per-link console reporting below, so the panel and the
        console output describe elements identically."""
        return "Host: {0}   <->   Link [{1}]: {2}".format(
            describe_element(self.host_element),
            self.link_name,
            describe_element(self.link_element),
        )


# ---------------------------------------------------------------------------
# CAMERA FLY-TO-CLASH + SELECTION HIGHLIGHT (T-4 / ticket 1004)
#
# The selection half (select_clash_pair, below) was added after a live-
# testing report on a real Revit 2024.3 session, following this file's
# fourth Phase 7 review pass on this ticket - see the module docstring's
# "LIVE-TESTING FIX" section and tickets/1004-camera-fly-to-clash.md's
# "Reopened again - live-testing gap" section for the full story.
# ---------------------------------------------------------------------------

def _pad_bounding_box(box_min, box_max, fraction):
    """Expand the axis-aligned box [box_min, box_max] outward by `fraction`
    of each axis's own extent, on both sides.

    Not part of the ticket's literal ask - a small, low-risk UX addition (in
    the same spirit as ticket 1003's StatusText/button-enabled additions) so
    a reframed clash's own geometry doesn't end up sitting exactly flush
    against the edge of the view, matching how Revit's built-in "zoom to
    fit"-style behaviors (e.g. ``UIDocument.ShowElements``) always leave some
    margin rather than fitting edge-to-edge.

    Degenerates gracefully for a zero/near-zero-size axis (e.g. a clash
    between two nearly coplanar/flat elements, where one axis of the combined
    box has ~0 extent) by falling back to a small fixed 1-foot pad on that
    axis instead of `0 * fraction == 0`, so ``ZoomAndCenterRectangle`` below
    is never handed a degenerate (zero-thickness on every axis normal to the
    view) rectangle.
    """
    mins = (box_min.X, box_min.Y, box_min.Z)
    maxs = (box_max.X, box_max.Y, box_max.Z)

    padded_min = []
    padded_max = []
    for lo, hi in zip(mins, maxs):
        extent = hi - lo
        pad = extent * fraction
        if pad <= 0:
            pad = 1.0
        padded_min.append(lo - pad)
        padded_max.append(hi + pad)

    return XYZ(*padded_min), XYZ(*padded_max)


def _combined_host_space_bounding_box(clash_result, host_doc, active_view):
    """Compute one combined (min_xyz, max_xyz) bounding box, in HOST
    coordinate space, covering BOTH elements of `clash_result` - the pair
    the camera should reframe on for US-4.

    - `clash_result.host_element` is already in host space (it's a live
      element of the active document). Per ticket 1001's established
      knowledge (see ``_outline_for_solid``'s docstring above),
      ``Element.get_BoundingBox(view)`` - unlike ``Solid.GetBoundingBox()`` -
      returns a box whose Min/Max are already expressed directly in that
      element's own document's coordinate system, with no separate
      local-frame ``Transform`` step to worry about. For the HOST element,
      that coordinate system already IS host space. `active_view` (the
      active 3D view) is passed through, matching the standard "zoom to
      element in view X" call pattern - it must be a view belonging to
      `host_doc` (a Revit API requirement of this overload), which the
      active view of `host_doc` always is.
    - `clash_result.link_element` lives in the LINKED document, so by the
      same Element-bbox reasoning its own ``get_BoundingBox()`` result is
      already expressed directly in THAT document's coordinate system - which
      is LINK-LOCAL space, not host space. It is read with a ``None`` view
      argument (there is no view of the link's own document to pass - the
      active view belongs to `host_doc`, and passing a `host_doc` view for an
      element of a different document is not a supported combination), then
      transformed into host space here via the link's
      ``RevitLinkInstance.GetTotalTransform()``, using ``_transform_all_
      corners`` - the SAME "transform all 8 corners, not just 2" technique
      ``_outline_for_solid`` already uses for solids, reused rather than
      reimplemented, for the identical reason: a rotated/mirrored link
      placement can under-cover the true extents if only the two extreme
      corners are transformed.

    The `RevitLinkInstance` is re-resolved from `clash_result.
    link_instance_id` via ``resolve_link_instance_by_id``/``resolve_link_
    document`` (ticket 1002) rather than trusting `clash_result.link_element`
    alone to still make sense - this also gets us a specific, actionable
    ``ClashFlagError`` (e.g. "link no longer loaded") if the link was
    unloaded/removed since the run that found this clash, instead of a bare
    bounding-box read failure with no explanation.

    Returns None (not an exception) if a bounding box specifically can't be
    read for either element (e.g. get_BoundingBox returning None) - that is
    not really an error case ClashFlagError's user-facing wording fits, just
    "nothing to reframe on this time." Raises ClashFlagError (propagated,
    uncaught) if the link itself can no longer be resolved/loaded - the
    caller (``reframe_active_view_on_clash``) catches that specifically so it
    can report the precise reason.
    """
    try:
        host_bbox = clash_result.host_element.get_BoundingBox(active_view)
    except Exception:
        host_bbox = None
    if host_bbox is None:
        return None

    link_instance = resolve_link_instance_by_id(
        host_doc, clash_result.link_instance_id
    )
    # Raises ClashFlagError if the link is no longer loaded - checked here
    # (not just left to a get_BoundingBox() failure below) purely so the
    # caller gets a specific, actionable message rather than a silent None.
    resolve_link_document(link_instance)

    try:
        link_bbox = clash_result.link_element.get_BoundingBox(None)
    except Exception:
        link_bbox = None
    if link_bbox is None:
        return None

    # Link-local -> host, for THIS specific RevitLinkInstance - same choice
    # (GetTotalTransform over GetTransform, to fold in true-north) as
    # run_interference_check() makes for the detection pipeline itself.
    link_transform = link_instance.GetTotalTransform()
    link_host_min, link_host_max = _transform_all_corners(
        link_bbox.Min, link_bbox.Max, link_transform
    )

    host_min, host_max = host_bbox.Min, host_bbox.Max
    combined_min = XYZ(
        min(host_min.X, link_host_min.X),
        min(host_min.Y, link_host_min.Y),
        min(host_min.Z, link_host_min.Z),
    )
    combined_max = XYZ(
        max(host_max.X, link_host_max.X),
        max(host_max.Y, link_host_max.Y),
        max(host_max.Z, link_host_max.Z),
    )
    return combined_min, combined_max


def select_clash_pair(clash_result, host_doc, host_uidoc):
    """Select/highlight BOTH elements of `clash_result` in the Revit UI - the
    host element directly, and the link element via a link-scoped
    ``Reference`` - so the user can actually tell WHICH two elements (out of
    potentially many visible once the camera reframes) are the ones really
    clashing. This is the other half of "equivalent to Revit's built-in
    Interference Check 'Show' button": that button both reframes the camera
    AND selects/highlights the clashing pair - only the reframe half was
    ever implemented here.

    LIVE-TESTING GAP, NOT A REVIEW MISS (see tickets/1004-camera-fly-to-
    clash.md's "Reopened again - live-testing gap" section): three prior
    Phase 7 review rounds on this ticket read and re-verified
    ``reframe_active_view_on_clash`` and its "equivalent to Show" framing
    without ever flagging that the selection half was missing, because there
    was no live Revit session available in this sandbox to actually look at
    a reframed view and notice nothing was highlighted in it. It surfaced
    only when the tool's real user stepped through an actual clash list in
    Revit 2024.3 and could not tell which two elements, among everything
    else visible after the camera moved, were the reported clash.

    API CHOICE - RESEARCHED, NOT GUESSED: selecting an element that lives in
    a LINKED document, from the host view/document, is NOT expressible via
    ``Selection.SetElementIds`` - that method only accepts ``ElementId``
    values meaningful in the host document, and a linked element's own
    ``ElementId`` is only meaningful inside its own (linked) document (the
    exact same cross-document-id trap ``apply_colorize_overrides`` already
    had to work around for graphic overrides - see this module's "ADDED IN
    1005" docstring section). The mechanism actually used here:
        host_reference = Reference(host_element)
        link_reference = Reference(link_element).CreateLinkReference(link_instance)
        host_uidoc.Selection.SetReferences([host_reference, link_reference])
    Verified via multiple independent sources, not just assumed from a
    single writeup:
      - ``Reference(Element)`` - a real constructor on
        ``Autodesk.Revit.DB.Reference``, confirmed via revitapidocs.com's
        Reference Constructor page.
      - ``Reference.CreateLinkReference(RevitLinkInstance)`` - confirmed via
        revitapidocs.com's own CreateLinkReference method page ("Creates a
        new reference to an object found in a linked document, from a
        reference to that same object obtained by looking directly in the
        linked document") and independently via Jeremy Tammik's Building
        Coder ("Conversion of a Geometric Reference in a Linked RVT Model").
      - ``Selection.SetReferences(IList<Reference>)`` - confirmed via
        revitapidocs.com's Selection Methods page ("Selects the references.
        The references can be an element or a subelement in the host or a
        linked document.") AND a separate, independent worked example
        (SharpBIM, "Highlight elements from a linked document") building
        this EXACT host-reference-plus-CreateLinkReference-converted-link-
        reference pattern to highlight a linked element from the host UI.
        Selecting a linked-document reference this way was added in the
        Revit 2023 API - already satisfied by this tool's Revit 2024.3
        target, but worth a second look if this file is ever back-ported to
        an older Revit version.

    NO TRANSACTION: like ``ZoomAndCenterRectangle`` (see
    ``reframe_active_view_on_clash``'s own "NO TRANSACTION" note below), the
    active Selection is transient Revit UI state, not a persisted model or
    view property - confirmed rather than assumed purely by analogy:
    independent Revit-API discussion of ``Selection.SetElementIds``/
    ``SetReferences`` describes both as only ever changing what's
    highlighted in the UI, never touching the model, so - like the camera
    zoom - no ``Transaction`` is opened here. (This IS a different part of
    the API surface than ``ZoomAndCenterRectangle`` - a ``UIView`` viewport
    method vs. a ``UIDocument.Selection`` method - so this was checked on
    its own rather than treated as automatically true "because zoom didn't
    need one either.")

    CALLER'S RESPONSIBILITY - VALID API CONTEXT: same requirement as every
    other Revit-API-touching function in this file (see
    ``reframe_active_view_on_clash``'s own note on this) - this function
    must only ever run from inside a ``_revit_api_bridge``-queued closure,
    never called directly from a ``ClashListWindow`` WPF handler.

    Returns True if the selection was set, False if it failed (e.g. the host
    element, the link element, or the link instance itself was deleted/
    unloaded since the run that found this clash) - reported via
    ``output.print_md``, never raised, so a stale reference can't abort the
    reframe half of this action too.
    """
    try:
        link_instance = resolve_link_instance_by_id(
            host_doc, clash_result.link_instance_id
        )
    except ClashFlagError as link_error:
        output.print_md(
            "_ClashFlag: could not select the clashing pair - {0}_".format(
                link_error
            )
        )
        return False

    try:
        host_reference = Reference(clash_result.host_element)
        link_reference = Reference(clash_result.link_element).CreateLinkReference(
            link_instance
        )
    except Exception as reference_error:
        output.print_md(
            "_ClashFlag: could not build a selection reference for this "
            "clash (an element may have been deleted since the run that "
            "found it): {0}_".format(reference_error)
        )
        return False

    try:
        host_uidoc.Selection.SetReferences(
            List[Reference]([host_reference, link_reference])
        )
    except Exception as selection_error:
        output.print_md(
            "_ClashFlag: could not select the clashing pair: {0}_".format(
                selection_error
            )
        )
        return False

    return True


def reframe_active_view_on_clash(clash_result, host_doc, host_uidoc):
    """Reframe the ACTIVE view's camera onto the combined bounding box of
    `clash_result`'s two clashing elements, AND select/highlight both
    clashing elements (see ``select_clash_pair`` above) - together, the
    camera-fly-to-and-highlight behavior from US-4 / ticket 1004, equivalent
    to what Revit's built-in Interference Check dialog's "Show" button does
    for a found clash. (The selection half was added after the camera-only
    version of this function had already been through three Phase 7 review
    rounds - see ``select_clash_pair``'s "LIVE-TESTING GAP" docstring note
    for why, and tickets/1004-camera-fly-to-clash.md's "Reopened again"
    section for the live-testing report that caught it.)

    Selection and reframe are two independent steps run back-to-back here,
    not one all-or-nothing operation: selecting doesn't require a 3D view
    (unlike the camera reframe below) and a failure in one half (e.g. a
    deleted element for selection, or no open 3D `UIView` for the reframe)
    must not silently prevent the other half from still doing its part - so
    ``select_clash_pair`` is called first, unconditionally, before the
    3D-view check that can skip the reframe half entirely. Both this
    function's own call site (``__main__``'s ``_reframe`` closure) and this
    function itself treat "select and reframe" as ONE queued bridge action
    (see the "CALLER'S RESPONSIBILITY" note below) even though the two steps
    inside it can succeed/fail independently of each other.

    CALLER'S RESPONSIBILITY - VALID API CONTEXT (Phase 7 round 3 fix; applies
    equally to the ``select_clash_pair`` call this function makes): this
    function itself assumes it is already running inside a valid Revit API
    execution context - it does not, and cannot, establish one. Every call
    site (``__main__``'s ``_on_clash_selection_changed`` closure) MUST queue
    the call through ``_revit_api_bridge.raise_action(...)`` rather than
    invoking this function directly from a ``ClashListWindow`` selection-
    changed handler, which runs OUTSIDE a valid context - see the module
    docstring's "SECOND RESEARCHED-NOT-GUESSED SUBTLETY" section for why.
    This function's own exception handling (try/except around
    ``ClashFlagError`` and the general zoom failure, both reported via
    ``output.print_md`` and returning False rather than propagating) is
    unaffected by being called from inside ``_RevitApiBridge.Execute()``
    instead of directly - it never raises out of itself either way, so
    ``Execute()``'s own outer try/except around each queued action is just a
    backstop, not something this function relies on. ``select_clash_pair``
    has this exact same property (never raises, reports via
    ``output.print_md``) for the same reason.

    Returns True if the CAMERA was reframed, False if that half was skipped
    (reported via ``output.print_md`` - a one-line console note, NOT a modal
    ``forms.alert`` - this runs on every clash-list navigation step, and a
    popup on every click would be far more disruptive than a console line
    the user can ignore while stepping through the list). This return value
    reflects the reframe outcome only - ``select_clash_pair``'s own
    True/False result is intentionally not folded into it (this function's
    callers, per ticket 1004, only ever care about the reframe outcome; the
    selection call already reports its own failures independently via
    ``output.print_md``, exactly like every other soft-failure in this
    function).

    ACTIVE-VIEW-NOT-3D HANDLING (ticket instruction #4): if the active view
    is not a ``View3D`` (covers "no active view" too, since None also fails
    the isinstance check), camera reframing is skipped entirely - it does
    NOT switch the user to some other 3D view, or create one. Silently
    changing the user's active view as a side effect of clicking a clash-list
    row would be more disruptive than just not moving the camera, and
    "which" 3D view to use if none is active is an ambiguous, unrequested
    design decision (the built-in Interference Check "Show" button has the
    same constraint - it reframes whatever 3D view is already open/active,
    it doesn't manufacture one). The user is expected to have a 3D view
    active before relying on fly-to-clash.

    API CHOICE - RESEARCHED, NOT GUESSED (see tickets/1004-camera-fly-to-
    clash.md's "Implementation" section for the full source trail):
    ``UIView.ZoomAndCenterRectangle(viewCorner1, viewCorner2)`` is used, with
    the two (padded) corners of the combined bounding box, in MODEL
    coordinates. Verified against revitapidocs.com's method description
    ("Zoom and center the view to a specified rectangle", both parameters
    documented as being in model coordinates) AND a real, working pyRevit-
    forum example doing exactly this "zoom the active view to an element's
    bounding box" pattern (``get_BoundingBox()`` -> ``ZoomAndCenterRectangle
    (min, max)``, no extra transform beyond the one already applied to get
    into model/host space). Chosen over two other candidates considered:
      - ``View3D.SetSectionBox`` - rejected because it CROPS the view (a
        persisted, visible view-state change - confirmed via revitapidocs.com
        that ``SetSectionBox`` changes what geometry the view displays and
        would need ``IsSectionBoxActive`` managed and a ``Transaction``,
        since it writes a view parameter) rather than just moving the
        camera to look at something - a materially more invasive, longer-
        lived effect than the native "Show" button produces, and would still
        be showing a cropped model after the user closes the clash list.
      - Manually computing a new ``ViewOrientation3D`` (eye position/forward/
        up vector) - rejected as substantially more failure-prone (has to
        derive a correct eye distance from the box size plus the view's
        field of view/aspect ratio by hand) for no behavioral benefit over a
        method the API already provides for exactly "fit the view to this
        rectangle."

    UNVERIFIED / FLAG FOR REVIEWER: search also turned up a forum report of
    "strange"/aspect-ratio-related ``ZoomAndCenterRectangle`` behavior in
    some 3D-view scenarios, and neither source that was found distinguishes
    PERSPECTIVE (camera) 3D views from ORTHOGRAPHIC 3D views specifically -
    the working forum example didn't state which kind it used. This has NOT
    been exercised against a live Revit session in this sandbox (none is
    available here). If it visibly misbehaves specifically on a perspective/
    camera 3D view during first real testing, the fallback is either to
    require an orthographic 3D view, or to switch to the manual
    ``ViewOrientation3D`` approach noted above.

    NO TRANSACTION: this only changes the transient on-screen pan/zoom state
    of an already-open ``UIView`` window - the same kind of change a user
    causes by scrolling/zooming with the mouse wheel. It does not create,
    delete, or modify any element, parameter, or persisted view property in
    either document, so no ``Transaction`` is opened here, consistent with
    the rest of this file's read-only design (see the module docstring).
    """
    # Select/highlight the clashing pair FIRST, unconditionally - this does
    # not require a 3D view (unlike the camera reframe below) and its
    # success/failure is independent of whether the reframe itself goes on
    # to succeed - see this function's own "Selection and reframe are two
    # independent steps" docstring paragraph above and select_clash_pair's
    # docstring for the full research trail on why this fixes a genuine,
    # live-testing-caught gap against the "equivalent to Show button" goal.
    select_clash_pair(clash_result, host_doc, host_uidoc)

    active_view = host_doc.ActiveView
    if not isinstance(active_view, View3D):
        output.print_md(
            "_ClashFlag: active view is not a 3D view - skipping camera "
            "reframe for this clash. Switch to a 3D view to use camera "
            "fly-to._"
        )
        return False

    try:
        combined_box = _combined_host_space_bounding_box(
            clash_result, host_doc, active_view
        )
    except ClashFlagError as combine_error:
        output.print_md("_ClashFlag: {0}_".format(combine_error))
        return False

    if combined_box is None:
        output.print_md(
            "_ClashFlag: could not read a bounding box for one or both "
            "elements in this clash - skipping camera reframe._"
        )
        return False

    padded_min, padded_max = _pad_bounding_box(
        combined_box[0], combined_box[1], CAMERA_REFRAME_PADDING_FRACTION
    )

    target_uiview = None
    for open_uiview in host_uidoc.GetOpenUIViews():
        if open_uiview.ViewId == active_view.Id:
            target_uiview = open_uiview
            break

    if target_uiview is None:
        output.print_md(
            "_ClashFlag: the active 3D view isn't open in any on-screen "
            "window (no matching UIView) - skipping camera reframe._"
        )
        return False

    try:
        target_uiview.ZoomAndCenterRectangle(padded_min, padded_max)
    except Exception as zoom_error:
        output.print_md("_ClashFlag: camera reframe failed: {0}_".format(zoom_error))
        return False

    return True


# Kept alive here purely to prevent .NET/CLR garbage collection of an open
# ClashListWindow. Unlike ScopePickerWindow (opened with the blocking
# ShowDialog(), which keeps its own frame alive on the call stack until
# closed), ClashListWindow is opened with the non-blocking Show() - the
# script's __main__ block finishes executing (and its local variables go out
# of scope) almost immediately after show_clash_list() returns, while the
# ---------------------------------------------------------------------------
# REVIT API BRIDGE (originally built for T-5 / ticket 1005's colorize
# checkbox; renamed and reused, unchanged in mechanism, for T-4 / ticket
# 1004's camera fly-to as of the Phase 7 round 3 fix - see the module
# docstring's "PHASE 7 ROUND 3 FIX" and "SECOND RESEARCHED-NOT-GUESSED
# SUBTLETY" sections)
# ---------------------------------------------------------------------------
#
# Kept physically next to the "COLORIZE BY CATEGORY" section below (rather
# than moved elsewhere in the file) since that is still where most of its
# call sites live; it is no longer colorize-specific in what it does.
#
# See the module docstring's "ADDED IN 1005" section for the full research
# trail on why colorize only touches HOST-side elements, not link-side ones -
# short version: there is no supported Revit API to override the graphics of
# an individual linked-document element, scoped to just that element, from a
# view in the host document (verified against revitapidocs.com's
# View.SetElementOverrides / RevitLinkGraphicsSettings docs AND an
# experienced Autodesk Community answer directly addressing this exact
# question - not assumed). That research is unrelated to the bridge itself.

class _RevitApiBridge(IExternalEventHandler):
    """Revit ``ExternalEvent`` bridge back into a valid API context for any
    Revit-API-touching work queued from OUTSIDE one - currently
    ``ClashListWindow``'s colorize checkbox handlers (1005) AND ticket 1004's
    camera-reframe-on-selection-change callback (as of the Phase 7 round 3
    fix; originally named ``_ColorizeApiBridge`` and colorize-only before
    that). See the module docstring's "SECOND RESEARCHED-NOT-GUESSED
    SUBTLETY" section for why this is required at all (a modeless
    WPFWindow's own event handlers - including ``ClashListWindow``'s
    selection-changed handler, not just its checkbox handlers - run OUTSIDE
    a valid Revit API context, so calling ``Transaction.Start()`` or any
    other Revit API method directly from one throws).

    Usage: call ``raise_action(some_zero_arg_callable)`` from anywhere
    (typically a WPF event handler); Revit invokes that callable back via
    ``Execute()`` at its next idle opportunity, on the main thread, inside a
    valid API context. Actions are queued (a list, not a single slot) so two
    calls to ``raise_action`` in quick succession - e.g. a colorize toggle
    and a clash-selection change landing around the same moment, or two
    separate ``ClashListWindow`` instances from two ClashFlag runs both
    doing so - can't silently overwrite/drop each other; ``Execute()``
    drains and runs every queued action, in order, each time Revit calls it.

    Exactly ONE instance of this class is created, at MODULE LOAD time (see
    ``_revit_api_bridge`` below) - required, not incidental:
    ``ExternalEvent.Create()`` itself must be called from a valid API
    context, and module load time (this script actively executing as a
    pyRevit command) is exactly that; constructing it lazily from inside a
    later, invalid-context event handler would defeat the whole point.
    """

    def __init__(self):
        self._pending_actions = []
        self.external_event = ExternalEvent.Create(self)

    def raise_action(self, action):
        self._pending_actions.append(action)
        self.external_event.Raise()

    def Execute(self, uiapp):
        pending_actions, self._pending_actions = self._pending_actions, []
        for action in pending_actions:
            try:
                action()
            except Exception as bridge_error:
                output.print_md(
                    "_ClashFlag: a queued action failed inside the API-"
                    "context bridge: {0}_".format(bridge_error)
                )

    def GetName(self):
        return "ClashFlag - Revit API bridge"


# Created once, at module load - see the class docstring for why the timing
# matters. Held at module scope (like `_open_clash_list_windows`) so it
# survives past this script's own __main__ returning, for as long as any
# ClashListWindow it's wired to stays open. Shared by both 1005's colorize
# checkbox handlers and 1004's camera-reframe-on-selection-change callback
# (as of the Phase 7 round 3 fix) - NOT a separate instance per feature; one
# bridge, one ExternalEvent, one queue is sufficient and simpler than two.
_revit_api_bridge = _RevitApiBridge()


# Fixed saturation/lightness for every hash-derived category-pair color (see
# `_color_for_category_pair`) - chosen so the resulting RGB stays legible
# against Revit's default white view background in BOTH the Wireframe style
# (where only the thin projection/cut line color is visible - too light and
# it disappears into white) and the Shaded style (where the color fills an
# entire face - too dark or too saturated reads as visually harsh/muddy
# across a whole model). Fixed rather than randomized/per-pair, per US-5's
# "zero configuration" requirement - only the HUE varies per pair.
_CATEGORY_PAIR_SATURATION = 0.62
_CATEGORY_PAIR_LIGHTNESS = 0.45


def _category_name_for_colorize(element):
    """Category display name used as one half of a colorize pair key - same
    "<no category>" fallback text describe_element() uses, so an element
    without a Category still gets a deterministic, groupable key instead of
    raising."""
    if element.Category is not None:
        return element.Category.Name
    return "<no category>"


def _category_pair_key(clash_result):
    """Stable, ORDER-INDEPENDENT dict key for one clash's category pair.

    Returns the host-side and link-side category names as a sorted 2-tuple,
    NOT in (host, link) order - see CONTEXT.md's "Category Pair" glossary
    entry. Which category lands on "host" vs. "link" is purely an accident
    of which file happened to be open as host that day, not anything about
    the real-world clash - a Walls/Air-Terminals clash must produce the same
    key (and therefore the same color) whichever side is host. Keeping the
    two names in natural (host, link) order, as an earlier version of this
    function did, was exactly this bug: the same pairing got two different
    dict keys - and two different colors - depending on host/link direction.
    """
    return tuple(sorted([
        _category_name_for_colorize(clash_result.host_element),
        _category_name_for_colorize(clash_result.link_element),
    ]))


def _stable_hash_int(text):
    """Deterministic hash of `text` into a non-negative int, stable across
    processes, runs, and machines - unlike Python's built-in `hash()`, which
    (for str, since Python 3.3's hash randomization / PYTHONHASHSEED) is
    salted per-process specifically to make it UNPREDICTABLE run-to-run.
    Using the builtin here would silently violate US-5's "same pair, same
    color, every run" requirement - two engineers (or two sessions) could see
    different colors for the identical Walls/Air-Terminals pairing. MD5 over
    the UTF-8 encoded text is a pure function of its input bytes only, with
    no such salt, and is more than adequate here since this is a visual
    bucketing aid, not a security or uniqueness guarantee.
    """
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _color_for_category_pair(pair_key):
    """Deterministic Color for an order-independent category pair key (see
    `_category_pair_key`), derived by hashing the pair directly into a hue
    rather than looking one up in a small fixed, hand-picked palette.

    The two category names are joined with a separator character ("|") that
    is vanishingly unlikely to appear inside a Revit category display name,
    so e.g. ("Air Terminals", "Walls") hashes as a single distinct string
    rather than accidentally colliding with some other pair whose names
    happen to concatenate the same way. The resulting hash mod 360 gives a
    hue; fixed `_CATEGORY_PAIR_SATURATION`/`_CATEGORY_PAIR_LIGHTNESS`
    constants (see their own comment) supply the rest of an HLS color, which
    `colorsys.hls_to_rgb` converts to 0.0-1.0 float RGB. Values are clamped
    into [0, 255] before rounding to guard against float rounding pushing a
    channel a hair outside that range (e.g. 255.00000000001).

    This has no fixed "number of colors" ceiling the way the old cycled
    10-color palette did - it degrades gracefully (two unrelated pairs can
    still land on similar-looking hues by chance, same as any hash-based
    bucketing) rather than deterministically colliding past a hard-coded
    count, and needs no stored/persisted table: it is a pure function of the
    pair's own name, recomputed fresh every call, per US-5's
    zero-configuration requirement.
    """
    pair_text = "|".join(pair_key)
    hue_degrees = _stable_hash_int(pair_text) % 360
    hue_fraction = hue_degrees / 360.0
    red, green, blue = colorsys.hls_to_rgb(
        hue_fraction, _CATEGORY_PAIR_LIGHTNESS, _CATEGORY_PAIR_SATURATION
    )

    def _to_byte(channel):
        return int(round(max(0.0, min(1.0, channel)) * 255))

    return Color(_to_byte(red), _to_byte(green), _to_byte(blue))


def _build_category_pair_color_map(clash_results):
    """Deterministic, order-independent category-pair -> Color map.

    Each distinct pair's Color (`_color_for_category_pair`) is a PURE
    function of that pair's own sorted name alone - never of which other
    pairs are present in `clash_results`, how many there are, or what order
    they happen to appear in. This replaces the old approach (collect
    distinct pairs, sort them alphabetically, and cycle a fixed 10-color
    palette by index), which meant a pair's color could change simply
    because a DIFFERENT pair started or stopped appearing in the result set
    (shifting everyone's index), and which silently collided once a model
    had more than 10 distinct pairs at once. Hashing each pair independently
    into the full hue space has no such ceiling and needs no stored table -
    the same pair name always hashes to the same color, in any model, on any
    run, with zero configuration.
    """
    distinct_pairs = set(_category_pair_key(cr) for cr in clash_results)
    return {pair: _color_for_category_pair(pair) for pair in distinct_pairs}


def _find_solid_fill_pattern_id(host_doc):
    """Return the ElementId of a solid DRAFTING fill pattern in `host_doc`,
    or None if one can't be found. Every out-of-the-box Revit template ships
    one ("<Solid fill>"), but a deliberately stripped-down project template
    might not - callers must tolerate None (skip the surface-pattern half of
    the override, keep the line-color half) rather than assume this always
    succeeds.
    """
    for fill_pattern_element in FilteredElementCollector(host_doc).OfClass(FillPatternElement):
        try:
            fill_pattern = fill_pattern_element.GetFillPattern()
        except Exception:
            continue
        if fill_pattern is not None and fill_pattern.IsSolidFill:
            return fill_pattern_element.Id
    return None


def _colorize_settings_for(color, solid_fill_pattern_id):
    """Build one OverrideGraphicSettings that renders as `color` regardless
    of the active view's visual style.

    Sets BOTH the projection/cut line color (the only thing visible in a
    Wireframe or Hidden Line view style) AND the surface+cut foreground
    pattern (a solid fill in `color`, when a solid pattern was found - the
    dominant visual in a Shaded/Realistic view style, where a shaded solid's
    rendered face color would otherwise drown out a thin projection line).
    Camera fly-to (1004) reframes on a 3D view, which is commonly Shaded or
    Realistic, so relying on line color alone would make this toggle look
    like it did nothing for most users.
    """
    settings = OverrideGraphicSettings()
    settings.SetProjectionLineColor(color)
    settings.SetCutLineColor(color)
    if solid_fill_pattern_id is not None:
        settings.SetSurfaceForegroundPatternColor(color)
        settings.SetSurfaceForegroundPatternId(solid_fill_pattern_id)
        settings.SetCutForegroundPatternColor(color)
        settings.SetCutForegroundPatternId(solid_fill_pattern_id)
    return settings


def apply_colorize_overrides(clash_results, host_doc, active_view):
    """Apply a per-category-pair (order-independent - see `_category_pair_key`)
    color override to every HOST-SIDE element across `clash_results`, in
    `active_view`. See this module's "COLORIZE BY CATEGORY" section header
    comment (and the module docstring's "ADDED IN 1005" section) for why
    link-side elements are deliberately NOT touched here.

    Returns a dict {ElementId.IntegerValue: OverrideGraphicSettings} - the
    PRE-EXISTING override for every host element this call touches, captured
    via `active_view.GetElementOverrides(...)` BEFORE this function changes
    anything. `clear_colorize_overrides` uses this to restore exactly what
    was there before, rather than blanket-clearing every override on these
    elements - so a manual override the user had already set up on one of
    these elements (before ever touching the ClashFlag colorize checkbox)
    survives a colorize on/off cycle intact. Keyed by `ElementId.
    IntegerValue` (a plain int) rather than the ElementId object itself so
    the result is a plain, unambiguously-hashable dict.

    A single host element can appear in more than one ClashResult (e.g. one
    beam clashing against two different linked ducts) - its pre-colorize
    override is captured only the FIRST time it's encountered here, so a
    later ClashResult for the same element doesn't wrongly "snapshot" this
    function's own already-applied override as if it were the user's
    original one. Re-applying an override to the same element more than once
    is harmless - whichever ClashResult for it is processed last simply
    determines its final color.

    Opens exactly one Transaction ("ClashFlag: colorize by category") for
    the whole batch - a single logical user action ("turn colorize on"), not
    one transaction per element - with the whole loop wrapped in a
    try/except that rolls back on any failure rather than leaving a half-
    applied transaction open, per project ground rules.
    """
    color_map = _build_category_pair_color_map(clash_results)
    solid_fill_pattern_id = _find_solid_fill_pattern_id(host_doc)

    previous_overrides = {}

    transaction = Transaction(host_doc, "ClashFlag: colorize by category")
    transaction.Start()
    try:
        for clash_result in clash_results:
            host_element = clash_result.host_element
            id_key = host_element.Id.IntegerValue

            if id_key not in previous_overrides:
                previous_overrides[id_key] = active_view.GetElementOverrides(host_element.Id)

            pair_color = color_map[_category_pair_key(clash_result)]
            active_view.SetElementOverrides(
                host_element.Id,
                _colorize_settings_for(pair_color, solid_fill_pattern_id),
            )
    except Exception:
        transaction.RollBack()
        raise
    else:
        transaction.Commit()

    return previous_overrides


def clear_colorize_overrides(host_doc, view, previous_overrides):
    """Restore every host element touched by `apply_colorize_overrides` back
    to whatever `OverrideGraphicSettings` it had immediately before colorize
    was turned on (`previous_overrides`, keyed by `ElementId.IntegerValue` -
    see that function's docstring) - NOT a blanket "remove all overrides",
    so a pre-existing manual override on one of these elements survives a
    colorize on/off cycle. Elements never touched by colorize are never
    referenced here at all, so unrelated overrides elsewhere in the view
    (anything the user set up themselves, outside ClashFlag) are untouched
    by construction.

    `view` MUST be the same View instance/id that `apply_colorize_overrides`
    was called against, not necessarily whatever is active NOW - overrides
    are per-view state, so clearing on a different view than the one that
    was actually colorized would both fail to clean up the real target and
    risk stamping an unrelated view with a stale snapshot. Callers
    (`ClashListWindow.colorize_checkbox_unchecked`, and the Closed-event
    cleanup in `show_clash_list`) are responsible for remembering which view
    id colorize was applied to and re-resolving that exact View here - see
    those call sites.

    Silently skips (does not raise) an id that can no longer be resolved to
    an element - it may have been deleted from the model since colorize was
    turned on, in which case there is nothing left to restore an override
    onto and that's not an error worth interrupting the rest of the clear
    operation over.

    Opens exactly one Transaction ("ClashFlag: clear colorize overrides")
    for the whole batch, same reasoning as `apply_colorize_overrides`.
    """
    transaction = Transaction(host_doc, "ClashFlag: clear colorize overrides")
    transaction.Start()
    try:
        for id_int_value, previous_settings in previous_overrides.items():
            element_id = ElementId(id_int_value)
            try:
                view.SetElementOverrides(element_id, previous_settings)
            except Exception:
                continue
    except Exception:
        transaction.RollBack()
        raise
    else:
        transaction.Commit()


# ---------------------------------------------------------------------------
# ISOLATE CURRENT CLASH (T-9 / ticket 1009)
#
# US-7: an opt-in "Isolate" toggle that hides everything in the active view
# except the CURRENT clash's host-side element, and always also runs Select
# (select_clash_pair, above, from T-4/1004) so the un-isolatable link-side
# element stays findable. Moving to a different clash while Isolate is on
# REPLACES the isolation; turning it off, or closing the panel while it's
# on, restores full visibility. See ClashListWindow.isolate_checkbox_checked/
# _unchecked and _apply_isolate_for_clash/_clear_isolate_if_active (below,
# in the "CLASH LIST PANEL" section) for the checkbox lifecycle itself -
# mirrors 1005's colorize checkbox lifecycle shape exactly, per the ticket.
# Only the two small Transaction-wrapped helper functions live up here,
# next to the other Revit-API-touching helpers this file already has.
# ---------------------------------------------------------------------------
#
# API CHOICE - RECALLED FROM ESTABLISHED REVIT API KNOWLEDGE, FLAGGED AS NOT
# INDEPENDENTLY RE-VERIFIED THIS SESSION: unlike tickets 1004/1005/1008 (which
# had WebFetch/WebSearch tools available to cross-check revitapidocs.com and
# forum sources live), this session's tool set does not include a web-fetch
# capability - there is no way to independently re-confirm these exact method
# names/signatures against a live doc page from inside this sandbox. What
# follows is based on well-established, previously-verified-in-production
# Revit API surface (the same "temporary hide/isolate" API used by countless
# real add-ins, including code the author has personally shipped before):
#   - ``View.IsolateElementsTemporary(ICollection<ElementId> elementIds)`` -
#     puts the view into Temporary Isolate mode showing ONLY the given
#     elements. Calling it AGAIN while the view is already in that mode
#     REPLACES the isolated set with the new one - it does not accumulate
#     across calls. This is exactly the "moving to a different clash
#     replaces the isolation, never accumulates" behavior US-7 asks for, and
#     is why re-isolating for a newly-current clash needs no separate
#     "clear, then re-apply" step - see _isolate_host_element's own
#     docstring below.
#   - ``View.IsInTemporaryViewMode(TemporaryViewMode temporaryViewMode)`` -
#     returns whether the view currently has that specific temporary mode
#     active.
#   - ``View.DisableTemporaryViewMode(TemporaryViewMode temporaryViewMode)`` -
#     exits that mode, restoring full visibility. Per this same established
#     knowledge, calling this for a mode the view is NOT currently in raises
#     rather than silently no-op-ing - which is why _exit_temporary_isolate
#     below guards with IsInTemporaryViewMode first, not fire-and-catch.
#   - ``TemporaryViewMode.TemporaryHideIsolate`` - the specific enum member
#     covering BOTH Temporary Hide and Temporary Isolate (the same mode
#     Revit's own View Control Bar "Temporary Hide/Isolate" flyout drives) -
#     used consistently for both the apply and clear calls below, since a
#     mode can only be disabled with the exact member it was enabled under.
# TRANSACTED, NOT TRANSIENT UI STATE: unlike ``UIView.ZoomAndCenterRectangle``
# or ``Selection.SetReferences`` (both confirmed, in the "CAMERA FLY-TO-CLASH"
# section above, to be transient on-screen state needing no Transaction),
# Temporary Isolate mode is a persisted (if normally short-lived) piece of
# VIEW state - it survives a document save until explicitly cleared, and
# both enabling and disabling it are documented as requiring an open,
# modifiable Transaction (attempting either outside one raises
# ``InvalidOperationException``, the same family of exception the module
# docstring's "SECOND RESEARCHED-NOT-GUESSED SUBTLETY" section already
# describes for other Revit API calls made outside a valid context/
# transaction). Both helpers below therefore open their own single,
# descriptively-named Transaction, with a try/except that rolls back on
# failure rather than leaving a half-applied transaction open, per project
# ground rules - exactly like ``apply_colorize_overrides``/
# ``clear_colorize_overrides`` already do for their own single-batch
# Transactions.
# ---------------------------------------------------------------------------


def _isolate_host_element(host_doc, view, host_element_id):
    """Put `view` into Temporary Isolate mode showing ONLY `host_element_id`
    - the "hides everything ... except the current clash's host-side
    element" half of US-7. Only ever called with a HOST-document element id
    (the link-side element can't be isolated this way at all - same Revit
    API ceiling this module's colorize section already researched for
    graphic overrides; Select is what keeps the link-side element findable
    instead - see select_clash_pair above).

    Safe to call again for a DIFFERENT `host_element_id` while `view` is
    already in Temporary Isolate mode from a previous call - per this
    section's header comment, ``IsolateElementsTemporary`` replaces the
    isolated set rather than accumulating it, so navigating to a new clash
    while Isolate is on can just call this again for the new clash's host
    element with no separate "clear first" step.
    """
    id_list = List[ElementId]([host_element_id])
    transaction = Transaction(host_doc, "ClashFlag: isolate current clash")
    transaction.Start()
    try:
        view.IsolateElementsTemporary(id_list)
    except Exception:
        transaction.RollBack()
        raise
    else:
        transaction.Commit()


def _exit_temporary_isolate(host_doc, view):
    """Exit Temporary Isolate mode on `view`, restoring full visibility -
    the "turning Isolate off ... immediately restores the full view" half
    of US-7. Guards with ``IsInTemporaryViewMode`` first (see this section's
    header comment for why) so this is a true no-op - no Transaction even
    opened - when `view` isn't actually in that mode (e.g. a user manually
    exited it via Revit's own View Control Bar while ClashFlag's checkbox
    was still checked; or a redundant call from a second near-simultaneous
    clear, though ``ClashListWindow._clear_isolate_if_active``'s own
    ``isolate_active`` guard already prevents that particular case from
    reaching here at all).
    """
    if not view.IsInTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate):
        return
    transaction = Transaction(host_doc, "ClashFlag: exit isolate mode")
    transaction.Start()
    try:
        view.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate)
    except Exception:
        transaction.RollBack()
        raise
    else:
        transaction.Commit()


# Kept alive here purely to prevent .NET/CLR garbage collection of an open
# ClashListWindow. Unlike ScopePickerWindow (opened with the blocking
# ShowDialog(), which keeps its own frame alive on the call stack until
# closed), ClashListWindow is opened with the non-blocking Show() - the
# script's __main__ block finishes executing (and its local variables go out
# of scope) almost immediately after show_clash_list() returns, while the
# window itself is still meant to stay open. Without holding a reference
# somewhere that survives past script end, the window object would become
# eligible for collection and could disappear/misbehave out from under the
# user. Entries remove themselves on Closed (see show_clash_list) so this
# doesn't grow unbounded across repeated runs in the same pyRevit session.
_open_clash_list_windows = []


# ---------------------------------------------------------------------------
# LEGEND SWATCHES (T-10 / ticket 1010)
#
# US-8: a small color swatch next to each ClashListBox row, showing what
# color that clash's category pair WOULD colorize to (via T-8's
# order-independent, hash-based `_color_for_category_pair`) - a static,
# always-visible legend for the color-to-meaning mapping, regardless of
# whether the Colorize checkbox (T-5/1005) is currently on or off. Purely a
# read-only lookup plus WPF visual construction - no Revit API calls, no
# `_revit_api_bridge` involvement, no Transaction, and no changes to the
# Isolate/Colorize checkbox handlers.
#
# APPROACH CHOICE: rather than introducing a DataTemplate/binding-based
# ListBox (this codebase has no MVVM/INotifyPropertyChanged convention
# anywhere - ClashResult, ScopeSelection, etc. are all plain, non-bindable
# Python objects), each row's visual (a small colored `Border` swatch plus
# the existing `describe()` label `TextBlock`, side by side in a horizontal
# `StackPanel`) is built directly in Python and added AS THE ITEM ITSELF to
# `ClashListBox.Items`, exactly the way `ScopePickerWindow` already builds
# `CheckBox`/`TextBlock`/`StackPanel` controls in code instead of static
# XAML (see `_build_host_categories_ui`/`_build_one_link_block` above) -
# this is the file's own established, least-disruption pattern for "the
# content isn't knowable until run time" UI, not a new one. WPF's
# `ItemsControl` accepts any object as an item, including a `UIElement`
# (which a `StackPanel` is) - it is used directly as that row's visual,
# wrapped in an implicitly-generated `ListBoxItem` container exactly like a
# plain string item would be. Crucially, this changes NOTHING about
# `ClashListBox.SelectedIndex`/index-based navigation: `_on_list_selection_
# changed`/`_set_current_index`/`_current_clash_result` all key off
# `SelectedIndex`, an integer position, never off the item's own type or
# content - see the "Implementation" section of tickets/1010-clash-list-
# legend-swatches.md for how this was specifically verified.
# ---------------------------------------------------------------------------


def _wpf_color_for_category_pair(clash_result):
    """Convert `clash_result`'s category-pair color - an
    `Autodesk.Revit.DB.Color` (0-255 int R/G/B, from T-8's
    `_color_for_category_pair`) - into a `System.Windows.Media.Color` (also
    0-255 byte R/G/B, but a completely separate .NET type with no implicit
    conversion between the two) suitable for a WPF `SolidColorBrush`. Calls
    `_color_for_category_pair(_category_pair_key(clash_result))` directly -
    the exact T-8 functions, not a re-derived/approximated hash - so the
    legend can never drift out of sync with what Colorize (T-5) actually
    applies to the model.
    """
    revit_color = _color_for_category_pair(_category_pair_key(clash_result))
    return MediaColor.FromRgb(revit_color.Red, revit_color.Green, revit_color.Blue)


def _build_clash_list_row(clash_result):
    """Build one `ClashListBox` row's visual for `clash_result`: a small
    solid-color swatch (the US-8 legend) immediately followed by the
    existing `clash_result.describe()` label text, laid out in a horizontal
    `StackPanel`. This is a purely cosmetic, static addition - it reflects
    what `clash_result`'s category pair WOULD colorize to (see
    `_wpf_color_for_category_pair`), independent of whether Colorize is
    currently checked, and adds no click/toggle behavior of its own beyond
    what the ListBox row already had (selecting the row still selects this
    clash, exactly as before).
    """
    swatch = Border()
    swatch.Width = 14
    swatch.Height = 14
    swatch.Margin = Thickness(0, 0, 6, 0)
    swatch.Background = SolidColorBrush(_wpf_color_for_category_pair(clash_result))
    swatch.BorderBrush = Brushes.Black
    swatch.BorderThickness = Thickness(1)
    swatch.VerticalAlignment = VerticalAlignment.Center

    label = TextBlock()
    label.Text = clash_result.describe()
    label.TextWrapping = TextWrapping.Wrap
    label.VerticalAlignment = VerticalAlignment.Center

    row = StackPanel()
    row.Orientation = Orientation.Horizontal
    row.Children.Add(swatch)
    row.Children.Add(label)
    return row


class ClashListWindow(forms.WPFWindow):
    """Modeless T-3 clash list / navigation panel (US-3).

    Modeless (opened via ``.Show()``, not ``.ShowDialog()`` like
    ScopePickerWindow) specifically because - per US-4 (camera auto-navigation,
    ticket 1004, NOT implemented here) - the user is expected to keep looking
    at and interacting with the active Revit 3D view WHILE stepping through
    clashes in this panel. A modal window would block the Revit UI thread and
    make that impossible, which is exactly the reason ScopePickerWindow (T-2)
    is modal and this one deliberately is not.

    Navigation model: ``self.current_index`` is the single source of truth for
    "which clash is currently selected". Both direct list clicks
    (``ClashListBox``'s ``SelectionChanged``) and the Next/Previous buttons
    ultimately change ``ClashListBox.SelectedIndex``, which is the only thing
    ``_on_list_selection_changed`` listens to - so there is exactly one code
    path that ever updates the current clash and fires the extension hook
    below, regardless of how the user triggered the change.

    EXTENSION HOOK for camera fly-to (1004): every time the current clash
    changes, this window calls ``self.on_selection_changed(clash_result,
    index)``. To hook in without touching any navigation logic above,
    EITHER:
      - pass ``selection_changed_callback`` to the constructor (or set
        ``window.selection_changed_callback = your_function`` on an instance
        afterwards - ``on_selection_changed``'s default implementation just
        forwards to this callback if one is set, otherwise it's a no-op), OR
      - subclass ``ClashListWindow`` and override ``on_selection_changed``
        directly.
    ``your_function(clash_result, index)`` / the override receives the
    ``ClashResult`` now selected and its integer index in
    ``self.clash_results``. Ticket 1004 (camera fly-to, wired from
    ``__main__``, NOT from inside this class) ultimately reads
    ``clash_result.host_element`` / ``.link_element`` / ``.link_instance_id``
    to compute a combined bounding box and reframe the view via
    ``reframe_active_view_on_clash`` above - but IMPORTANT (Phase 7 round 3
    fix): this hook, like every other ``ClashListWindow`` event handler,
    fires OUTSIDE a valid Revit API execution context (see the module
    docstring's "SECOND RESEARCHED-NOT-GUESSED SUBTLETY" section), so
    ``__main__``'s callback does NOT call ``reframe_active_view_on_clash``
    directly from here - it queues a closure that does so through
    ``_revit_api_bridge.raise_action(...)`` instead, the same bridge 1005's
    colorize checkbox uses, and the actual camera move happens later, back
    in a valid context, inside ``_RevitApiBridge.Execute()``. Do NOT
    reimplement Next/Previous/list-click handling to add new per-selection
    behavior - hook in here instead so there is only ever one navigation
    path.

    Ticket 1005 (colorize-by-category) does NOT use this hook, deliberately:
    per that ticket, colorizing applies to every clash in
    ``self.clash_results`` at once, not to whichever single clash is
    currently selected, so it's a different kind of action from navigation.
    It gets its own control instead - see ``ColorizeCheckBox`` in
    ``clashflag_clash_list.xaml`` and ``colorize_checkbox_checked`` /
    ``colorize_checkbox_unchecked`` below.

    Passing `selection_changed_callback` to the CONSTRUCTOR (rather than only
    ever setting it on the returned instance afterwards) matters for the
    very first clash: ``__init__`` auto-selects index 0 immediately below
    (before returning to any caller), which fires this same hook - a
    callback attached only after construction would silently miss that
    initial auto-selection and only ever fire on subsequent Next/Previous/
    click navigation.
    """

    def __init__(self, xaml_file_path, clash_results, selection_changed_callback=None):
        forms.WPFWindow.__init__(self, xaml_file_path)

        self.clash_results = list(clash_results)
        self.current_index = -1

        # Extension point for tickets 1004/1005 - see class docstring. None
        # means "no callback attached"; on_selection_changed() below no-ops
        # in that case. Set from the constructor argument (not just left for
        # external assignment) so it's already in place before the initial
        # _set_current_index(0) call below fires it for the first clash.
        self.selection_changed_callback = selection_changed_callback

        # T-5 / ticket 1005 (colorize by category) state. `colorize_active`
        # and `colorize_previous_overrides` mirror the corresponding
        # parameters of apply_colorize_overrides/clear_colorize_overrides -
        # see colorize_checkbox_checked/_unchecked below and this module's
        # "COLORIZE BY CATEGORY" section for what they're for.
        # `colorize_view_id` remembers exactly which View was colorized
        # (captured at apply time, NOT re-read from doc.ActiveView at clear
        # time) because overrides are per-view state and the user could
        # switch the active view while colorize stays checked - see
        # clear_colorize_overrides's docstring for why clearing must target
        # the SAME view it was applied to.
        self.colorize_active = False
        self.colorize_previous_overrides = {}
        self.colorize_view_id = None

        # T-9 / ticket 1009 (US-7) state. Mirrors colorize_active's/
        # colorize_view_id's exact shape and reasoning (see the comment just
        # above), with one addition: unlike colorize (a single one-shot
        # apply per Checked event), isolate can be RE-applied many times
        # over one "session" - once per Next/Previous/list-click navigation
        # while the checkbox stays checked (see on_selection_changed below).
        # `isolate_view_id` is therefore not just "captured at apply time,
        # not re-read at clear time" like colorize_view_id - it is captured
        # ONCE, at the FIRST apply of a session, and then REUSED (never
        # re-read from doc.ActiveView) for every later re-apply in that same
        # session too, so a mid-session active-view switch can't strand an
        # earlier isolated view with nothing left able to clear it. See
        # _apply_isolate_for_clash's own docstring for the full reasoning.
        self.isolate_active = False
        self.isolate_view_id = None

        # T-11 (ticket 1011) fix: every module-level name a delegate-wired
        # (XAML Checked=/Unchecked=/Click=) method on this class needs is
        # captured as a `self.*` attribute HERE, in __init__ - the one method
        # on this class that is NOT invoked through a CLR delegate (it's an
        # ordinary Python constructor call from show_clash_list), and so is
        # the only method guaranteed to see this module's real globals (see
        # tickets/1011-fix-event-handler-globals-crash.md's root-cause
        # writeup). Every delegate-wired method below (colorize_checkbox_
        # checked, _clear_colorize_if_active, _apply_isolate_for_clash,
        # _clear_isolate_if_active - including their nested `_apply`/`_clear`
        # closures) reads these back via `self.*` (captured into a local
        # first, matching the existing `self.isolate_view_id` ->
        # `reuse_view_id` precedent below) instead of referencing the bare
        # module-level name directly, which would raise
        # IronPython.Runtime.UnboundNameException the moment it's clicked in
        # a live Revit session.
        self._doc = doc
        self._uidoc = uidoc
        self._output = output
        self._forms = forms
        self._bridge = _revit_api_bridge
        self._apply_colorize_overrides_fn = apply_colorize_overrides
        self._clear_colorize_overrides_fn = clear_colorize_overrides
        self._isolate_host_element_fn = _isolate_host_element
        self._exit_temporary_isolate_fn = _exit_temporary_isolate
        self._select_clash_pair_fn = select_clash_pair

        for clash_result in self.clash_results:
            # T-10 (US-8): each row is now a small Legend swatch (see
            # `_build_clash_list_row`) plus the same describe() label text
            # this used to add as a bare string - SelectedIndex-based
            # navigation below is unaffected (see the "LEGEND SWATCHES"
            # section header comment above `_build_clash_list_row`).
            self.ClashListBox.Items.Add(_build_clash_list_row(clash_result))

        self.ClashListBox.SelectionChanged += self._on_list_selection_changed

        if self.clash_results:
            self._set_current_index(0)
        else:
            self._update_status_and_buttons()
            # Nothing to colorize or isolate either - matches the disabled
            # Previous/Next buttons' "no clashes" treatment above.
            self.ColorizeCheckBox.IsEnabled = False
            self.IsolateCheckBox.IsEnabled = False

    def colorize_checkbox_checked(self, sender, args):
        """Turn colorize-by-category ON for the WHOLE current
        ``clash_results`` set at once - see the class docstring's
        "EXTENSION HOOK" note for why this is a separate control from the
        per-selection navigation hook, and ``apply_colorize_overrides`` /
        this module's "ADDED IN 1005" docstring section for exactly what
        does and doesn't get colorized (host-side elements only - a
        researched Revit API limitation, not an oversight).

        Does NOT call ``apply_colorize_overrides`` directly - this handler
        itself runs outside a valid Revit API context (see the module
        docstring's "SECOND RESEARCHED-NOT-GUESSED SUBTLETY"), so the actual
        work is queued through ``_revit_api_bridge`` and runs later, back
        in a valid context, via ``_RevitApiBridge.Execute``.

        T-11 (ticket 1011) fix: this method is wired to the XAML `Checked=`
        event, so its (and its nested `_apply` closure's) `func_globals` is a
        broken, near-empty dict (see tickets/1011-fix-event-handler-globals-
        crash.md) - every module-level name this method/closure needs is
        therefore read from a `self.*` attribute (captured into a local
        here, at the top of the OUTER method, so the nested closure below
        picks it up via its normal enclosing-scope cell mechanism) instead of
        referenced bare.
        """
        host_doc = self._doc
        apply_overrides_fn = self._apply_colorize_overrides_fn
        show_forms = self._forms
        print_output = self._output
        bridge = self._bridge

        def _apply():
            active_view = host_doc.ActiveView
            try:
                previous_overrides = apply_overrides_fn(
                    self.clash_results, host_doc, active_view
                )
            except Exception as colorize_error:
                show_forms.alert(
                    "ClashFlag could not apply colorize overrides: {0}".format(
                        colorize_error
                    ),
                    title="ClashFlag - colorize error",
                )
                # Safe to touch WPF state here even though this runs inside
                # the ExternalEvent bridge's Execute(), not the original
                # click handler - Execute() runs on the same main/UI thread
                # the window's own dispatcher uses (see the module
                # docstring), so this is not a cross-thread property set.
                self.ColorizeCheckBox.IsChecked = False
                return

            self.colorize_previous_overrides = previous_overrides
            self.colorize_view_id = active_view.Id
            self.colorize_active = True
            print_output.print_md(
                "_ClashFlag: colorize by category is ON - host-side "
                "clashing elements only. Revit has no API to override an "
                "individual linked element's graphics from a host view "
                "(researched, see clashflag_runner.py's module docstring), "
                "so link-side elements are left untouched._"
            )

        bridge.raise_action(_apply)

    def colorize_checkbox_unchecked(self, sender, args):
        """Turn colorize-by-category OFF: restore every host element this
        tool touched back to its pre-colorize override state (see
        ``clear_colorize_overrides``'s docstring), on the SAME view it was
        applied to - not necessarily whatever view happens to be active
        right now."""
        self._clear_colorize_if_active()

    def _clear_colorize_if_active(self):
        """Shared by the Unchecked handler above AND by show_clash_list's
        Closed-event cleanup below (ticket instruction: don't leave
        overrides dangling in the model after this window's UI is gone) -
        both need the exact same "restore and reset state" behavior, and
        having two independent copies of it would risk them drifting apart.
        No-ops if colorize was never turned on, or was already cleared -
        both handlers can end up calling this on the same already-clean
        state without harm (e.g. Unchecked firing once more during Close).

        The ``colorize_active``/``colorize_previous_overrides``/
        ``colorize_view_id`` reset happens SYNCHRONOUSLY here, immediately -
        not deferred into the queued action below - specifically so a second
        near-simultaneous call (e.g. unchecking the box right as the window
        is also closing, firing Unchecked and Closed back to back) sees
        ``colorize_active`` already False and no-ops instead of queuing a
        second, redundant clear. The actual model-touching work (reading
        `view` back via `doc.GetElement`, calling `clear_colorize_overrides`)
        still has to happen later, in a valid API context, via the bridge -
        that part is queued exactly like colorize_checkbox_checked's apply.

        T-11 (ticket 1011) fix: like colorize_checkbox_checked, this method
        (and its nested `_clear` closure) is reached from a delegate-wired
        handler (`colorize_checkbox_unchecked`, and indirectly `show_clash_
        list`'s Closed handler) with broken `func_globals` - every
        module-level name needed is read from a `self.*` attribute, captured
        into a local at the top of this method, instead of referenced bare.
        """
        if not self.colorize_active:
            return

        host_doc = self._doc
        print_output = self._output
        clear_overrides_fn = self._clear_colorize_overrides_fn
        bridge = self._bridge

        view_id = self.colorize_view_id
        previous_overrides = self.colorize_previous_overrides
        self.colorize_active = False
        self.colorize_previous_overrides = {}
        self.colorize_view_id = None

        def _clear():
            view = host_doc.GetElement(view_id) if view_id else None
            if view is not None:
                try:
                    clear_overrides_fn(host_doc, view, previous_overrides)
                except Exception as clear_error:
                    print_output.print_md(
                        "_ClashFlag: failed to fully clear colorize "
                        "overrides: {0}_".format(clear_error)
                    )
            else:
                print_output.print_md(
                    "_ClashFlag: the view colorize was applied to no "
                    "longer exists - its overrides could not be explicitly "
                    "cleared (they went away with the view itself)._"
                )

        bridge.raise_action(_clear)

    def isolate_checkbox_checked(self, sender, args):
        """Turn Isolate ON (US-7 / ticket 1009) for the CURRENT clash - see
        this module's "ISOLATE CURRENT CLASH" section and
        _apply_isolate_for_clash's own docstring for what actually happens
        and exactly which view it targets.

        Like every other ClashListWindow handler, this runs OUTSIDE a valid
        Revit API execution context (see the module docstring's "SECOND
        RESEARCHED-NOT-GUESSED SUBTLETY" section) - all it does directly is
        read plain Python/already-held state (`self.current_index`,
        `self.clash_results`) and hand off to `_apply_isolate_for_clash`,
        which itself queues the actual Revit-API-touching work through
        `_revit_api_bridge.raise_action(...)`. Nothing Revit-API-touching is
        ever called directly from this method's own body.
        """
        clash_result = self._current_clash_result()
        if clash_result is None:
            # Shouldn't normally happen - IsolateCheckBox is disabled
            # whenever clash_results is empty (see __init__) - but guarded
            # defensively rather than assumed, same posture as
            # colorize_checkbox_checked's handling of unexpected states.
            self.IsolateCheckBox.IsChecked = False
            return
        self._apply_isolate_for_clash(clash_result)

    def isolate_checkbox_unchecked(self, sender, args):
        """Turn Isolate OFF: exit Temporary Isolate mode on whichever view
        Isolate is currently active on, restoring full visibility there -
        see `_clear_isolate_if_active`'s docstring for exactly which view
        and why."""
        self._clear_isolate_if_active()

    def _apply_isolate_for_clash(self, clash_result):
        """Queue the bridge action that isolates `clash_result`'s host
        element and Selects both its elements (US-7's "Isolate always also
        runs Select") - shared by `isolate_checkbox_checked` (the FIRST
        apply of an Isolate "session") and `on_selection_changed` (every
        RE-apply triggered by Next/Previous/list-click navigation while
        `self.isolate_active` is already True). One shared implementation
        means both call sites can never drift apart on what "isolate this
        clash" actually does - the same reason `_clear_colorize_if_active`
        is shared between the Unchecked handler and the window's Closed
        handler.

        VIEW CHOICE - CAPTURE ONCE PER SESSION, DON'T RE-READ "WHATEVER'S
        ACTIVE NOW" ON EVERY RE-APPLY: the FIRST call in a session
        (`self.isolate_view_id` is still None, i.e. Isolate was just
        checked) reads `doc.ActiveView` fresh, exactly like
        `colorize_checkbox_checked` captures `colorize_view_id`. Every
        SUBSEQUENT call in the SAME session (checkbox still checked,
        `self.isolate_view_id` already set from that first call) re-resolves
        and reuses that EXACT View by id - it does not read `doc.ActiveView`
        again. This matters because `IsolateElementsTemporary` can be called
        on any resolved View object regardless of whether it's the currently
        active one, and blindly re-reading "whatever's active now" on every
        navigation step would silently strand an EARLIER isolated view stuck
        in Temporary Isolate mode forever the moment a user switches the
        active view mid-session and then clicks Next: `isolate_view_id`
        would get overwritten to point at the new view, and nothing would
        ever go back and call `DisableTemporaryViewMode` on the abandoned
        first one - not even closing the window, since `_clear_isolate_if_
        active` only ever knows about the LAST view stored there. Reusing
        one captured view for a whole session (extending colorize_view_id's
        existing "capture at apply time, don't re-read at clear time"
        pattern to also cover mid-session RE-apply, not just clear)
        guarantees exactly one view is ever touched per session, and that
        Unchecked/Closed can always find and clean up the one it touched.

        No-ops (queues nothing) when `clash_result` is None - i.e. nothing
        is currently "the current clash" (can only happen transiently, e.g.
        `current_index` momentarily out of range) - there is nothing to
        isolate.

        T-11 (ticket 1011) fix: this method (reached from the delegate-wired
        `isolate_checkbox_checked` and, on later navigation, `on_selection_
        changed`) and its nested `_apply` closure have broken `func_globals`
        - every module-level name needed (`doc`, `output`, `uidoc`,
        `_isolate_host_element`, `select_clash_pair`, `_revit_api_bridge`) is
        therefore read from a `self.*` attribute, captured into a local at
        the top of this method (alongside the existing `reuse_view_id`
        capture below) instead of referenced bare.
        """
        if clash_result is None:
            return

        host_doc = self._doc
        host_uidoc = self._uidoc
        print_output = self._output
        isolate_host_element_fn = self._isolate_host_element_fn
        select_clash_pair_fn = self._select_clash_pair_fn
        bridge = self._bridge

        # None only on the very first apply of a session (see docstring
        # above) - captured here, in the raw handler body, not inside the
        # queued closure below: this is a plain read of an already-held
        # Python attribute (an ElementId object created earlier, inside a
        # valid context), not a new Revit API call, so it needs no bridge -
        # the exact same reasoning colorize_checkbox_unchecked already
        # relies on when it reads self.colorize_view_id outside the bridge.
        reuse_view_id = self.isolate_view_id
        is_first_apply_in_session = reuse_view_id is None

        def _apply():
            if reuse_view_id is not None:
                view = host_doc.GetElement(reuse_view_id)
                if view is None:
                    print_output.print_md(
                        "_ClashFlag: the view Isolate was applied to no "
                        "longer exists - turning Isolate off._"
                    )
                    self.isolate_active = False
                    self.isolate_view_id = None
                    self.IsolateCheckBox.IsChecked = False
                    return
            else:
                view = host_doc.ActiveView

            try:
                isolate_host_element_fn(host_doc, view, clash_result.host_element.Id)
            except Exception as isolate_error:
                print_output.print_md(
                    "_ClashFlag: could not isolate this clash's host "
                    "element: {0}_".format(isolate_error)
                )
                # Reset state and uncheck rather than leave Isolate marked
                # "active" against a view it never actually succeeded in
                # isolating - mirrors colorize_checkbox_checked's own
                # failure handling (uncheck the box on apply failure).
                self.isolate_active = False
                self.isolate_view_id = None
                self.IsolateCheckBox.IsChecked = False
                return

            self.isolate_active = True
            self.isolate_view_id = view.Id
            # Always also Select both elements (US-7) - the link-side
            # element can't be isolated (same API ceiling as colorize's
            # host-only override limitation), so Select keeps it findable
            # inside the still-fully-visible link model.
            select_clash_pair_fn(clash_result, host_doc, host_uidoc)

            if is_first_apply_in_session:
                # Printed once per session (first check), not on every
                # subsequent Next/Previous re-apply - matches
                # reframe_active_view_on_clash's own "console note, not
                # popup, since [failure] notes already fire on every
                # navigation step" reasoning, taken one step further here:
                # a routine SUCCESS note on every single step would drown
                # out the genuinely useful per-step failure notes above.
                print_output.print_md(
                    "_ClashFlag: Isolate is ON - hides everything in this "
                    "view except this clash's host-side element. The "
                    "link-side element can't be isolated (same Revit API "
                    "ceiling as colorize's host-only limitation), so "
                    "Select keeps it findable too. Moving to a different "
                    "clash replaces the isolation; turning Isolate off "
                    "restores full visibility._"
                )

        bridge.raise_action(_apply)

    def _clear_isolate_if_active(self):
        """Shared by `isolate_checkbox_unchecked` above AND
        `show_clash_list`'s Closed-event cleanup below - exact mirror of
        `_clear_colorize_if_active`'s own shape and reasoning (a window
        closed while Isolate is still on must not leave the model - here,
        specifically the one view Isolate was applied to - stuck in
        Temporary Isolate mode after this window's UI is gone). No-ops if
        Isolate was never turned on, or was already cleared (e.g. a
        still-in-flight `_apply_isolate_for_clash` bridge closure that
        already reset this state after a re-apply failure, or Unchecked and
        Closed both firing close together) - same double-fire safety
        `_clear_colorize_if_active` already relies on.

        State reset happens SYNCHRONOUSLY, immediately, here - not deferred
        into the queued bridge closure - for the identical reason
        `_clear_colorize_if_active`'s own docstring gives: a second
        near-simultaneous call must see `isolate_active` already False and
        no-op, rather than queue a second, redundant
        `DisableTemporaryViewMode` call.

        T-11 (ticket 1011) fix: like `_clear_colorize_if_active`, this method
        (and its nested `_clear` closure) is reached from a delegate-wired
        handler (`isolate_checkbox_unchecked`, and indirectly `show_clash_
        list`'s Closed handler) with broken `func_globals` - every
        module-level name needed is read from a `self.*` attribute, captured
        into a local at the top of this method, instead of referenced bare.
        """
        if not self.isolate_active:
            return

        host_doc = self._doc
        print_output = self._output
        exit_temporary_isolate_fn = self._exit_temporary_isolate_fn
        bridge = self._bridge

        view_id = self.isolate_view_id
        self.isolate_active = False
        self.isolate_view_id = None

        def _clear():
            view = host_doc.GetElement(view_id) if view_id else None
            if view is None:
                print_output.print_md(
                    "_ClashFlag: the view Isolate was applied to no longer "
                    "exists - its Temporary Isolate mode could not be "
                    "explicitly cleared (it went away with the view "
                    "itself)._"
                )
                return
            try:
                exit_temporary_isolate_fn(host_doc, view)
            except Exception as clear_error:
                print_output.print_md(
                    "_ClashFlag: failed to fully exit Temporary Isolate "
                    "mode: {0}_".format(clear_error)
                )

        bridge.raise_action(_clear)

    def _on_list_selection_changed(self, sender, args):
        """The one place ``current_index`` ever changes. Fires for direct
        user clicks on a list row AND for the ``SelectedIndex`` writes
        ``_set_current_index()`` itself makes (Next/Previous/initial
        selection) - both paths converge here on purpose."""
        selected_index = self.ClashListBox.SelectedIndex
        if selected_index == self.current_index:
            return
        self.current_index = selected_index
        self._update_status_and_buttons()
        self._fire_selection_hook()

    def _set_current_index(self, new_index):
        """Move the current-clash pointer to `new_index`, clamped to the
        valid range. Setting ``SelectedIndex`` (rather than updating
        ``self.current_index`` directly) routes the change back through
        ``_on_list_selection_changed`` above, keeping list-click and
        button-driven navigation on the exact same code path."""
        if not self.clash_results:
            return
        clamped_index = max(0, min(new_index, len(self.clash_results) - 1))
        self.ClashListBox.SelectedIndex = clamped_index

    def _update_status_and_buttons(self):
        total = len(self.clash_results)
        if 0 <= self.current_index < total:
            self.StatusText.Text = "Clash {0} of {1}".format(
                self.current_index + 1, total
            )
        else:
            self.StatusText.Text = "No clashes." if total == 0 else ""
        self.PreviousButton.IsEnabled = self.current_index > 0
        self.NextButton.IsEnabled = 0 <= self.current_index < total - 1

    def _current_clash_result(self):
        """The ``ClashResult`` `self.current_index` currently points at, or
        ``None`` if out of range (e.g. `current_index` is still -1 before
        any clash is auto-selected, or `clash_results` is empty). Shared by
        `_fire_selection_hook` (existing, 1003) and
        `isolate_checkbox_checked` (new, 1009) so both read "the current
        clash" exactly the same way."""
        if 0 <= self.current_index < len(self.clash_results):
            return self.clash_results[self.current_index]
        return None

    def _fire_selection_hook(self):
        clash_result = self._current_clash_result()
        self.on_selection_changed(clash_result, self.current_index)

    def on_selection_changed(self, clash_result, index):
        """EXTENSION HOOK - see class docstring for the full contract. Called
        every time the current-clash pointer changes, with the newly current
        ``ClashResult`` (or ``None``/``-1`` if nothing is selected) and its
        index. Default implementation forwards to
        ``self.selection_changed_callback`` if one has been set; override
        this method in a subclass instead if you'd rather extend by
        inheritance. Ticket 1004 (camera fly-to) hooks in here; ticket 1005
        (colorize) deliberately does NOT - see the class docstring's
        "colorize-by-category" note above.

        T-9 / ticket 1009 (US-7) ALSO hooks in here, deliberately, rather
        than inventing a second navigation hook (per that ticket's explicit
        instruction): if Isolate is currently on, replace the isolation for
        the newly-current clash - this is the ONE place "the current clash
        changed" is ever signaled, regardless of whether the change came
        from a list click, Next, Previous, or the initial auto-selection at
        window-open (that initial call is harmless here since
        `self.isolate_active` is always still False at that point - Isolate
        is opt-in and can't have been checked before the window finished
        constructing)."""
        if self.selection_changed_callback is not None:
            self.selection_changed_callback(clash_result, index)

        if self.isolate_active:
            self._apply_isolate_for_clash(clash_result)

    def next_button_click(self, sender, args):
        self._set_current_index(self.current_index + 1)

    def previous_button_click(self, sender, args):
        self._set_current_index(self.current_index - 1)

    def close_button_click(self, sender, args):
        self.Close()


def show_clash_list(clash_results, selection_changed_callback=None):
    """Show the modeless T-3 clash list window for `clash_results` (expected
    non-empty - see run_interference_check's caller in __main__, which skips
    calling this at all when a run finds zero clashes rather than opening an
    empty panel).

    `selection_changed_callback` (added 1004), if given, is forwarded straight
    to ``ClashListWindow``'s constructor rather than set on the returned
    instance afterwards - see that constructor's docstring for why the
    timing matters (the very first clash is auto-selected, and hence the hook
    fired, DURING construction, before this function would otherwise have a
    chance to return an instance for the caller to attach a callback to).

    Returns the ``ClashListWindow`` instance. The caller doesn't need to keep
    it - a module-level list keeps it alive (see ``_open_clash_list_windows``
    above).
    """
    xaml_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "clashflag_clash_list.xaml"
    )
    window = ClashListWindow(xaml_path, clash_results, selection_changed_callback)

    _open_clash_list_windows.append(window)

    def _on_window_closed(sender, args):
        # T-5 / ticket 1005 instruction: don't leave colorize overrides
        # dangling in the model after this window's UI is gone - if the
        # checkbox was still checked when the user closed the window (title-
        # bar close, Close button, or Escape all raise Closed the same way),
        # clear them here using the exact same restore-previous-overrides
        # path the Unchecked handler uses, BEFORE forgetting the window.
        window._clear_colorize_if_active()
        # T-9 / ticket 1009 instruction: same treatment for Isolate - don't
        # leave the model's view stuck in Temporary Isolate mode after this
        # window's UI is gone, using the exact same restore path
        # isolate_checkbox_unchecked uses. Independent of the colorize call
        # above - neither reads or writes the other's state.
        window._clear_isolate_if_active()
        if window in _open_clash_list_windows:
            _open_clash_list_windows.remove(window)

    window.Closed += _on_window_closed

    window.Show()
    return window


def run_interference_check(scope_selection):
    """Run the manual-transform interference check for one user-picked scope:
    `scope_selection.host_categories` against the active document, checked
    separately against each selected linked model in
    `scope_selection.link_selections` (each with its own category subset and
    its own placement transform).

    Returns a flat, ordered ``list[ClashResult]`` covering every clash found
    across every selected link, in the same order the links were iterated and
    (within a link) the same order ``find_clashing_pairs`` returned them -
    this is the single sequence the T-3 list panel (``ClashListWindow``) is
    built to display/navigate. The list is empty (never ``None``) when no
    clashes were found anywhere, so a caller can just check truthiness.

    The existing per-link/per-pair ``output.print_md`` console reporting
    below is UNCHANGED and kept alongside this - it's not made redundant by
    the flat list because it's grouped and labeled per-link (with candidate
    counts, skip counts, and a per-link sub-total) in a way a single flat
    list intentionally is not; the console output is a run LOG, the flat list
    is UI-navigation STATE. Both are cheap to keep since they're built from
    the same already-computed ``clashing_pairs`` values.
    """
    output.print_md("## ClashFlag - interference check runner")
    output.print_md(
        "Host categories: **{0}**".format(
            ", ".join(str(c) for c in scope_selection.host_categories)
        )
    )
    output.print_md(
        "Detection method: manual transform pipeline (bbox pre-filter + "
        "`SolidUtils.CreateTransformed` + `BooleanOperationsUtils.Intersect`) "
        "per tickets/1001 rework - no tolerance/near-miss logic."
    )

    # Host candidates are collected once and reused against every selected
    # link below - they don't depend on which link is being checked, only on
    # the (shared, single) host category selection.
    host_candidates, host_skipped = collect_candidate_solids(
        doc, scope_selection.host_categories, link_transform=None
    )
    output.print_md(
        "Host candidates: **{0}** ({1} skipped - no usable solid geometry)".format(
            len(host_candidates), host_skipped
        )
    )

    if not host_candidates:
        output.print_md(
            "**No interferences found** - the host side has zero candidates "
            "with usable solid geometry, so no pair can be checked."
        )
        return []

    total_clash_count = 0
    all_clash_results = []  # flat list[ClashResult] across every link - see
    # this function's docstring for why this is built alongside, not instead
    # of, the per-link console reporting below.

    for link_element_id, link_categories in scope_selection.link_selections:
        link_instance = resolve_link_instance_by_id(doc, link_element_id)
        link_doc = resolve_link_document(link_instance)
        link_name = _link_display_name(link_instance)

        output.print_md("### Linked model: **{0}**".format(link_name))
        output.print_md(
            "Link categories: **{0}**".format(
                ", ".join(str(c) for c in link_categories)
            )
        )

        # Maps LINK-LOCAL coordinates -> HOST coordinates, for THIS specific
        # RevitLinkInstance. Chosen over GetTransform() because it also folds
        # in true-north, matching tickets/0004's Erratum guidance for
        # cross-document geometry work. Computed fresh per link instance -
        # each loaded link (even two placements of the same link document)
        # gets its own transform, since a shared Document doesn't disambiguate
        # placement per tickets/0004's "Multiple link instances" note.
        link_transform = link_instance.GetTotalTransform()

        link_candidates, link_skipped = collect_candidate_solids(
            link_doc, link_categories, link_transform=link_transform
        )
        output.print_md(
            "Linked candidates: **{0}** ({1} skipped - no usable solid "
            "geometry)".format(len(link_candidates), link_skipped)
        )

        if not link_candidates:
            output.print_md(
                "No interferences found against **{0}** - zero candidates "
                "with usable solid geometry on the link side.".format(link_name)
            )
            continue

        clashing_pairs = find_clashing_pairs(host_candidates, link_candidates)

        if not clashing_pairs:
            output.print_md(
                "No interferences found against **{0}** for this scope.".format(
                    link_name
                )
            )
            continue

        total_clash_count += len(clashing_pairs)
        output.print_md(
            "**{0} clash pair(s) found against {1}:**".format(
                len(clashing_pairs), link_name
            )
        )

        for index, (element1, element2) in enumerate(clashing_pairs, start=1):
            host_id_text = output.linkify(element1.Id)

            output.print_md(
                "{0}. Host `{1}` ({2})  <->  Link `{3}` ({4})".format(
                    index,
                    host_id_text,
                    describe_element(element1),
                    element2.Id.IntegerValue,
                    describe_element(element2),
                )
            )
            all_clash_results.append(
                ClashResult(element1, element2, link_name, link_instance.Id)
            )

    output.print_md("---")
    output.print_md(
        "**Total: {0} clash pair(s) found across {1} selected link(s).**".format(
            total_clash_count, len(scope_selection.link_selections)
        )
    )

    return all_clash_results


if __name__ == "__main__":
    try:
        scope_selection = show_scope_picker(doc)
        if scope_selection is None:
            output.print_md("ClashFlag - cancelled (no scope confirmed).")
        else:
            clash_results = run_interference_check(scope_selection)
            # Only open the T-3 list panel when there's something to
            # navigate - run_interference_check's own console reporting
            # above already covers the "no clashes" case (per-link and via
            # the final "Total: 0 clash pair(s)" line), so an empty panel
            # would be redundant and confusing (per ticket 1003 instruction
            # #5: don't show an empty panel for a zero-clash run).
            if clash_results:
                # 1004: wire camera fly-to via ClashListWindow's existing
                # selection_changed_callback hook - passed straight into
                # show_clash_list (not set on the returned window afterwards)
                # so it's already attached before the window auto-selects
                # clash #0 during construction (see show_clash_list's and
                # ClashListWindow.__init__'s docstrings for why that ordering
                # matters). This is wiring only - no navigation logic in
                # ClashListWindow itself is touched.
                #
                # Phase 7 round 3 fix: this callback is a WPF selection-
                # changed event handler on a modeless window, so - like every
                # other ClashListWindow handler - it runs OUTSIDE a valid
                # Revit API execution context on every call except the very
                # first (synchronous, still-inside-__main__) auto-selection.
                # Rather than special-case that one still-valid first call,
                # every call is routed through `_revit_api_bridge.raise_action`
                # UNCONDITIONALLY, exactly the way `colorize_checkbox_checked`'s
                # `_apply` closure already does for 1005 - the actual API work
                # (reading ActiveView, resolving the link, calling
                # ZoomAndCenterRectangle) happens later, back in a valid
                # context, inside `_RevitApiBridge.Execute()`.
                def _on_clash_selection_changed(clash_result, index):
                    if clash_result is None:
                        return

                    def _reframe():
                        reframe_active_view_on_clash(clash_result, doc, uidoc)

                    _revit_api_bridge.raise_action(_reframe)

                show_clash_list(
                    clash_results,
                    selection_changed_callback=_on_clash_selection_changed,
                )
    except ClashFlagError as clash_flag_error:
        # Expected, actionable setup problem (e.g. a link unloaded since the
        # picker was shown) - show the user a clear message instead of a raw
        # stack trace.
        forms.alert(str(clash_flag_error), title="ClashFlag - setup error")
    except Exception as unexpected_error:
        # Unexpected Revit API failure (e.g. bad model state) - report it
        # through the pyRevit console rather than letting Revit itself crash
        # or show an unhandled-exception dialog.
        output.print_md("**ClashFlag failed unexpectedly:**")
        output.print_md("```\n{0}\n```".format(unexpected_error))
        raise

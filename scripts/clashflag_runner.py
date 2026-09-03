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
clash by its (host category, link category) pair - genuinely correct,
transacted, and toggle-safe - and does NOT attempt any link-side element
override. A console note (`output.print_md`) says so every time colorize is
turned on, and the checkbox's XAML tooltip says so up front, so this isn't a
silent gap from the user's point of view.

SECOND RESEARCHED-NOT-GUESSED SUBTLETY: a modeless ``forms.WPFWindow`` (which
``ClashListWindow`` is, per 1003 - see its class docstring) does NOT run its
later button/checkbox event handlers inside a valid Revit API "execution
context" - the script's own valid context ends when its ``__main__`` block
returns, but the window (and its event handlers) keep firing long after
that. Calling a Revit API method that needs a valid context from one of
those handlers - most importantly ``Transaction.Start()/Commit()`` - throws
``Autodesk.Revit.Exceptions.InvalidOperationException`` ("Starting a
transaction from an external application running outside of API context is
not allowed"). This was verified via multiple independent sources (a
pyRevit-specific worked example hitting exactly this exception from a
modeless WPFWindow button handler; the general Revit API "External Events"
developer-guide pattern; and pyRevit's own more recent release notes
explicitly adding an "external event helper and modeless" example to
address it) - NOT assumed, because getting this wrong would mean the
colorize checkbox throws instead of doing anything the very first time it's
clicked in a real Revit session. The fix is the standard
``ExternalEvent``/``IExternalEventHandler`` bridge: ``_ColorizeApiBridge``
(below) is registered once, at module-load time (itself inside a valid API
context, since that's while this script's command is actively executing -
required by ``ExternalEvent.Create``'s own contract), and every colorize
apply/clear operation is queued through it (``raise_action``) instead of
being called directly from a Checked/Unchecked/Closed handler. Revit invokes
the queued action back on the main thread, in a valid context, the next time
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
"""

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
    RevitLinkInstance,
    Solid,
    SolidUtils,
    Transaction,
    View3D,
    ViewDetailLevel,
    XYZ,
)
from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler
from System.Collections.Generic import List
from System.Windows import FontStyles, FontWeights, TextWrapping, Thickness
from System.Windows.Controls import CheckBox, StackPanel, TextBlock

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
            forms.alert(
                "Pick at least one host category before running.",
                title="ClashFlag - scope picker",
            )
            return

        if not link_selections:
            forms.alert(
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
# CAMERA FLY-TO-CLASH (T-4 / ticket 1004)
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


def reframe_active_view_on_clash(clash_result, host_doc, host_uidoc):
    """Reframe the ACTIVE view's camera onto the combined bounding box of
    `clash_result`'s two clashing elements - the camera-fly-to behavior from
    US-4 / ticket 1004, equivalent to what Revit's built-in Interference
    Check dialog's "Show" button does for a found clash.

    Returns True if the view was reframed, False if it was skipped (reported
    via ``output.print_md`` - a one-line console note, NOT a modal
    ``forms.alert`` - this runs on every clash-list navigation step, and a
    popup on every click would be far more disruptive than a console line
    the user can ignore while stepping through the list).

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
# COLORIZE BY CATEGORY (T-5 / ticket 1005)
# ---------------------------------------------------------------------------
#
# See the module docstring's "ADDED IN 1005" section for the full research
# trail on why this only colorizes HOST-side elements, not link-side ones -
# short version: there is no supported Revit API to override the graphics of
# an individual linked-document element, scoped to just that element, from a
# view in the host document (verified against revitapidocs.com's
# View.SetElementOverrides / RevitLinkGraphicsSettings docs AND an
# experienced Autodesk Community answer directly addressing this exact
# question - not assumed).

class _ColorizeApiBridge(IExternalEventHandler):
    """Revit ``ExternalEvent`` bridge back into a valid API context for
    ``ClashListWindow``'s colorize checkbox handlers - see the module
    docstring's "SECOND RESEARCHED-NOT-GUESSED SUBTLETY" section for why
    this is required at all (a modeless WPFWindow's own event handlers run
    OUTSIDE a valid Revit API context, so calling ``Transaction.Start()``
    directly from one throws).

    Usage: call ``raise_action(some_zero_arg_callable)`` from anywhere
    (typically a WPF event handler); Revit invokes that callable back via
    ``Execute()`` at its next idle opportunity, on the main thread, inside a
    valid API context. Actions are queued (a list, not a single slot) so two
    calls to ``raise_action`` in quick succession - e.g. two separate
    ``ClashListWindow`` instances from two ClashFlag runs both toggling
    colorize around the same moment - can't silently overwrite/drop each
    other; ``Execute()`` drains and runs every queued action, in order, each
    time Revit calls it.

    Exactly ONE instance of this class is created, at MODULE LOAD time (see
    ``_colorize_api_bridge`` below) - required, not incidental:
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
                    "_ClashFlag: colorize action failed inside the API-"
                    "context bridge: {0}_".format(bridge_error)
                )

    def GetName(self):
        return "ClashFlag - colorize-by-category API bridge"


# Created once, at module load - see the class docstring for why the timing
# matters. Held at module scope (like `_open_clash_list_windows`) so it
# survives past this script's own __main__ returning, for as long as any
# ClashListWindow it's wired to stays open.
_colorize_api_bridge = _ColorizeApiBridge()


# Small, hand-picked, mutually-distinguishable palette (ColorBrewer-style
# "qualitative" hues - deliberately not randomly generated, so adjacent
# entries never land on near-duplicate colors) cycled across every distinct
# (host_category, link_category) pair seen in the current clash_results.
_CATEGORY_PAIR_COLOR_PALETTE = [
    Color(228, 26, 28),    # red
    Color(55, 126, 184),   # blue
    Color(77, 175, 74),    # green
    Color(255, 127, 0),    # orange
    Color(152, 78, 163),   # purple
    Color(255, 255, 51),   # yellow
    Color(166, 86, 40),    # brown
    Color(247, 129, 191),  # pink
    Color(153, 153, 153),  # gray
    Color(0, 128, 128),    # teal
]


def _category_name_for_colorize(element):
    """Category display name used as one half of a colorize pair key - same
    "<no category>" fallback text describe_element() uses, so an element
    without a Category still gets a deterministic, groupable key instead of
    raising."""
    if element.Category is not None:
        return element.Category.Name
    return "<no category>"


def _category_pair_key(clash_result):
    """Stable dict key for one clash's (host category, link category) pair.
    Host and link names are kept in their natural (host, link) order rather
    than order-normalized/sorted against each other - within a single
    ClashFlag run a given category never swaps which side it's found on, so
    this is already consistent, and "Host: Structural Framing <-> Link:
    Duct" reads more naturally than an alphabetically-normalized pair would.
    """
    return (
        _category_name_for_colorize(clash_result.host_element),
        _category_name_for_colorize(clash_result.link_element),
    )


def _build_category_pair_color_map(clash_results):
    """Deterministic (host_category, link_category) -> Color map, stable
    across repeated calls for the SAME clash_results CONTENT regardless of
    the ORDER those results happen to be in.

    Distinct pairs are collected into a set and then sorted alphabetically
    before being zipped against the fixed palette by position - so the
    mapping depends only on WHICH pairs are present, never on the order
    run_interference_check/find_clashing_pairs happened to produce them in.
    Colors cycle (modulo) once there are more distinct pairs than palette
    entries - beyond _CATEGORY_PAIR_COLOR_PALETTE's length, some pairs will
    share a color. That's an acceptable degradation (still internally
    consistent per pair within one colorize toggle) rather than a hard cap
    on how many distinct pairs can be colorized at once.
    """
    distinct_pairs = sorted(set(_category_pair_key(cr) for cr in clash_results))
    return {
        pair: _CATEGORY_PAIR_COLOR_PALETTE[index % len(_CATEGORY_PAIR_COLOR_PALETTE)]
        for index, pair in enumerate(distinct_pairs)
    }


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
    """Apply a per-(host_category, link_category)-pair color override to
    every HOST-SIDE element across `clash_results`, in `active_view`. See
    this module's "COLORIZE BY CATEGORY" section header comment (and the
    module docstring's "ADDED IN 1005" section) for why link-side elements
    are deliberately NOT touched here.

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

    EXTENSION HOOK for camera fly-to (1004) and colorize (1005, not yet
    implemented): every time the current clash changes, this window calls
    ``self.on_selection_changed(clash_result, index)``. To hook in without
    touching any navigation logic above, EITHER:
      - pass ``selection_changed_callback`` to the constructor (or set
        ``window.selection_changed_callback = your_function`` on an instance
        afterwards - ``on_selection_changed``'s default implementation just
        forwards to this callback if one is set, otherwise it's a no-op), OR
      - subclass ``ClashListWindow`` and override ``on_selection_changed``
        directly.
    ``your_function(clash_result, index)`` / the override receives the
    ``ClashResult`` now selected and its integer index in
    ``self.clash_results``. Ticket 1004 (camera fly-to, wired from
    ``__main__``, NOT from inside this class) reads ``clash_result.
    host_element`` / ``.link_element`` / ``.link_instance_id`` to compute a
    combined bounding box and reframe the view - see
    ``reframe_active_view_on_clash`` above. Do NOT reimplement Next/Previous/
    list-click handling to add new per-selection behavior - hook in here
    instead so there is only ever one navigation path.

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

        for clash_result in self.clash_results:
            self.ClashListBox.Items.Add(clash_result.describe())

        self.ClashListBox.SelectionChanged += self._on_list_selection_changed

        if self.clash_results:
            self._set_current_index(0)
        else:
            self._update_status_and_buttons()
            # Nothing to colorize either - matches the disabled Previous/
            # Next buttons' "no clashes" treatment above.
            self.ColorizeCheckBox.IsEnabled = False

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
        work is queued through ``_colorize_api_bridge`` and runs later, back
        in a valid context, via ``_ColorizeApiBridge.Execute``.
        """
        def _apply():
            active_view = doc.ActiveView
            try:
                previous_overrides = apply_colorize_overrides(
                    self.clash_results, doc, active_view
                )
            except Exception as colorize_error:
                forms.alert(
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
            output.print_md(
                "_ClashFlag: colorize by category is ON - host-side "
                "clashing elements only. Revit has no API to override an "
                "individual linked element's graphics from a host view "
                "(researched, see clashflag_runner.py's module docstring), "
                "so link-side elements are left untouched._"
            )

        _colorize_api_bridge.raise_action(_apply)

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
        """
        if not self.colorize_active:
            return

        view_id = self.colorize_view_id
        previous_overrides = self.colorize_previous_overrides
        self.colorize_active = False
        self.colorize_previous_overrides = {}
        self.colorize_view_id = None

        def _clear():
            view = doc.GetElement(view_id) if view_id else None
            if view is not None:
                try:
                    clear_colorize_overrides(doc, view, previous_overrides)
                except Exception as clear_error:
                    output.print_md(
                        "_ClashFlag: failed to fully clear colorize "
                        "overrides: {0}_".format(clear_error)
                    )
            else:
                output.print_md(
                    "_ClashFlag: the view colorize was applied to no "
                    "longer exists - its overrides could not be explicitly "
                    "cleared (they went away with the view itself)._"
                )

        _colorize_api_bridge.raise_action(_clear)

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

    def _fire_selection_hook(self):
        clash_result = None
        if 0 <= self.current_index < len(self.clash_results):
            clash_result = self.clash_results[self.current_index]
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
        "colorize-by-category" note above."""
        if self.selection_changed_callback is not None:
            self.selection_changed_callback(clash_result, index)

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
                def _on_clash_selection_changed(clash_result, index):
                    if clash_result is None:
                        return
                    reframe_active_view_on_clash(clash_result, doc, uidoc)

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

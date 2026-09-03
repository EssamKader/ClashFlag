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

Deliberately still out of scope (see specs/clash-flag.md "out of scope" +
tickets/1003+):
    - No tolerance / near-miss ("soft clash") logic - hard (real, non-zero-
      volume intersection) clashes only. The small epsilons used below exist
      ONLY to absorb floating-point noise (e.g. two solids that share a face
      exactly) - they are not a clearance/tolerance feature and are not
      user-configurable.
    - No clash list navigation, camera fly-to, or colorize-by-category
      (later US-3/4/5, tickets 1003-1005).
    - pyRevit pushbutton/bundle packaging (ticket 1006) - this is still a
      flat, directly-run script.

This script is READ-ONLY against the model: everything below only *reads*
geometry (FilteredElementCollector, Element.get_Geometry) or computes
transient, in-memory results (SolidUtils.CreateTransformed,
BooleanOperationsUtils.ExecuteBooleanOperation) - none of it creates, deletes,
or modifies any element or parameter in either document, and the scope
picker only reads UI state - no Transaction is opened anywhere in this file.
Per project ground rules ("Revit API code always wraps mutating operations in
a Transaction"), that's correct as long as nothing here starts writing to the
model - if a future ticket adds anything that writes (e.g. tagging clash
locations, storing results in a project parameter), THAT code must open its
own Transaction around just the mutating calls.
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
    ElementMulticategoryFilter,
    FilteredElementCollector,
    GeometryInstance,
    Options,
    Outline,
    RevitLinkInstance,
    Solid,
    SolidUtils,
    ViewDetailLevel,
    XYZ,
)
from System.Collections.Generic import List
from System.Windows import FontStyles, FontWeights, TextWrapping, Thickness
from System.Windows.Controls import CheckBox, StackPanel, TextBlock

from pyrevit import revit, script, forms

output = script.get_output()
doc = revit.doc


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
    clash. The fix is to transform all 8 corners of the local box and take
    the min/max of the transformed set, which is what this function does.
    """
    try:
        bbox = solid.GetBoundingBox()
    except Exception:
        return None

    if bbox is None:
        return None

    tf = bbox.Transform
    lo = bbox.Min
    hi = bbox.Max

    xs, ys, zs = [], [], []
    for x in (lo.X, hi.X):
        for y in (lo.Y, hi.Y):
            for z in (lo.Z, hi.Z):
                corner = tf.OfPoint(XYZ(x, y, z))
                xs.append(corner.X)
                ys.append(corner.Y)
                zs.append(corner.Z)

    world_min = XYZ(min(xs), min(ys), min(zs))
    world_max = XYZ(max(xs), max(ys), max(zs))

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


def run_interference_check(scope_selection):
    """Run the manual-transform interference check for one user-picked scope:
    `scope_selection.host_categories` against the active document, checked
    separately against each selected linked model in
    `scope_selection.link_selections` (each with its own category subset and
    its own placement transform).
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
        return

    total_clash_count = 0

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

    output.print_md("---")
    output.print_md(
        "**Total: {0} clash pair(s) found across {1} selected link(s).**".format(
            total_clash_count, len(scope_selection.link_selections)
        )
    )


if __name__ == "__main__":
    try:
        scope_selection = show_scope_picker(doc)
        if scope_selection is None:
            output.print_md("ClashFlag - cancelled (no scope confirmed).")
        else:
            run_interference_check(scope_selection)
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

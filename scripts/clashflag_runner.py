# -*- coding: utf-8 -*-
"""ClashFlag - T-1 tracer bullet: manual-transform interference-check runner.

Implements US-2 (revised) from specs/clash-flag.md, per
tickets/1001-interference-check-runner.md's "Phase 7 review comments (round 1
-> rework required)" section.

REWORK HISTORY: v1 of this script drove the cross-document check via
``InterferenceCheckOptions.LinkInstance2``, resting on an unverified (and,
per tickets/0004-linked-model-api-research.md's Erratum, almost certainly
wrong) assumption that ``Document.PerformInterferenceCheck`` auto-applies a
link's placement transform when checking host-vs-link. Elements read back via
``RevitLinkInstance.GetLinkDocument()`` are in the LINK's own local
coordinate space, not the host's - using them directly would silently miss
real clashes (or flag phantom ones) on any link that isn't sitting at an
identity transform relative to the host, i.e. almost always in practice.

This version instead builds the manual pipeline confirmed in
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

Deliberately out of scope for this ticket (see tickets/1002+ / spec "out of
scope"):
    - No user-facing UI or scope picker (T-2 / ticket 1002) - categories and
      the link instance name are still hardcoded constants below.
    - No tolerance / near-miss ("soft clash") logic - hard (real, non-zero-
      volume intersection) clashes only, per specs/clash-flag.md "Explicitly
      out of scope for v1". The small epsilons used below exist ONLY to
      absorb floating-point noise (e.g. two solids that share a face exactly)
      - they are not a clearance/tolerance feature and are not
      user-configurable.
    - No clash list navigation, camera fly-to, or colorize-by-category
      (later US-3/4/5).
    - Multiple loaded instances of the *same* link, each at a different
      placement (each would need its own transform + its own candidate set -
      see the note next to LINKED_MODEL_INSTANCE_NAME below). Out of scope
      for this tracer bullet, matching the original ticket's scope.

This script is READ-ONLY against the model: everything below only *reads*
geometry (FilteredElementCollector, Element.get_Geometry) or computes
transient, in-memory results (SolidUtils.CreateTransformed,
BooleanOperationsUtils.ExecuteBooleanOperation) - none of it creates, deletes,
or modifies any element or parameter in either document. Per project ground
rules ("Revit API code always wraps mutating operations in a Transaction"),
no Transaction is opened here because nothing is mutated - if a future ticket
adds anything that writes to the model (e.g. tagging clash locations, storing
results in a project parameter), THAT code must open its own Transaction
around just the mutating calls.
"""

import clr

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from Autodesk.Revit.DB import (
    BooleanOperationsUtils,
    BooleanOperationsType,
    BuiltInCategory,
    ElementCategoryFilter,
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

from pyrevit import revit, script, forms

output = script.get_output()
doc = revit.doc


# ---------------------------------------------------------------------------
# Fixed, hardcoded scope for this tracer-bullet ticket (T-2 / ticket 1002 makes
# this user-configurable). Chosen as a representative, commonly-clashing MEP-vs-
# structural pair: structural framing (beams) in the host model against duct
# curves in the linked model.
# ---------------------------------------------------------------------------
HOST_CATEGORY = BuiltInCategory.OST_StructuralFraming
LINK_CATEGORY = BuiltInCategory.OST_DuctCurves

# Hardcoded linked model instance to check against. There is no live Revit
# session in this sandbox to read a real link name from, so this is a stand-in
# value - update it to match the RevitLinkInstance name (as it appears in the
# Project Browser / Manage Links) in whatever model this is first run against.
#
# SCOPE NOTE (out of scope for this ticket, per tickets/1001 tracer-bullet
# scope): if the SAME link document is loaded more than once at different
# placements, find_link_instance() below returns only the first loaded match
# by name, and every downstream transform/candidate-set is built for that one
# RevitLinkInstance only. Other placements of the same link are silently not
# checked. Proper multi-instance support needs each RevitLinkInstance handled
# as its own (transform, candidate-set) pair - tracked as future scope, not
# this ticket's.
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


def find_link_instance(host_doc, link_name):
    """Locate the hardcoded RevitLinkInstance by name.

    Raises ClashFlagError with a clear message if the link instance isn't
    present, or is present but not currently loaded (we need the linked
    document actually loaded/resolvable to read its geometry).
    """
    collector = FilteredElementCollector(host_doc).OfClass(RevitLinkInstance)

    matched_but_unloaded = False

    for link_instance in collector:
        try:
            instance_name = link_instance.Name
        except Exception:
            instance_name = None

        if instance_name and link_name in instance_name:
            link_doc = link_instance.GetLinkDocument()
            if link_doc is None:
                # Name matched, but the link is unloaded - keep scanning in
                # case another placement of the same link IS loaded, but
                # remember this so the error message is accurate if not.
                matched_but_unloaded = True
                continue
            return link_instance, link_doc

    if matched_but_unloaded:
        raise ClashFlagError(
            "Found a RevitLinkInstance matching '{0}' but it is not loaded "
            "(unloaded/unresolved link). Load the link and re-run.".format(link_name)
        )

    raise ClashFlagError(
        "No loaded RevitLinkInstance found matching '{0}'. Update "
        "LINKED_MODEL_INSTANCE_NAME in this script to match a link instance "
        "name in the current model (Manage tab > Manage Links), and make sure "
        "it is loaded.".format(link_name)
    )


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


def collect_candidate_solids(source_doc, category, link_transform=None):
    """Collect (element, [solids...]) pairs for every element of `category`
    in `source_doc`, with each solid ALREADY in host coordinate space.

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
        ElementCategoryFilter(category)
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


def run_interference_check():
    output.print_md("## ClashFlag - interference check runner (T-1 tracer bullet)")
    output.print_md(
        "Fixed scope: **{0}** (host) vs **{1}** (linked)".format(
            HOST_CATEGORY, LINK_CATEGORY
        )
    )
    output.print_md(
        "Detection method: manual transform pipeline (bbox pre-filter + "
        "`SolidUtils.CreateTransformed` + `BooleanOperationsUtils.Intersect`) "
        "per tickets/1001 rework - no tolerance/near-miss logic."
    )

    link_instance, link_doc = find_link_instance(doc, LINKED_MODEL_INSTANCE_NAME)

    output.print_md("Linked model: **{0}**".format(link_doc.Title))

    # Maps LINK-LOCAL coordinates -> HOST coordinates. Chosen over
    # GetTransform() because it also folds in true-north, matching
    # tickets/0004's Erratum guidance for cross-document geometry work.
    link_transform = link_instance.GetTotalTransform()

    # Host candidates: already host-space, no transform.
    host_candidates, host_skipped = collect_candidate_solids(
        doc, HOST_CATEGORY, link_transform=None
    )

    # Link candidates: collected from link_doc (link-local space), then
    # transformed to host space inside collect_candidate_solids using
    # link_transform. From here on, every solid involved is host-space.
    link_candidates, link_skipped = collect_candidate_solids(
        link_doc, LINK_CATEGORY, link_transform=link_transform
    )

    output.print_md(
        "Host candidates: **{0}** ({1} skipped - no usable solid geometry)".format(
            len(host_candidates), host_skipped
        )
    )
    output.print_md(
        "Linked candidates: **{0}** ({1} skipped - no usable solid geometry)".format(
            len(link_candidates), link_skipped
        )
    )

    if not host_candidates or not link_candidates:
        output.print_md(
            "**No interferences found** - one side has zero candidates with "
            "usable solid geometry, so no pair can be checked."
        )
        return

    clashing_pairs = find_clashing_pairs(host_candidates, link_candidates)

    if not clashing_pairs:
        output.print_md("**No interferences found** for the fixed scope above.")
        return

    output.print_md("**{0} clash pair(s) found:**".format(len(clashing_pairs)))

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


if __name__ == "__main__":
    try:
        run_interference_check()
    except ClashFlagError as clash_flag_error:
        # Expected, actionable setup problem (bad/missing link name) - show the
        # user a clear message instead of a raw stack trace.
        forms.alert(str(clash_flag_error), title="ClashFlag - setup error")
    except Exception as unexpected_error:
        # Unexpected Revit API failure (e.g. bad model state) - report it
        # through the pyRevit console rather than letting Revit itself crash
        # or show an unhandled-exception dialog.
        output.print_md("**ClashFlag failed unexpectedly:**")
        output.print_md("```\n{0}\n```".format(unexpected_error))
        raise

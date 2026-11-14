"""Placement measurements shared by the donor routes, with route-specific policies."""
from ..trajectory_experiment import crossing_pairs
from .contacts import BRUSH_WIDTH, contact_pairs, segment_clearance


def split_neighbor_support(index, neighbor, current, reference):
    old = [current[index], current[neighbor]]
    ref = [reference[index], reference[neighbor]]
    return (bool(crossing_pairs(old) or crossing_pairs(ref)),
            bool(contact_pairs(old) or contact_pairs(ref)))


def split_relationship_failure(placed, index, current, reference, support):
    """Keep the original neighbor, crossing and contact short-circuit order."""
    for j, neighbor in enumerate(current):
        if j == index:
            continue
        if j not in support:
            support[j] = split_neighbor_support(index, j, current, reference)
        cross, contact = support[j]
        after = [placed, neighbor]
        if not cross and crossing_pairs(after):
            return "crossing", j
        if not contact and contact_pairs(after):
            return "brush contact", j
    return None


def split_relationship_details(placed, index, current, reference):
    """Optional measurements. The official single-stroke rule ignores losses."""
    rows = []
    for j, neighbor in enumerate(current):
        if j == index:
            continue
        old = [current[index], neighbor]
        ref = [reference[index], reference[j]]
        trial = [placed, neighbor]
        before_cross, ref_cross, after_cross = (bool(crossing_pairs(pair)) for pair in (old, ref, trial))
        before_contact, ref_contact, after_contact = (bool(contact_pairs(pair)) for pair in (old, ref, trial))
        if not any((before_cross, ref_cross, after_cross, before_contact, ref_contact, after_contact)):
            continue
        rows.append({
            "orders": [index + 1, j + 1],
            "before": {"crossing": before_cross, "contact": before_contact},
            "reference": {"crossing": ref_cross, "contact": ref_contact},
            "after": {"crossing": after_cross, "contact": after_contact},
            "clearance_em": segment_clearance(*trial), "brush_width_em": BRUSH_WIDTH,
            "new_unsupported_crossing": after_cross and not (before_cross or ref_cross),
            "new_unsupported_contact": after_contact and not (before_contact or ref_contact),
            "lost_crossing": before_cross and not after_cross,
            "lost_contact": before_contact and not after_contact,
        })
    return rows


def connected_relationship_failure(placed, outside, original):
    """The connected policy compares each physical segment with all replaced slots."""
    for neighbor_index, neighbor in enumerate(outside):
        for segment_index, (trace, expected) in enumerate(zip(placed, original, strict=True)):
            if crossing_pairs([trace, neighbor]) and not any(
                crossing_pairs([old, neighbor]) for old in expected
            ):
                return "crossing", segment_index, neighbor_index
            clearance = segment_clearance(trace, neighbor)
            if clearance <= BRUSH_WIDTH and min(
                segment_clearance(old, neighbor) for old in expected
            ) > BRUSH_WIDTH:
                return "brush contact", segment_index, neighbor_index
    return None


def crossing_delta(before, after):
    return crossing_pairs(after) - crossing_pairs(before)


def cross_boundary(pairs, owned):
    return {(a, b) for a, b in pairs if (a in owned) != (b in owned)}


def component_boundary_contacts(before, after, owned, reference):
    # Maintain the existing order and exact contact_pairs threshold.
    new = cross_boundary(contact_pairs(after) - contact_pairs(before), owned)
    lost = cross_boundary((contact_pairs(before) & reference) - contact_pairs(after), owned)
    return new, lost

"""Optical punctuation bearings; original em size and baseline remain fixed."""

import unicodedata


def punctuation_bearings(character, bounds, em, radius):
    """Return advance/origin only for punctuation, excluding connector characters."""
    category = unicodedata.category(character)
    if not category.startswith('P') or category == 'Pc':
        return None
    ink_width = bounds[2] - bounds[0]
    clearance = .04
    # Chinese punctuation receives no half/full-em reservation either. Use the
    # same minimal optical clearance as handwritten letters on both sides.
    return (ink_width + 2 * clearance) * em + 2 * radius, radius + (clearance - bounds[0]) * em

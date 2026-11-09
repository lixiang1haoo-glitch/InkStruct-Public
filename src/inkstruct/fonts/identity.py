"""Exact font release references carried alongside embedded glyphs."""

KEYS = ('font_id', 'release_id', 'core_hash')


def release_identity(record):
    identity = tuple(record.get(key) for key in KEYS)
    if (any(not isinstance(value, str) or not value or len(value) > 128 for value in identity)
            or len(identity[2]) != 64 or any(c not in '0123456789abcdef' for c in identity[2])):
        return None
    return identity


def embedded_identity(glyphs):
    identities = set()
    for glyph in glyphs:
        core = glyph.font_core
        if core and (identity := release_identity(core['identity'])):
            identities.add(identity)
            if len(identities) > 1:
                return None
    return next(iter(identities), None)

"""Structured constructor failures and read-only JSON source locations."""

import json


class TemplateValidationError(ValueError):
    def __init__(self, code, message, paths=((),), *, source_offset=None):
        super().__init__(message)
        self.code = code
        self.paths = tuple(tuple(p) for p in paths)
        self.source_offset = source_offset

    def prefixed(self, *prefix):
        return TemplateValidationError(
            self.code,
            str(self),
            tuple((*prefix, *p) for p in self.paths),
            source_offset=self.source_offset,
        )

    def report(self):
        return {
            "code": self.code,
            "message": str(self),
            "targets": [
                {
                    "path": list(p),
                    "pointer": "".join(
                        "/" + str(v).replace("~", "~0").replace("/", "~1") for v in p
                    ),
                }
                for p in self.paths
            ],
            "source_offset": self.source_offset,
        }


def converted(value, cls, *path):
    try:
        return cls(**value) if isinstance(value, dict) else value
    except TemplateValidationError as error:
        raise error.prefixed(*path) from error
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise TemplateValidationError("template-object-invalid", str(error), (path,)) from error


def json_value_span(text, path):
    """Return a JSON value's scalar offsets, following last-key-wins decoding."""
    decoder = json.JSONDecoder()
    decoder.decode(text)  # Only navigate syntactically complete drafts.

    def space(pos):
        while pos < len(text) and text[pos] in " \r\n\t":
            pos += 1
        return pos

    start = space(0)
    _, end = decoder.raw_decode(text, start)
    for part in path:
        found = None
        pos = space(start + 1)
        if text[start] == "{" and isinstance(part, str):
            while text[pos] != "}":
                key, pos = decoder.raw_decode(text, pos)
                pos = space(space(pos) + 1)  # Colon.
                _, stop = decoder.raw_decode(text, pos)
                if key == part:
                    found = (pos, stop)
                pos = space(stop)
                if text[pos] == "}":
                    break
                pos = space(pos + 1)
        elif text[start] == "[" and type(part) is int:
            index = 0
            while text[pos] != "]":
                _, stop = decoder.raw_decode(text, pos)
                if index == part:
                    found = (pos, stop)
                    break
                pos = space(stop)
                if text[pos] == "]":
                    break
                pos = space(pos + 1)
                index += 1
        if found is None:
            return None
        start, end = found
    return start, end

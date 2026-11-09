"""Immutable syntax, not a TeX execution environment or a font outline renderer."""

from dataclasses import dataclass

from ..document.schema import Diagnostic, SourceSpan

MATH_VERSION = "inkstruct-math-v1"


@dataclass(frozen=True)
class MathNode:
    kind: str
    span: SourceSpan
    children: tuple["MathNode", ...] = ()
    value: str = ""
    math_class: str = "ord"
    attributes: tuple[tuple[str, str], ...] = ()
    occurrence_id: str | None = None

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass(frozen=True)
class MathParseResult:
    source: str
    span: SourceSpan
    root: MathNode | None
    diagnostics: tuple[Diagnostic, ...]
    version: str = MATH_VERSION

    @property
    def valid(self):
        return self.root is not None and not self.diagnostics

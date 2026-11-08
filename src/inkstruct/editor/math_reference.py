"""Latin Modern Math glyphs for settings previews, with no system-font fallback."""

from importlib.resources import files
from struct import unpack_from
from zipfile import ZipFile

from PySide6 import QtCore, QtGui

from ..math.handwritten import MathOutline

FONT_RESOURCE = "lm-math-1.959.zip"
FONT_MEMBER = "lm-math/opentype/latinmodern-math.otf"
ITALIC = {
    **{c: chr(0x1D434 + i) for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")},
    **{c: chr(0x1D44E + i) for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")},
    **{c: chr(0x1D6E2 + i) for i, c in enumerate("ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡϴΣΤΥΦΧΨΩ∇")},
    **{c: chr(0x1D6FC + i) for i, c in enumerate("αβγδεζηθικλμνξοπρςστυφχψω∂ϵϑϰϕϱϖ")},
    "h": "ℎ",
}


class MathReferenceFont:
    def __init__(self):
        with files(__package__).joinpath("resources", FONT_RESOURCE).open("rb") as stream:
            with ZipFile(stream) as archive:
                data = archive.read(FONT_MEMBER)
        self.font = QtGui.QRawFont()
        self.font.loadFromData(QtCore.QByteArray(data), 1000, QtGui.QFont.PreferNoHinting)
        if not self.font.isValid() or self.font.familyName() != "Latin Modern Math":
            raise ValueError("无法读取随附的 Latin Modern Math")
        table = bytes(self.font.fontTable("MATH"))
        constants, = unpack_from(">H", table, 4)
        axis, = unpack_from(">h", table, constants + 12)
        self.axis = axis / self.font.unitsPerEm()
        self.paths = {}
        self.metrics = {}

    def measure(self, character, letter_style):
        codepoint = ITALIC.get(character, character) if letter_style == "italic" else character
        if codepoint not in self.metrics:
            glyph, = self.font.glyphIndexesForString(codepoint)
            if not glyph:
                raise ValueError(f"Latin Modern Math 缺少 {character}（U+{ord(codepoint):04X}）")
            if glyph not in self.paths:
                self.paths[glyph] = self.font.pathForGlyph(glyph)
            bounds = self.paths[glyph].boundingRect()
            advance, = self.font.advancesForGlyphIndexes([glyph], QtGui.QRawFont.UseDesignMetrics)
            self.metrics[codepoint] = MathOutline(
                glyph, codepoint, tuple(v / 1000 for v in
                    (bounds.left(), bounds.top(), bounds.right(), bounds.bottom())),
                advance.x() / 1000, self.axis,
            )
        return self.metrics[codepoint]

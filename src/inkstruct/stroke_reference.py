from __future__ import annotations

import gzip
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

Point = tuple[float, float]
Stroke = list[Point]
StrokeReferenceMap = dict[str, list[Stroke]]

REFERENCE_SCHEMA_VERSION = "inkstruct_stroke_references_v1"
REFERENCE_QUANTIZATION = 1024


def highlighted_stroke_index(
    written_stroke_count: int, *, pen_down: bool, expected_stroke_count: int
) -> int | None:
    """Return the current stroke while writing, otherwise the next stroke.

    ``TrajectoryCanvas`` adds the active stroke on TabletPress, so a pen-down
    count includes the stroke currently being written.  A pen-up count contains
    only completed strokes.
    """
    expected = max(0, int(expected_stroke_count))
    count = max(0, int(written_stroke_count))
    if expected == 0:
        return None
    if pen_down:
        active = max(0, count - 1)
        return active if active < expected else None
    return count if count < expected else None


def encode_reference_bundle(
    references: Mapping[str, Sequence[Sequence[Sequence[float]]]],
    *,
    source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    encoded: dict[str, list[list[list[int]]]] = {}
    for character, strokes in references.items():
        encoded[str(character)] = [
            [
                [
                    round(min(1.0, max(0.0, float(point[0]))) * REFERENCE_QUANTIZATION),
                    round(min(1.0, max(0.0, float(point[1]))) * REFERENCE_QUANTIZATION),
                ]
                for point in stroke
            ]
            for stroke in strokes
        ]
    return {
        "schema_version": REFERENCE_SCHEMA_VERSION,
        "quantization": REFERENCE_QUANTIZATION,
        "character_count": len(encoded),
        "source": dict(source or {}),
        "strokes": encoded,
    }


def write_reference_bundle(
    path: Path,
    references: Mapping[str, Sequence[Sequence[Sequence[float]]]],
    *,
    source: Mapping[str, Any] | None = None,
) -> None:
    payload = encode_reference_bundle(references, source=source)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9, newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
        stream.write("\n")


def load_reference_bundle(path: Path) -> StrokeReferenceMap:
    with gzip.open(Path(path), "rt", encoding="utf-8") as stream:
        payload = json.load(stream)
    if payload.get("schema_version") != REFERENCE_SCHEMA_VERSION:
        raise RuntimeError("标准笔顺参考数据版本不受支持")
    quantization = int(payload.get("quantization", 0))
    if quantization <= 0:
        raise RuntimeError("标准笔顺参考数据缺少有效量化参数")
    result: StrokeReferenceMap = {}
    for character, strokes in payload.get("strokes", {}).items():
        result[str(character)] = [
            [(float(point[0]) / quantization, float(point[1]) / quantization) for point in stroke]
            for stroke in strokes
        ]
    if int(payload.get("character_count", -1)) != len(result):
        raise RuntimeError("标准笔顺参考数据字符数量校验失败")
    return result


def create_stroke_reference_widget_class(QtCore, QtGui, QtWidgets):
    """Create the Qt widget lazily so non-desktop InkStruct imports stay lightweight."""

    class StrokeReferenceWidget(QtWidgets.QWidget):
        def __init__(
            self,
            reference_provider: Callable[[str], Sequence[Sequence[Sequence[float]]] | None],
            parent=None,
        ):
            super().__init__(parent)
            self._reference_provider = reference_provider
            self._character: str | None = None
            self._strokes: list[Stroke] = []
            self._written_stroke_count = 0
            self._pen_down = False
            self.setObjectName("strokeReferenceWidget")
            self.setMinimumSize(230, 260)
            self.setMaximumWidth(330)
            self.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Preferred,
                QtWidgets.QSizePolicy.Policy.Expanding,
            )
            self.setToolTip("绿色表示当前正在书写或下一笔待写的标准笔画")

        def set_state(
            self,
            character: str | None,
            written_stroke_count: int,
            pen_down: bool,
        ) -> None:
            normalized = character if character and len(character) == 1 else None
            if normalized != self._character:
                self._character = normalized
                value = self._reference_provider(normalized) if normalized else None
                self._strokes = [
                    [(float(point[0]), float(point[1])) for point in stroke]
                    for stroke in (value or [])
                ]
            self._written_stroke_count = max(0, int(written_stroke_count))
            self._pen_down = bool(pen_down)
            self.update()

        def sizeHint(self):
            return QtCore.QSize(280, 440)

        @staticmethod
        def _smooth_path(points, box):
            mapped = [
                QtCore.QPointF(
                    box.left() + min(1.0, max(0.0, point[0])) * box.width(),
                    box.top() + min(1.0, max(0.0, point[1])) * box.height(),
                )
                for point in points
            ]
            path = QtGui.QPainterPath()
            if not mapped:
                return path
            path.moveTo(mapped[0])
            if len(mapped) == 1:
                return path
            for index in range(1, len(mapped) - 1):
                midpoint = (mapped[index] + mapped[index + 1]) / 2.0
                path.quadTo(mapped[index], midpoint)
            path.lineTo(mapped[-1])
            return path

        def paintEvent(self, event) -> None:
            del event
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            painter.fillRect(self.rect(), QtGui.QColor("#F8FAFC"))

            margin = 14.0
            title_height = 32.0
            status_height = 34.0
            available_height = max(80.0, self.height() - title_height - status_height - 3 * margin)
            side = min(max(80.0, self.width() - 2 * margin), available_height)
            left = (self.width() - side) / 2.0
            top = margin + title_height
            box = QtCore.QRectF(left, top, side, side)

            title_font = painter.font()
            title_font.setPointSize(11)
            title_font.setWeight(QtGui.QFont.Weight.DemiBold)
            painter.setFont(title_font)
            painter.setPen(QtGui.QColor("#334155"))
            title = f"笔顺提示  ·  {self._character}" if self._character else "笔顺提示"
            painter.drawText(
                QtCore.QRectF(margin, margin, self.width() - 2 * margin, title_height),
                int(QtCore.Qt.AlignmentFlag.AlignCenter),
                title,
            )

            painter.fillRect(box, QtGui.QColor("#FFFFFF"))
            painter.setPen(QtGui.QPen(QtGui.QColor("#94A3B8"), 1.25))
            painter.drawRect(box)
            grid_pen = QtGui.QPen(
                QtGui.QColor("#CBD5E1"),
                1.0,
                QtCore.Qt.PenStyle.DashLine,
            )
            painter.setPen(grid_pen)
            center_x = box.left() + box.width() / 2.0
            center_y = box.top() + box.height() / 2.0
            painter.drawLine(
                QtCore.QPointF(center_x, box.top()), QtCore.QPointF(center_x, box.bottom())
            )
            painter.drawLine(
                QtCore.QPointF(box.left(), center_y), QtCore.QPointF(box.right(), center_y)
            )
            painter.drawLine(box.topLeft(), box.bottomRight())
            painter.drawLine(box.topRight(), box.bottomLeft())

            expected = len(self._strokes)
            highlight = highlighted_stroke_index(
                self._written_stroke_count,
                pen_down=self._pen_down,
                expected_stroke_count=expected,
            )
            completed = (
                max(0, self._written_stroke_count - 1)
                if self._pen_down
                else self._written_stroke_count
            )

            def draw_stroke(index: int, color: str, width: float) -> None:
                path = self._smooth_path(self._strokes[index], box)
                pen = QtGui.QPen(
                    QtGui.QColor(color),
                    width,
                    QtCore.Qt.PenStyle.SolidLine,
                    QtCore.Qt.PenCapStyle.RoundCap,
                    QtCore.Qt.PenJoinStyle.RoundJoin,
                )
                painter.setPen(pen)
                painter.drawPath(path)

            for stroke_index in range(expected):
                if stroke_index == highlight:
                    continue
                if stroke_index < completed:
                    draw_stroke(stroke_index, "#64748B", 4.5)
                else:
                    draw_stroke(stroke_index, "#CBD5E1", 3.6)
            if highlight is not None:
                draw_stroke(highlight, "#16A34A", 7.0)
                if self._strokes[highlight]:
                    start = self._strokes[highlight][0]
                    start_point = QtCore.QPointF(
                        box.left() + start[0] * box.width(),
                        box.top() + start[1] * box.height(),
                    )
                    painter.setBrush(QtGui.QColor("#16A34A"))
                    painter.setPen(QtGui.QPen(QtGui.QColor("#FFFFFF"), 1.5))
                    painter.drawEllipse(start_point, 4.2, 4.2)

            status_rect = QtCore.QRectF(
                margin,
                box.bottom() + margin,
                self.width() - 2 * margin,
                status_height,
            )
            status_font = painter.font()
            status_font.setPointSize(10)
            status_font.setWeight(QtGui.QFont.Weight.DemiBold)
            painter.setFont(status_font)
            if not self._character:
                status = "载入任务后显示"
                status_color = "#64748B"
            elif not self._strokes:
                status = "暂无标准笔顺参考"
                status_color = "#B45309"
            elif highlight is None:
                status = f"笔画已完成：{min(self._written_stroke_count, expected)} / {expected}"
                status_color = "#15803D"
            elif self._pen_down:
                status = f"正在书写：第 {highlight + 1} / {expected} 笔"
                status_color = "#15803D"
            else:
                status = f"下一笔：第 {highlight + 1} / {expected} 笔"
                status_color = "#15803D"
            painter.setPen(QtGui.QColor(status_color))
            painter.drawText(
                status_rect,
                int(QtCore.Qt.AlignmentFlag.AlignCenter),
                status,
            )

    return StrokeReferenceWidget

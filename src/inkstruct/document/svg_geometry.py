"""Bounded SVG centreline geometry; all flattening error is in final millimetres."""

import math
import re

NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
TOKEN = re.compile(rf"[A-Za-z]|{NUMBER}")
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
MAX_POINTS = 50_000


def numbers(value):
    tokens = re.findall(NUMBER, value)
    if re.sub(NUMBER, "", value).strip(" ,\t\r\n"):
        raise ValueError("Invalid SVG numbers")
    result = tuple(float(v) for v in tokens)
    if any(not math.isfinite(v) or abs(v) > 1e9 or 0 < abs(v) < 1e-12 for v in result):
        raise ValueError("SVG coordinate exceeds finite numeric budget")
    return result


def multiply(a, b):
    x, y, z, w, u, v = a
    c, d, e, f, g, h = b
    result = (
        x * c + z * d,
        y * c + w * d,
        x * e + z * f,
        y * e + w * f,
        x * g + z * h + u,
        y * g + w * h + v,
    )
    if any(not math.isfinite(n) or abs(n) > 1e9 for n in result):
        raise ValueError("SVG transform exceeds numeric budget")
    return result


def point(matrix, p):
    a, b, c, d, e, f = matrix
    result = (a * p[0] + c * p[1] + e, b * p[0] + d * p[1] + f)
    if any(not math.isfinite(n) or abs(n) > 1e9 for n in result):
        raise ValueError("SVG point exceeds numeric budget")
    return result


def transform(value):
    result = IDENTITY
    pattern = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^()]*)\)")
    pos = 0
    for match in pattern.finditer(value):
        if value[pos : match.start()].strip(" ,\t\r\n"):
            raise ValueError("Unsupported SVG transform")
        kind, body = match.groups()
        v = numbers(body)
        if kind == "matrix" and len(v) == 6:
            m = v
        elif kind == "translate" and len(v) in (1, 2):
            m = (1, 0, 0, 1, v[0], v[1] if len(v) == 2 else 0)
        elif kind == "scale" and len(v) in (1, 2):
            m = (v[0], 0, 0, v[-1], 0, 0)
        elif kind == "rotate" and len(v) in (1, 3):
            c, s = math.cos(math.radians(v[0])), math.sin(math.radians(v[0]))
            m = (c, s, -s, c, 0, 0)
            if len(v) == 3:
                m = multiply(multiply((1, 0, 0, 1, v[1], v[2]), m), (1, 0, 0, 1, -v[1], -v[2]))
        elif kind in ("skewX", "skewY") and len(v) == 1:
            k = math.tan(math.radians(v[0]))
            m = (1, 0, k, 1, 0, 0) if kind == "skewX" else (1, k, 0, 1, 0, 0)
        else:
            raise ValueError("Invalid SVG transform arguments")
        result = multiply(result, m)
        pos = match.end()
    if value[pos:].strip(" ,\t\r\n"):
        raise ValueError("Unsupported SVG transform")
    if abs(result[0] * result[3] - result[1] * result[2]) < 1e-15:
        raise ValueError("Singular SVG transform")
    return result


def distance_segment(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    denom = dx * dx + dy * dy
    t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / denom)) if denom else 0
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


class Flattener:
    def __init__(self, tolerance):
        if not math.isfinite(tolerance) or not 0.001 <= tolerance <= 1:
            raise ValueError("SVG tolerance must be within 0.001–1 mm")
        self.tolerance = tolerance
        self.paths = []
        self.current = []
        self.count = 0

    def add(self, p):
        self.count += 1
        if self.count > MAX_POINTS:
            raise ValueError("SVG flattened point budget exceeded")
        if not self.current or self.current[-1] != p:
            self.current.append(p)

    def finish(self):
        if self.current:
            if len(self.current) < 2:
                raise ValueError("SVG isolated points need an explicit calibrated dot path")
            self.paths.append(tuple(self.current))
            self.current = []

    def bezier(self, controls, depth=0):
        if (
            max(distance_segment(p, controls[0], controls[-1]) for p in controls[1:-1])
            <= self.tolerance
        ):
            self.add(controls[-1])
            return
        if depth >= 24:
            raise ValueError("SVG curve subdivision budget exceeded")
        levels = [controls]
        while len(levels[-1]) > 1:
            levels.append(
                tuple(
                    ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                    for a, b in zip(levels[-1], levels[-1][1:])
                )
            )
        self.bezier(tuple(v[0] for v in levels), depth + 1)
        self.bezier(tuple(v[-1] for v in reversed(levels)), depth + 1)

    def arc(self, start, values, end, matrix):
        rx, ry, rotation, large, sweep = values
        if large not in (0, 1) or sweep not in (0, 1) or rx < 0 or ry < 0:
            raise ValueError("Invalid SVG arc radii or flags")
        if start == end:
            return
        if rx == 0 or ry == 0:
            self.add(point(matrix, end))
            return
        c, s = math.cos(math.radians(rotation)), math.sin(math.radians(rotation))
        dx, dy = (start[0] - end[0]) / 2, (start[1] - end[1]) / 2
        x, y = c * dx + s * dy, -s * dx + c * dy
        factor = math.hypot(x / rx, y / ry)
        if factor > 1:
            rx, ry = rx * factor, ry * factor
        # Normalized endpoint-to-centre conversion, avoiding fourth-power overflow.
        xx, yy = x / rx, y / ry
        denom = xx * xx + yy * yy
        k = math.sqrt(max(0, (1 - denom) / denom)) * (-1 if large == sweep else 1)
        cx, cy = k * rx * yy, -k * ry * xx
        centre = (
            c * cx - s * cy + (start[0] + end[0]) / 2,
            s * cx + c * cy + (start[1] + end[1]) / 2,
        )
        u, v = ((x - cx) / rx, (y - cy) / ry), ((-x - cx) / rx, (-y - cy) / ry)
        theta = math.atan2(u[1], u[0])
        delta = math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1])
        if sweep and delta < 0:
            delta += 2 * math.pi
        if not sweep and delta > 0:
            delta -= 2 * math.pi
        a, b, e, d, _, _ = matrix
        ux, uy = a * rx * c + e * rx * s, b * rx * c + d * rx * s
        vx, vy = -a * ry * s + e * ry * c, -b * ry * s + d * ry * c
        # Linear interpolation error <= max|r''| * h^2 / 8, after the full affine map.
        bound = math.sqrt(ux * ux + uy * uy + vx * vx + vy * vy)
        count = max(1, math.ceil(abs(delta) * math.sqrt(bound / (8 * self.tolerance))))
        if count + self.count > MAX_POINTS:
            raise ValueError("SVG flattened point budget exceeded")
        for i in range(1, count):
            angle = theta + delta * i / count
            self.add(
                point(
                    matrix,
                    (
                        centre[0] + rx * c * math.cos(angle) - ry * s * math.sin(angle),
                        centre[1] + rx * s * math.cos(angle) + ry * c * math.sin(angle),
                    ),
                )
            )
        self.add(point(matrix, end))

    def path(self, data, matrix):
        matches = list(TOKEN.finditer(data))
        pos = 0
        for match in matches:
            if data[pos : match.start()].strip(" ,\t\r\n"):
                raise ValueError("Invalid SVG path syntax")
            pos = match.end()
        if data[pos:].strip(" ,\t\r\n"):
            raise ValueError("Invalid SVG path syntax")
        tokens = [m.group() for m in matches]
        i, command, previous = 0, None, None
        current, start, cubic, quadratic = (0.0, 0.0), None, None, None
        sizes = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}
        while i < len(tokens):
            if tokens[i].isalpha():
                command = tokens[i]
                i += 1
                if command.upper() == "Z":
                    if start is None:
                        raise ValueError("Closepath without moveto")
                    self.add(point(matrix, start))
                    current = start
                    self.finish()
                    previous, cubic, quadratic, command = "Z", None, None, None
                    continue
            if command is None or command.upper() not in sizes:
                raise ValueError("Unsupported SVG path command")
            kind = command.upper()
            count = sizes[kind]
            if i + count > len(tokens) or any(t.isalpha() for t in tokens[i : i + count]):
                raise ValueError("Incomplete SVG path command")
            v = numbers(" ".join(tokens[i : i + count]))
            i += count
            relative = command.islower()

            def coord(x, y, current=current, relative=relative):
                return (x + current[0], y + current[1]) if relative else (x, y)

            if start is None and kind != "M":
                raise ValueError("SVG path must begin with moveto")
            if kind == "M":
                self.finish()
                current = coord(*v)
                start = current
                self.add(point(matrix, current))
                command = "l" if relative else "L"
            else:
                if not self.current:
                    self.add(point(matrix, current))
                if kind == "H":
                    end = (v[0] + current[0] if relative else v[0], current[1])
                elif kind == "V":
                    end = (current[0], v[0] + current[1] if relative else v[0])
                else:
                    end = coord(*v[-2:])
                if kind in "LHV":
                    self.add(point(matrix, end))
                elif kind in "CS":
                    p1 = (
                        coord(*v[:2])
                        if kind == "C"
                        else (
                            (2 * current[0] - cubic[0], 2 * current[1] - cubic[1])
                            if previous in ("C", "S")
                            else current
                        )
                    )
                    p2 = coord(*v[-4:-2])
                    self.bezier(tuple(point(matrix, p) for p in (current, p1, p2, end)))
                    cubic = p2
                elif kind in "QT":
                    p1 = (
                        coord(*v[:2])
                        if kind == "Q"
                        else (
                            (2 * current[0] - quadratic[0], 2 * current[1] - quadratic[1])
                            if previous in ("Q", "T")
                            else current
                        )
                    )
                    self.bezier(tuple(point(matrix, p) for p in (current, p1, end)))
                    quadratic = p1
                elif kind == "A":
                    self.arc(current, v[:5], end, matrix)
                current = end
            if kind not in "CS":
                cubic = None
            if kind not in "QT":
                quadratic = None
            previous = kind
        self.finish()

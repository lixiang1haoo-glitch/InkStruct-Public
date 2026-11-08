"""Bounded, explicit TeX-like grammar with scalar provenance for every node.

No macro expansion, file access, package loading, comments, or arbitrary commands.
Unsupported syntax fails closed while the caller retains the unmodified source.
"""

from dataclasses import replace

from ..assets.glyph_provider import is_han
from ..document.break_commands import FRAME_COMMANDS, LINE_COMMANDS, PAGE_COMMANDS, scan_break
from ..document.schema import Diagnostic, SourceSpan
from ..document.source_map import MappedText
from .schema import MathNode, MathParseResult

GREEK = dict(
    zip(
        [
            "alpha",
            "beta",
            "gamma",
            "delta",
            "epsilon",
            "zeta",
            "eta",
            "theta",
            "iota",
            "kappa",
            "lambda",
            "mu",
            "nu",
            "xi",
            "omicron",
            "pi",
            "rho",
            "sigma",
            "tau",
            "upsilon",
            "phi",
            "chi",
            "psi",
            "omega",
        ],
        "αβγδεζηθικλμνξοπρστυφχψω",
        strict=True,
    )
)
GREEK.update(
    dict(
        zip(
            [
                "Gamma",
                "Delta",
                "Theta",
                "Lambda",
                "Xi",
                "Pi",
                "Sigma",
                "Upsilon",
                "Phi",
                "Psi",
                "Omega",
            ],
            "ΓΔΘΛΞΠΣΥΦΨΩ",
            strict=True,
        )
    )
)
GREEK.update(
    epsilon="ϵ",
    phi="ϕ",
    varepsilon="ε",
    vartheta="ϑ",
    varpi="ϖ",
    varrho="ϱ",
    varsigma="ς",
    varphi="φ",
)
SYMBOLS = {
    **GREEK,
    "times": "×",
    "cdot": "⋅",
    "div": "÷",
    "pm": "±",
    "mp": "∓",
    "le": "≤",
    "leq": "≤",
    "ge": "≥",
    "geq": "≥",
    "ne": "≠",
    "neq": "≠",
    "approx": "≈",
    "equiv": "≡",
    "sim": "∼",
    "propto": "∝",
    "infty": "∞",
    "partial": "∂",
    "hbar": "ℏ",
    "nabla": "∇",
    "in": "∈",
    "notin": "∉",
    "ni": "∋",
    "emptyset": "∅",
    "subset": "⊂",
    "subseteq": "⊆",
    "supset": "⊃",
    "supseteq": "⊇",
    "cup": "∪",
    "cap": "∩",
    "to": "→",
    "rightarrow": "→",
    "leftarrow": "←",
    "leftrightarrow": "↔",
    "uparrow": "↑",
    "downarrow": "↓",
    "Rightarrow": "⇒",
    "Leftarrow": "⇐",
    "Leftrightarrow": "⇔",
    "forall": "∀",
    "exists": "∃",
    "neg": "¬",
    "land": "∧",
    "lor": "∨",
    "perp": "⊥",
    "parallel": "∥",
    "angle": "∠",
    "prime": "′",
    "sum": "∑",
    "prod": "∏",
    "int": "∫",
    "oint": "∮",
    "circ": "∘",
    "degree": "°",
    "ldots": "…",
    "cdots": "⋯",
    "vert": "|",
    "Vert": "‖",
    "langle": "⟨",
    "rangle": "⟩",
    "lbrace": "{",
    "rbrace": "}",
    "lvert": "|",
    "rvert": "|",
    "lVert": "‖",
    "rVert": "‖",
}
FUNCTIONS = frozenset(
    [
        "sin",
        "cos",
        "tan",
        "cot",
        "sec",
        "csc",
        "arcsin",
        "arccos",
        "arctan",
        "sinh",
        "cosh",
        "tanh",
        "log",
        "ln",
        "exp",
        "lim",
        "max",
        "min",
        "det",
        "gcd",
    ]
)
SPACES = {",": "thin", ":": "medium", ";": "thick", " ": "word", "quad": "quad", "qquad": "qquad"}
STRUCTURES = frozenset(
    (
        "frac",
        "dfrac",
        "tfrac",
        "sqrt",
        "text",
        "mathrm",
        "operatorname",
        "left",
        "right",
        "begin",
        "end",
        "limits",
        "nolimits",
        "tag",
        "notag",
        "nonumber",
        "label",
        "ref",
        "eqref",
        "newline",
        "linebreak",
    )
)
ACCENTS = frozenset(
    (
        "vec",
        "overrightarrow",
        "overleftarrow",
        "overleftrightarrow",
        "bar",
        "overline",
        "underline",
        "hat",
        "widehat",
        "tilde",
        "widetilde",
        "dot",
        "ddot",
    )
)
COMMANDS = (
    ACCENTS
    | {"hline", "cline"}
    | frozenset(SYMBOLS)
    | FUNCTIONS
    | frozenset(SPACES)
    | STRUCTURES
    | frozenset("{}|%#&$_")
)
MATRIX_ENVIRONMENTS = frozenset(
    ("matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix", "cases", "smallmatrix")
)
ALIGN_ENVIRONMENTS = frozenset(
    ("aligned", "gathered", "split", "align*", "gather*", "align", "gather")
)
ENVIRONMENTS = MATRIX_ENVIRONMENTS | ALIGN_ENVIRONMENTS | {"equation", "equation*", "array"}
BINARY = frozenset("+−×∗⋅÷±∓∪∩∧∨")
RELATION = frozenset("=<>≤≥≠≈≡∼∝∈∉∋⊂⊆⊃⊇→←↔↑↓⇒⇐⇔⊥∥∶")
OPERATORS = frozenset("∑∏∫∮")
DIRECT = (
    BINARY
    | RELATION
    | frozenset(SYMBOLS.values())
    | frozenset("ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ")
    | frozenset("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+-−=*/().,;:[]|!．")
)


def symbol_class(char):
    if char in BINARY:
        return "bin"
    if char in RELATION:
        return "rel"
    if char in OPERATORS:
        return "op"
    if char in "(⟨[{":
        return "open"
    if char in ")⟩]}":
        return "close"
    if char in ",;:":
        return "punct"
    return "ord"


class MathSyntaxError(ValueError):
    def __init__(self, code, message, start, end):
        super().__init__(message)
        self.code, self.message, self.start, self.end = code, message, start, end


class Parser:
    def __init__(self, mapped):
        self.mapped, self.text, self.pos = mapped, mapped.text, 0
        self.depth = self.count = 0

    def fail(self, code, message, start=None, end=None):
        start = self.pos if start is None else start
        raise MathSyntaxError(
            code, message, start, min(len(self.text), start + 1) if end is None else end
        )

    def span(self, a, b):
        if a < b:
            return self.mapped.covering_span(a, b)
        at = (
            self.mapped.ranges[a].start
            if a < len(self.text)
            else self.mapped.ranges[-1].end
            if self.text
            else 0
        )
        return SourceSpan(at, at)

    def node(self, kind, a, b, children=(), value="", math_class="ord", attributes=()):
        self.count += 1
        if self.count > 4096:
            self.fail("math-budget", "Formula exceeds 4096 syntax nodes", a, b)
        return MathNode(
            kind, self.span(a, b), tuple(children), value, math_class, tuple(attributes)
        )

    def space(self):
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def command(self):
        a = self.pos
        self.pos += 1
        if self.pos == len(self.text):
            self.fail("math-command", "Incomplete command", a, self.pos)
        if self.text[self.pos].isascii() and self.text[self.pos].isalpha():
            while (
                self.pos < len(self.text)
                and self.text[self.pos].isascii()
                and self.text[self.pos].isalpha()
            ):
                self.pos += 1
        else:
            self.pos += 1
        return self.text[a + 1 : self.pos], a

    def at_command(self, name):
        value = "\\" + name
        if not self.text.startswith(value, self.pos):
            return False
        end = self.pos + len(value)
        return end == len(self.text) or not (self.text[end].isascii() and self.text[end].isalpha())

    def at_row_break(self):
        if self.text.startswith("\\\\", self.pos):
            return True
        match = scan_break(self.text, self.pos)
        return bool(match and match.name in LINE_COMMANDS and (match.error or match.strength == 4))

    def consume_row_break(self):
        if self.text.startswith("\\\\", self.pos):
            self.pos += 2
            return
        start = self.pos
        match = scan_break(self.text, self.pos)
        if not match or match.name not in LINE_COMMANDS:
            self.fail("math-line-break-context", "Expected an explicit row break")
        self.pos = match.end
        if match.error:
            self.fail("math-break-option", match.error, start, self.pos)

    def row(self, stop=None):
        self.depth += 1
        if self.depth > 32:
            self.fail("math-depth", "Formula nesting exceeds 32")
        a, children = self.pos, []
        while True:
            self.space()
            if self.pos == len(self.text) or (stop and stop()):
                break
            before = self.pos
            base = self.atom()
            arguments, roles = [base], []
            self.space()
            if self.at_command("limits") or self.at_command("nolimits"):
                command, start = self.command()
                if base.math_class != "op":
                    self.fail("math-limits", "Limits require an operator", start, self.pos)
                base = replace(base, attributes=base.attributes + (("limits", command),))
                arguments[0] = base
                self.space()
            while self.pos < len(self.text) and self.text[self.pos] in "_^":
                marker, start = self.text[self.pos], self.pos
                role = "sub" if marker == "_" else "sup"
                if any(k == role for k, _ in roles):
                    self.fail("math-script", "Duplicate " + role + "script", start)
                if base.kind == "Space":
                    self.fail("math-script", "A script needs a visible base", start)
                self.pos += 1
                self.space()
                if self.pos == len(self.text):
                    self.fail("math-script", "Missing script argument", start)
                argument = self.atom()
                if argument.kind == "Space":
                    self.fail("math-script", "A script cannot be spacing alone", start, self.pos)
                roles.append((role, str(len(arguments))))
                arguments.append(argument)
                self.space()
            if roles:
                base = self.node(
                    "Scripts",
                    before,
                    self.pos,
                    arguments,
                    math_class=base.math_class,
                    attributes=roles,
                )
            children.append(base)
            if self.pos <= before:
                raise RuntimeError("Math parser made no progress")
        self.depth -= 1
        # A binary sign at the start, after a relation/operator/open/punctuation,
        # or before a close/relation/end is unary. No glyph shape is substituted.
        visible = [
            i for i, n in enumerate(children) if n.kind not in {"Space", "Tag", "Label", "NoTag"}
        ]
        classes = [children[i].math_class for i in visible]
        for j, i in enumerate(visible):
            n = children[i]
            prev = classes[j - 1] if j else None
            after = children[visible[j + 1]].math_class if j + 1 < len(visible) else None
            if n.math_class == "bin" and (
                prev in {None, "bin", "rel", "op", "open", "punct"}
                or after in {None, "rel", "close", "punct"}
            ):
                children[i] = replace(n, math_class="ord")
        return self.node("Row", a, self.pos, children)

    def group(self):
        self.space()
        a = self.pos
        if self.text[self.pos : self.pos + 1] != "{":
            self.fail("math-group", "Expected a braced argument")
        self.pos += 1
        row = self.row(lambda: self.text[self.pos : self.pos + 1] == "}")
        if self.text[self.pos : self.pos + 1] != "}":
            self.fail("math-group", "Unclosed group", a, len(self.text))
        self.pos += 1
        return self.node("Group", a, self.pos, (row,))

    def argument(self, start, name, role="argument"):
        """Read one math atom or a braced list, keeping following scripts outside.

        Unlike a mandatory group, a TeX math argument may be one character or a
        command. Ungrouped command chains need their own depth guard because
        they do not pass through row(), which guards braced nesting.
        """
        self.space()
        if (
            self.pos == len(self.text)
            or self.text[self.pos : self.pos + 1] in {"}", "_", "^", "&"}
            or self.at_command("right")
            or self.at_command("end")
        ):
            self.fail("math-argument", f"Missing {role} for \\" + name, start, self.pos)
        ungrouped = self.text[self.pos : self.pos + 1] != "{"
        if ungrouped:
            self.depth += 1
            if self.depth > 32:
                self.fail("math-depth", "Formula nesting exceeds 32", start, self.pos)
        try:
            argument = self.atom()
        finally:
            if ungrouped:
                self.depth -= 1
        if argument.kind == "Space":
            self.fail(
                "math-argument",
                f"The {role} for \\" + name + " cannot be spacing alone",
                start,
                self.pos,
            )
        return argument

    @staticmethod
    def empty_group(argument):
        return argument.kind == "Group" and not argument.children[0].children

    def text_group(self, start, name):
        self.space()
        if self.text[self.pos : self.pos + 1] != "{":
            self.fail("math-group", "Expected a braced text argument")
        self.pos += 1
        children = []
        while self.pos < len(self.text) and self.text[self.pos] != "}":
            a, c = self.pos, self.text[self.pos]
            if c == "\\":
                c, _ = self.command()
                if c not in "{}_%#&$\\ ":
                    self.fail(
                        "math-text-command",
                        "Only escaped punctuation is allowed in text",
                        a,
                        self.pos,
                    )
            else:
                self.pos += 1
                if c in "{$" or (ord(c) < 32 and not c.isspace()):
                    self.fail(
                        "math-text",
                        "Nested groups, math and control characters are not supported in text",
                        a,
                        self.pos,
                    )
            children.append(self.node("Symbol", a, self.pos, value=" " if c.isspace() else c))
        if self.pos == len(self.text):
            self.fail("math-group", "Unclosed text argument", start, self.pos)
        self.pos += 1
        if not children:
            self.fail("math-empty", "Empty text argument", start, self.pos)
        return self.node(
            "Text",
            start,
            self.pos,
            children,
            math_class="op" if name == "operatorname" else "ord",
            attributes=(("style", name),),
        )

    def delimiter(self):
        self.space()
        a = self.pos
        if self.pos == len(self.text):
            self.fail("math-delimiter", "Missing delimiter")
        c = self.text[self.pos]
        if c == "\\":
            command, _ = self.command()
            c = SYMBOLS.get(command, "‖" if command == "|" else command if command in "{}" else "")
        else:
            self.pos += 1
        if c not in (".", "(", ")", "[", "]", "{", "}", "|", "‖", "⟨", "⟩"):
            self.fail("math-delimiter", "Unsupported delimiter", a, self.pos)
        return c, self.span(a, self.pos)

    def environment_name(self):
        self.space()
        a = self.pos
        if self.text[self.pos : self.pos + 1] != "{":
            self.fail("math-environment", "Expected an environment name")
        end = self.text.find("}", self.pos + 1)
        if end < 0:
            self.fail("math-environment", "Unclosed environment name", a, len(self.text))
        value = self.text[self.pos + 1 : end]
        self.pos = end + 1
        return value

    def matrix(self, start):
        name = self.environment_name()
        if name not in ENVIRONMENTS:
            self.fail("math-environment", "Unsupported environment: " + name, start, self.pos)
        if name == "array":
            from .array_parser import parse_array

            return parse_array(self, start)
        if name in {"equation", "equation*"}:
            body = self.row(lambda: self.at_command("end"))
            if not self.at_command("end"):
                self.fail("math-environment", "Unclosed equation environment", start, self.pos)
            self.command()
            if self.environment_name() != name:
                self.fail("math-environment", "Mismatched equation environment", start, self.pos)
            return self.node(
                "Equation", start, self.pos, (body,), attributes=(("environment", name),)
            )
        if name in ALIGN_ENVIRONMENTS:
            return self.alignment(start, name)
        rows, cells, row_start = [], [], self.pos
        while True:
            cell = self.row(
                lambda: (
                    self.text[self.pos : self.pos + 1] == "&"
                    or self.at_row_break()
                    or self.at_command("end")
                )
            )
            cells.append(cell)
            if len(cells) > 8 or sum(len(r.children) for r in rows) + len(cells) > 64:
                self.fail(
                    "math-matrix-budget", "Matrix exceeds 8 columns or 64 cells", start, self.pos
                )
            if self.text[self.pos : self.pos + 1] == "&":
                self.pos += 1
                continue
            rows.append(self.node("MatrixRow", row_start, self.pos, cells))
            if len(rows) > 8:
                self.fail("math-matrix-budget", "Matrix exceeds 8 rows", start, self.pos)
            if self.at_command("end"):
                self.command()
                ending = self.environment_name()
                if ending != name:
                    self.fail("math-environment", "Mismatched environment end", start, self.pos)
                break
            if self.at_row_break():
                self.consume_row_break()
                self.space()
                if self.text[self.pos : self.pos + 1] in {"[", "*"}:
                    self.fail(
                        "math-matrix-option",
                        "Per-row spacing and starred row breaks are unsupported; group a literal leading bracket",
                        self.pos,
                    )
                if self.at_command("end"):
                    self.fail("math-matrix", "Trailing empty matrix row is not supported", self.pos)
                row_start, cells = self.pos, []
                continue
            self.fail("math-environment", "Unclosed matrix environment", start, self.pos)
        sizes = {len(r.children) for r in rows}
        if len(sizes) != 1 or (name == "cases" and sizes != {2}):
            self.fail(
                "math-matrix", "Matrix rows need equal columns; cases needs two", start, self.pos
            )
        return self.node("Matrix", start, self.pos, rows, attributes=(("environment", name),))

    def alignment(self, start, name):
        self.space()
        position = "c"
        if self.text[self.pos : self.pos + 1] == "[":
            option_start = self.pos
            end = self.text.find("]", self.pos + 1)
            if (
                name not in {"aligned", "gathered"}
                or end < 0
                or self.text[self.pos + 1 : end].strip() not in {"t", "b", "c"}
            ):
                self.fail(
                    "math-alignment-option",
                    "Only aligned/gathered accept [t], [b] or [c]",
                    option_start,
                    end + 1 if end >= 0 else len(self.text),
                )
            position = self.text[self.pos + 1 : end].strip()
            self.pos = end + 1
        rows, cells, row_start, total = [], [], self.pos, 0
        gathered = name in {"gathered", "gather*", "gather"}
        limit = 1 if gathered else 2 if name == "split" else 8
        while True:
            cell = self.row(
                lambda: (
                    self.text[self.pos : self.pos + 1] == "&"
                    or self.at_row_break()
                    or self.at_command("end")
                )
            )
            # Alignment right columns have an implicit ordinary atom before a
            # leading binary operator, matching the intended continuation sign.
            if len(cells) % 2 and not gathered and cell.children:
                children = list(cell.children)
                for i, child in enumerate(children):
                    if child.kind != "Space":
                        if child.kind == "Symbol" and child.value in BINARY:
                            children[i] = replace(child, math_class="bin")
                        break
                cell = replace(cell, children=tuple(children))
            cells.append(cell)
            total += 1
            if len(cells) > limit or total > 256:
                self.fail(
                    "math-alignment-budget",
                    "Alignment exceeds its column limit or 256 cells",
                    start,
                    self.pos,
                )
            if self.text[self.pos : self.pos + 1] == "&":
                self.pos += 1
                continue
            rows.append(self.node("AlignmentRow", row_start, self.pos, cells))
            if len(rows) > 32:
                self.fail("math-alignment-budget", "Alignment exceeds 32 rows", start, self.pos)
            if self.at_row_break():
                self.consume_row_break()
                self.space()
                if self.text[self.pos : self.pos + 1] in {"[", "*"}:
                    self.fail(
                        "math-alignment-option",
                        "Per-row spacing and starred row breaks are unsupported; group a literal leading bracket",
                        self.pos,
                    )
                if not self.at_command("end"):
                    row_start, cells = self.pos, []
                    continue
            if not self.at_command("end"):
                self.fail("math-environment", "Unclosed alignment environment", start, self.pos)
            self.command()
            if self.environment_name() != name:
                self.fail("math-environment", "Mismatched environment end", start, self.pos)
            break
        return self.node(
            "Alignment",
            start,
            self.pos,
            rows,
            attributes=(("environment", name), ("position", position)),
        )

    def atom(self):
        self.space()
        a = self.pos
        if self.pos == len(self.text):
            self.fail("math-argument", "Missing argument")
        c = self.text[self.pos]
        if c == "{":
            return self.group()
        if c in "}_^&":
            self.fail("math-unexpected", "Unexpected math syntax: " + c)
        if c != "\\":
            self.pos += 1
            if c not in DIRECT and not is_han(c):
                self.fail("math-symbol", "Unsupported direct math character: " + c, a, self.pos)
            # Only math ASCII hyphen/star denote mathematical minus/multiplication.
            c = {"-": "−", "*": "∗", "．": "."}.get(c, c)
            return self.node("Symbol", a, self.pos, value=c, math_class=symbol_class(c))
        name, _ = self.command()
        if name in FRAME_COMMANDS | PAGE_COMMANDS:
            self.fail(
                "math-frame-break-context" if name in FRAME_COMMANDS else "math-page-break-context",
                "Page/frame controls belong in body text outside math", a, self.pos,
            )
        if name in LINE_COMMANDS:
            match = scan_break(self.text, a)
            self.pos = match.end
            if match.error:
                self.fail("math-break-option", match.error, a, self.pos)
            if match.strength < 4:
                return self.node("Space", a, self.pos, value="zero")
            self.fail(
                "math-line-break-context",
                "Use newline/linebreak inside aligned, matrix, cases or array", a, self.pos,
            )
        if name in ACCENTS:
            self.depth += 1
            if self.depth > 32:
                self.fail("math-depth", "Formula nesting exceeds 32", a, self.pos)
            argument = self.atom()
            self.depth -= 1
            if argument.kind == "Group" and not argument.children[0].children:
                self.fail("math-empty", "Accent argument cannot be empty", a, self.pos)
            return self.node("Accent", a, self.pos, (argument,), value=name)
        if name in {"hline", "cline"}:
            self.fail(
                "math-array-rule-position", "Array rules belong at row boundaries", a, self.pos
            )
        if name == "tag":
            starred = self.text[self.pos : self.pos + 1] == "*"
            if starred:
                self.pos += 1
            content = self.text_group(a, "tag")
            return self.node(
                "Tag",
                a,
                self.pos,
                (content,),
                attributes=(("parentheses", "false" if starred else "true"),),
            )
        if name in {"notag", "nonumber"}:
            return self.node("NoTag", a, self.pos)
        if name in {"label", "ref", "eqref"}:
            value = self.environment_name()
            if (
                not value
                or len(value) > 128
                or any(c.isspace() or c in "{}\\" or ord(c) < 32 for c in value)
            ):
                self.fail(
                    "math-label-key",
                    "Equation label keys must contain 1-128 non-space characters",
                    a,
                    self.pos,
                )
            return self.node(
                "Label" if name == "label" else "Reference",
                a,
                self.pos,
                value=value,
                attributes=(("parentheses", "true" if name == "eqref" else "false"),),
            )
        if name in SYMBOLS or name in ("{", "}", "|", "%", "#", "&", "$", "_"):
            value = SYMBOLS.get(name, "‖" if name == "|" else name)
            return self.node("Symbol", a, self.pos, value=value, math_class=symbol_class(value))
        if name in SPACES:
            return self.node("Space", a, self.pos, value=SPACES[name])
        if name in FUNCTIONS:
            children = [self.node("Symbol", a, self.pos, value=c) for c in name]
            return self.node("Operator", a, self.pos, children, math_class="op", value=name)
        if name == "mathrm":
            self.space()
            argument_start = self.pos
            argument = self.argument(a, name)
            if argument.kind != "Group":
                # Keep a structure's own style/attributes inside the roman scope.
                row = self.node("Row", argument_start, self.pos, (argument,))
                argument = self.node("Group", argument_start, self.pos, (row,))
            return replace(argument, span=self.span(a, self.pos), attributes=(("style", "mathrm"),))
        if name in ("text", "operatorname"):
            return self.text_group(a, name)
        if name in ("frac", "dfrac", "tfrac"):
            numerator = self.argument(a, name, "numerator argument")
            denominator = self.argument(a, name, "denominator argument")
            if self.empty_group(numerator) or self.empty_group(denominator):
                self.fail("math-empty", "Fraction arguments cannot be empty", a, self.pos)
            return self.node(
                "Fraction", a, self.pos, (numerator, denominator), attributes=(("style", name),)
            )
        if name == "sqrt":
            self.space()
            degree = None
            if self.text[self.pos : self.pos + 1] == "[":
                self.pos += 1
                degree = self.row(lambda: self.text[self.pos : self.pos + 1] == "]")
                if self.text[self.pos : self.pos + 1] != "]" or not degree.children:
                    self.fail("math-radical", "Invalid root degree", a, self.pos)
                self.pos += 1
            radicand = self.argument(a, name, "radicand argument")
            if self.empty_group(radicand):
                self.fail("math-empty", "Empty radicand", a, self.pos)
            return self.node(
                "Radical",
                a,
                self.pos,
                ((degree, radicand) if degree else (radicand,)),
                attributes=(("indexed", str(bool(degree)).lower()),),
            )
        if name == "left":
            left, left_span = self.delimiter()
            content = self.row(lambda: self.at_command("right"))
            if not self.at_command("right"):
                self.fail("math-delimiter", "Missing matching right delimiter", a, self.pos)
            self.command()
            right, right_span = self.delimiter()
            return self.node(
                "Delimited",
                a,
                self.pos,
                (content,),
                attributes=(
                    ("left", left),
                    ("right", right),
                    ("left_span", f"{left_span.start}:{left_span.end}"),
                    ("right_span", f"{right_span.start}:{right_span.end}"),
                ),
            )
        if name == "begin":
            return self.matrix(a)
        if name in ("right", "end", "limits", "nolimits", "\\"):
            self.fail("math-unexpected", "Command is misplaced: \\" + name, a, self.pos)
        self.fail("math-command-unsupported", "Unsupported command: \\" + name, a, self.pos)


def parse_math(source: MappedText | str, *, offset=0) -> MathParseResult:
    mapped = MappedText.original(source, offset) if isinstance(source, str) else source
    parser = Parser(mapped)
    span = mapped.covering_span() if mapped.text else SourceSpan(offset, offset)
    try:
        if len(mapped.text) > 4096:
            parser.fail("math-budget", "Formula exceeds 4096 scalars", 0, len(mapped.text))
        root = parser.row()
        if not root.children:
            parser.fail("math-empty", "Empty formula", 0, len(mapped.text))
        return MathParseResult(mapped.text, span, root, ())
    except MathSyntaxError as error:
        return MathParseResult(
            mapped.text,
            span,
            None,
            (Diagnostic(error.code, error.message, parser.span(error.start, error.end)),),
        )

"""Document-wide limits, separate from LRU weights and per-resource validation."""

from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps

from .cancellation import check_cancel

LIMITS_VERSION = "mixed-document-limits-v1"


@dataclass(frozen=True)
class DocumentLimits:
    tokens: int = 100_000
    nodes: int = 50_000
    depth: int = 64
    pages: int = 200
    points: int = 2_000_000
    expanded_points: int = 20_000_000

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in vars(self).values()):
            raise ValueError("Document limits must be positive integers")


DEFAULT_LIMITS = DocumentLimits()
_active = ContextVar("inkstruct_document_budget", default=None)


class DocumentLimitError(ValueError):
    def __init__(self, kind, actual, limit):
        self.kind, self.actual, self.limit = kind, actual, limit
        labels = {
            "tokens": "Markdown 解析 token 总数",
            "block_tokens": "Markdown 块 token 数",
            "parser_depth": "Markdown 解析嵌套深度（nesting）",
            "nodes": "语义及数学节点总数",
            "depth": "结构嵌套深度",
            "pages": "页面总数",
            "points": "页面路径点总数",
            "expanded_points": "本次布局累计展开点数",
        }
        super().__init__(
            f"文档{labels[kind]}超限：{actual:,}，上限 {limit:,}。"
            "请拆分文档、减少重复内容或简化路径；源码可保存为草稿。"
        )


def policy_key():
    return LIMITS_VERSION, DEFAULT_LIMITS


def check_limit(kind, value, limits=None):
    limit = getattr(limits or DEFAULT_LIMITS, kind)
    if value > limit:
        raise DocumentLimitError(kind, value, limit)


class WorkBudget:
    def __init__(self):
        self.limits = DEFAULT_LIMITS
        self.tokens = self.expanded_points = 0

    def add(self, kind, count):
        value = getattr(self, kind) + count
        check_limit(kind, value, self.limits)
        setattr(self, kind, value)


def created_token():
    if budget := _active.get():
        budget.add("tokens", 1)


def expanded_points(count):
    if budget := _active.get():
        budget.add("expanded_points", count)


def allocating_page(count):
    if budget := _active.get():
        check_limit("pages", count, budget.limits)


class PointAccumulator:
    """Early per-stage point bound, including unmerged borders and repeated content."""

    def __init__(self, pages=()):
        self.count = sum(len(op.points) for p in pages for op in (*p.paint_ops, *p.preview_ops))
        check_limit("points", self.count)

    def add(self, count):
        check_limit("points", self.count + count)
        self.count += count


class BudgetedOps(list):
    """Append-only staging list; existing values must already belong to its meter."""

    def __init__(self, meter, existing=()):
        super().__init__(existing)
        self.meter = meter

    def append(self, op):
        self.meter.add(len(op.points))
        super().append(op)

    def extend(self, ops):
        for op in ops:
            self.append(op)


def validate_nodes(nodes, *, cancelled=None):
    """Iterative audit before recursive consumers, counting every placed tree edge."""
    stack = [(node, 1) for node in reversed(nodes)]
    count = 0
    while stack:
        check_cancel(cancelled)
        node, depth = stack.pop()
        count += 1
        check_limit("nodes", count)
        check_limit("depth", depth)
        math = getattr(node, "math", None)
        if math is not None:
            stack.append((math, depth + 1))
        stack.extend((child, depth + 1) for child in reversed(node.children))


def validate_snapshot(snapshot, *, cancelled=None):
    # Existing plain-text/standalone tools retain their original limits.
    if not snapshot.layout_version.startswith("markdown-"):
        return
    check_limit("pages", len(snapshot.pages))
    points = 0
    for page in snapshot.pages:
        check_cancel(cancelled)
        for op in (*page.paint_ops, *page.preview_ops):
            points += len(op.points)
            check_limit("points", points)


def bounded_parse(function):
    @wraps(function)
    def run(*args, **kwargs):
        token = _active.set(WorkBudget())
        try:
            return function(*args, **kwargs)
        finally:
            _active.reset(token)

    return run


def bounded_layout(function):
    @wraps(function)
    def run(document, *args, **kwargs):
        cancelled = kwargs.get("cancelled")
        owner = _active.get() is None
        token = _active.set(WorkBudget()) if owner else None
        try:
            if owner:
                validate_nodes(document.nodes, cancelled=cancelled)
            result = function(document, *args, **kwargs)
            validate_snapshot(result, cancelled=cancelled)
            return result
        finally:
            if token is not None:
                _active.reset(token)

    return run

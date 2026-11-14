"""Opt-in local observations. The trace never participates in generation decisions."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass

_sink = ContextVar("inkstruct_donor_observer", default=None)


@dataclass(frozen=True)
class Donor:
    writer: str
    character: str
    sample: str
    sha256: str
    source: tuple
    target: tuple


def observer():
    return _sink.get()


@contextmanager
def capture(sink):
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


def emit(sink, route, stage, outcome, *, donor=None, **details):
    if sink is not None:
        event = {"route": route, "stage": stage, "outcome": outcome, **details}
        if donor is not None:
            event["donor"] = asdict(donor)
        sink(event)

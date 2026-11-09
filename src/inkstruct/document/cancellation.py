"""Cooperative cancellation shared by parsing and layout workers."""


class LayoutCancelled(RuntimeError):
    pass


def check_cancel(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise LayoutCancelled("Layout cancelled")

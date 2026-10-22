"""Only in experiment child processes; unchanged production cancellation on load."""
import inspect
import textwrap

def stable_viewport_changed(original):
    source=textwrap.dedent(inspect.getsource(original))
    before="if self._job and self._job.index not in self.pages_in_rect(visible):"
    after="if self._job and self._job.index not in self.pages_in_rect(visible) and (not self.viewport_ready() or not tuple(self.pages_in_rect(visible)) or min(abs(self._job.index-i) for i in self.pages_in_rect(visible)) > 1):"
    assert source.count(before)==1
    namespace=dict(original.__globals__);exec(source.replace(before,after),namespace)
    return namespace['viewport_changed']

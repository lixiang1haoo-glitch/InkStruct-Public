"""Exact warning membership, moving the inner prefix loop into str.startswith.

This preserves every warning and accepted-state rule. It replaces a Python
O(selections * semantic owners) generator with the equivalent C prefix tuple.
"""
def warning_membership(self,*,pending_only=False):
    document=getattr(self,'markdown_document',None)
    if document is None:return []
    ids={o.occurrence_id for o in document.occurrences}
    prefixes=tuple(n.node_id+':math-rule:' for root in document.nodes for n in root.walk())
    ids.update(key for key in self.resolver.selections if key.startswith(prefixes))
    return self.resolver.usage_warnings(pending_only=pending_only,occurrence_ids=ids)

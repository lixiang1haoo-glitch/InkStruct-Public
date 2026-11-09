"""Versioned, opt-in retrieval restrictions; never edit upstream structure data.

These are reviewed transfer-unit exceptions, not character decompositions or
general shape classifiers. Whole ancestors and independent stroke fallback stay
available. Parent/role mismatches alone are not grounds for rejection.
"""
from __future__ import annotations

import copy

VERSION = 'author_reuse_no_split_v1'
RULES = ({'id': 'yin_no_split_yi_shi_v1', 'parent': '尹', 'children': ['一', '尸'],
          'disabled_path': '尹→一＋尸',
          'reason': '人工确认：尸的左撇不穿头，不能作为尹对应笔画的直接迁移单元',
          'confirmed_case': '群←炉：目标第1、3、4笔经君→尹→尸复用户的去点部分',
          'allowed': '完整尹、完整君、户中的尸及可靠作者单笔'},)


class ReuseRules:
    def __init__(self, enabled=False):
        self.enabled = enabled

    def boundaries(self, graph):
        if not self.enabled:
            return []
        nodes = {n.component_id: n for n in graph.components}
        result = []
        for parent in graph.components:
            for rule in RULES:
                children = [nodes[k] for k in parent.children_ids if k in nodes]
                if (parent.canonical == rule['parent']
                        and sorted(c.canonical for c in children) == sorted(rule['children'])):
                    result.append((parent, children, rule))
        return result

    def check(self, graph, stroke_ids, *, side):
        ids = set(stroke_ids)
        for parent, children, rule in self.boundaries(graph):
            # Whole 尹 or an enclosing 君 is explicitly permitted. This tests
            # ownership, not fragile virtual-node IDs, and catches cached plans.
            if ids and any(ids <= set(c.stroke_ids) for c in children):
                return {'accepted': False, 'version': VERSION, 'rule': rule,
                        'side': side, 'character': graph.character,
                        'parent_component': parent.component_id,
                        'parent_stroke_ids': list(parent.stroke_ids),
                        'rejected_stroke_ids': list(stroke_ids)}
        return {'accepted': True, 'version': VERSION, 'enabled': self.enabled}

    def view(self, graph):
        """Hide forbidden descendants in a copy, keeping complete parent nodes."""
        if not self.enabled:
            return graph, []
        out = copy.deepcopy(graph)
        removed, diagnostics = set(), []
        nodes = {n.component_id: n for n in out.components}
        for parent, children, rule in self.boundaries(out):
            queue = [c.component_id for c in children]
            while queue:
                key = queue.pop()
                if key in removed:
                    continue
                removed.add(key)
                queue.extend(nodes[key].children_ids)
            parent.children_ids = []
            diagnostics.append({'version': VERSION, 'rule': rule,
                                'character': graph.character, 'parent_component': parent.component_id,
                                'action': 'hide descendants for author retrieval only'})
        out.components = [n for n in out.components if n.component_id not in removed]
        return out, diagnostics

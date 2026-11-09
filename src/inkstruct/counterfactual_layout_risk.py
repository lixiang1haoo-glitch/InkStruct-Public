"""Grouped paired evidence from fixed training-only layout interventions."""
from __future__ import annotations

from .component_layout_risk import ComponentLayoutRiskGate


class CounterfactualLayoutRiskGate(ComponentLayoutRiskGate):
    """Several trial moves still contribute at most one author-character vote."""
    def __init__(self, examples):
        keys = [(e['writer'], e['character'], e['component_id'], e['proposal_id']) for e in examples]
        if len(set(keys)) != len(keys):
            raise ValueError('duplicate grouped counterfactual proposal')
        self.examples = sorted(examples, key=lambda e: (
            e['writer'], e['character'], e['component_id'], e['proposal_id']))
